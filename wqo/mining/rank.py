"""Scoring and shortlisting of simulation results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from ..config import GATE, GateThresholds
from ..simulate import SimResult


@dataclass
class Scored:
    result: SimResult
    score: float
    reasons: list[str]

    @property
    def alpha_id(self) -> Optional[str]:
        return self.result.alpha_id


def score(result: SimResult, thresholds: Optional[GateThresholds] = None) -> Scored:
    """Rank candidates by how close they are to being submittable.

    Sharpe dominates because it is the primary BRAIN criterion; fitness is
    weighted next; turnover contributes only as a penalty when it strays
    outside the acceptable band. Sign is ignored — a strongly negative alpha
    is a strongly positive one with a minus sign in front.
    """
    t = thresholds or GATE
    stats = result.stats
    reasons: list[str] = []

    if not result.ok:
        return Scored(result, float("-inf"), [result.error or "simulation failed"])

    sharpe = abs(float(stats.get("sharpe") or 0.0))
    fitness = abs(float(stats.get("fitness") or 0.0))
    turnover = float(stats.get("turnover") or 0.0)

    value = sharpe * 2.0 + fitness

    if turnover < t.min_turnover:
        value -= 2.0
        reasons.append(f"turnover {turnover:.3f} below {t.min_turnover}")
    elif turnover > t.max_turnover:
        # Scale the penalty with the overshoot rather than a flat hit.
        value -= 2.0 * (turnover - t.max_turnover) / max(t.max_turnover, 1e-9)
        reasons.append(f"turnover {turnover:.3f} above {t.max_turnover}")

    checks = stats.get("checks") or []
    failed = [c.get("name") for c in checks if c.get("result") == "FAIL"]
    if failed:
        value -= 1.0 * len(failed)
        reasons.append("failed BRAIN checks: " + ", ".join(str(f) for f in failed))

    if sharpe < t.min_sharpe:
        reasons.append(f"sharpe {sharpe:.3f} below {t.min_sharpe}")

    return Scored(result, value, reasons)


def shortlist(
    results: Iterable[SimResult],
    *,
    thresholds: Optional[GateThresholds] = None,
    limit: int = 10,
    require_clean: bool = True,
) -> list[Scored]:
    """Rank results, optionally keeping only ones with no failing BRAIN check."""
    t = thresholds or GATE
    scored = [score(r, t) for r in results if r.ok]
    if require_clean:
        kept = []
        for item in scored:
            stats = item.result.stats
            checks = stats.get("checks") or []
            if any(c.get("result") == "FAIL" for c in checks):
                continue
            if abs(float(stats.get("sharpe") or 0.0)) < t.min_sharpe:
                continue
            kept.append(item)
        scored = kept
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:limit]
