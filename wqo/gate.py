"""Pre-submission quality gate.

BRAIN's own ``/alphas/{id}/check`` is the authority on whether an alpha may be
submitted. This module does two things around it:

* renders those checks into a readable PASS/FAIL table, and
* applies our own local thresholds first, so obviously-doomed alphas never
  consume a check call or a slot in the daily submission quota.

Nothing here can make a submission succeed that BRAIN would reject. It only
ever stops submissions earlier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .config import GATE, GateThresholds

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARNING"
PENDING = "PENDING"
SKIPPED = "SKIPPED"


@dataclass
class Criterion:
    name: str
    status: str
    value: Optional[float] = None
    limit: Optional[float] = None
    detail: str = ""
    source: str = "local"  # local | brain

    @property
    def blocking(self) -> bool:
        return self.status == FAIL


@dataclass
class GateReport:
    alpha_id: Optional[str]
    criteria: list[Criterion] = field(default_factory=list)

    @property
    def failures(self) -> list[Criterion]:
        return [c for c in self.criteria if c.blocking]

    @property
    def warnings(self) -> list[Criterion]:
        return [c for c in self.criteria if c.status == WARN]

    @property
    def pending(self) -> list[Criterion]:
        return [c for c in self.criteria if c.status == PENDING]

    @property
    def passed(self) -> bool:
        return not self.failures and not self.pending

    def to_dict(self) -> dict:
        return {
            "alpha_id": self.alpha_id,
            "passed": self.passed,
            "failures": [c.name for c in self.failures],
            "warnings": [c.name for c in self.warnings],
            "pending": [c.name for c in self.pending],
            "criteria": [
                {
                    "name": c.name,
                    "status": c.status,
                    "value": c.value,
                    "limit": c.limit,
                    "detail": c.detail,
                    "source": c.source,
                }
                for c in self.criteria
            ],
        }

    def render(self) -> str:
        lines = [f"Alpha {self.alpha_id or '(unsaved)'}"]
        width = max((len(c.name) for c in self.criteria), default=10)
        for c in self.criteria:
            value = "-" if c.value is None else f"{c.value:.4g}"
            limit = "" if c.limit is None else f" (limit {c.limit:.4g})"
            note = f"  {c.detail}" if c.detail else ""
            lines.append(f"  {c.status:<8} {c.name:<{width}}  {value}{limit}{note}")
        verdict = "PASSED" if self.passed else "BLOCKED"
        lines.append(f"  => {verdict}")
        if self.failures:
            lines.append("  blocking: " + ", ".join(c.name for c in self.failures))
        if self.pending:
            lines.append(
                "  still computing: " + ", ".join(c.name for c in self.pending)
            )
        return "\n".join(lines)


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None


def evaluate_local(
    alpha: dict,
    *,
    self_corr: Optional[float] = None,
    prod_corr: Optional[float] = None,
    thresholds: Optional[GateThresholds] = None,
) -> list[Criterion]:
    """Apply our own thresholds to a fetched alpha record."""
    t = thresholds or GATE
    stats = alpha.get("is") or {}
    out: list[Criterion] = []

    sharpe = _num(stats.get("sharpe"))
    out.append(
        Criterion(
            "sharpe",
            PASS if sharpe is not None and abs(sharpe) >= t.min_sharpe else FAIL,
            sharpe,
            t.min_sharpe,
            detail="absolute value is used; a strongly negative alpha can be inverted",
        )
    )

    fitness = _num(stats.get("fitness"))
    out.append(
        Criterion(
            "fitness",
            PASS if fitness is not None and abs(fitness) >= t.min_fitness else FAIL,
            fitness,
            t.min_fitness,
        )
    )

    turnover = _num(stats.get("turnover"))
    if turnover is None:
        out.append(Criterion("turnover", FAIL, None, None, "not reported"))
    elif turnover < t.min_turnover:
        out.append(
            Criterion("turnover", FAIL, turnover, t.min_turnover, "too low / stale")
        )
    elif turnover > t.max_turnover:
        out.append(
            Criterion("turnover", FAIL, turnover, t.max_turnover, "too high / churny")
        )
    else:
        out.append(Criterion("turnover", PASS, turnover, t.max_turnover))

    drawdown = _num(stats.get("drawdown"))
    if drawdown is None:
        out.append(Criterion("drawdown", SKIPPED, None, t.max_drawdown, "not reported"))
    else:
        out.append(
            Criterion(
                "drawdown",
                PASS if abs(drawdown) <= t.max_drawdown else FAIL,
                abs(drawdown),
                t.max_drawdown,
                detail="peak-to-trough decline in cumulative PnL",
            )
        )

    if self_corr is None:
        out.append(Criterion("self_correlation", SKIPPED, None, t.max_self_correlation))
    else:
        over_limit = self_corr >= t.max_self_correlation
        # BRAIN allows an over-limit alpha through if its Sharpe beats the alpha
        # it correlates with by the exemption margin. We cannot evaluate that
        # here without the other alpha's Sharpe, so flag it rather than claiming
        # a definitive fail.
        exemption = int(t.self_correlation_sharpe_exemption * 100)
        out.append(
            Criterion(
                "self_correlation",
                FAIL if over_limit else PASS,
                self_corr,
                t.max_self_correlation,
                detail=(
                    f"over limit — still eligible only if Sharpe is >{exemption}% "
                    "better than the alpha it correlates with"
                    if over_limit
                    else "vs. your own submitted alphas"
                ),
            )
        )

    if prod_corr is None:
        out.append(Criterion("prod_correlation", SKIPPED, None, t.max_prod_correlation))
    else:
        out.append(
            Criterion(
                "prod_correlation",
                PASS if prod_corr < t.max_prod_correlation else FAIL,
                prod_corr,
                t.max_prod_correlation,
                detail="vs. production alphas",
            )
        )

    return out


def _brain_status(result: Any) -> str:
    text = str(result or "").upper()
    if text in {PASS, FAIL, WARN, PENDING}:
        return text
    if text in {"ERROR"}:
        return FAIL
    return text or PENDING


def evaluate_brain_checks(checks: Any) -> list[Criterion]:
    """Translate BRAIN's ``checks`` array into criteria."""
    out: list[Criterion] = []
    for check in checks or []:
        if not isinstance(check, dict):
            continue
        out.append(
            Criterion(
                name=str(check.get("name", "UNKNOWN")).lower(),
                status=_brain_status(check.get("result")),
                value=_num(check.get("value")),
                limit=_num(check.get("limit")),
                detail=str(check.get("message") or ""),
                source="brain",
            )
        )
    return out


def build_report(
    alpha: dict,
    *,
    brain_checks: Any = None,
    self_corr: Optional[float] = None,
    prod_corr: Optional[float] = None,
    thresholds: Optional[GateThresholds] = None,
) -> GateReport:
    """Combine local thresholds and BRAIN's checks into one report.

    ``brain_checks`` defaults to the ``is.checks`` already present on the alpha
    record, so a report can be produced without an extra ``/check`` call.
    """
    if brain_checks is None:
        brain_checks = (alpha.get("is") or {}).get("checks")
    criteria = evaluate_local(
        alpha, self_corr=self_corr, prod_corr=prod_corr, thresholds=thresholds
    )
    criteria.extend(evaluate_brain_checks(brain_checks))
    return GateReport(alpha_id=alpha.get("id"), criteria=criteria)
