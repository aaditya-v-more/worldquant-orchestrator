"""Alpha submission — the one irreversible action in this tool.

Submission consumes daily quota and cannot be undone, so the API here is built
so that it *cannot* happen implicitly:

* :func:`prepare` is read-only. It gathers the full check report and is what
  should be shown to a human.
* :func:`submit` refuses unless ``confirmed=True`` is passed explicitly, and
  refuses again if the gate is not clean unless ``force=True``.

The CLI mirrors this: ``python -m wqo submit <id>`` only ever prints a report;
``--confirm`` is required to actually POST.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from . import alphas, config, endpoints, gate
from .session import ApiError, BrainSession
from .store import Ledger, SubmissionConflict


class SubmissionRefused(RuntimeError):
    pass


@dataclass
class Preparation:
    alpha: dict
    report: gate.GateReport
    self_corr: Optional[float]
    prod_corr: Optional[float]

    @property
    def alpha_id(self) -> str:
        return self.alpha.get("id", "")

    def to_dict(self) -> dict:
        return {
            "alpha_id": self.alpha_id,
            "url": endpoints.alpha_url(self.alpha_id) if self.alpha_id else None,
            "code": (self.alpha.get("regular") or {}).get("code"),
            "settings": self.alpha.get("settings"),
            "self_correlation": self.self_corr,
            "prod_correlation": self.prod_corr,
            "report": self.report.to_dict(),
        }


def fetch_brain_checks(session: BrainSession, alpha_id: str) -> Any:
    """Run BRAIN's authoritative pre-submission check.

    This is a read-only GET — it evaluates eligibility without submitting.
    """
    payload = alphas.await_payload(session, endpoints.alpha_check(alpha_id))
    if payload is None:
        return None
    if isinstance(payload, dict):
        # Responses have been seen shaped as {"is": {"checks": [...]}} and as
        # {"checks": [...]}; accept either.
        if "checks" in payload:
            return payload["checks"]
        inner = payload.get("is") or {}
        if "checks" in inner:
            return inner["checks"]
    return payload


def prepare(
    session: BrainSession,
    alpha_id: str,
    *,
    with_correlations: bool = True,
    with_brain_check: bool = True,
) -> Preparation:
    """Gather everything needed to decide on a submission. Makes no changes."""
    alpha = alphas.get(session, alpha_id)

    self_corr = prod_corr = None
    if with_correlations:
        try:
            self_corr = alphas.max_correlation(alphas.correlation(session, alpha_id, "self"))
        except ApiError:
            self_corr = None
        try:
            prod_corr = alphas.max_correlation(alphas.correlation(session, alpha_id, "prod"))
        except ApiError:
            prod_corr = None

    brain_checks = None
    if with_brain_check:
        try:
            brain_checks = fetch_brain_checks(session, alpha_id)
        except ApiError:
            brain_checks = None

    report = gate.build_report(
        alpha, brain_checks=brain_checks, self_corr=self_corr, prod_corr=prod_corr
    )
    return Preparation(
        alpha=alpha, report=report, self_corr=self_corr, prod_corr=prod_corr
    )


def submit(
    session: BrainSession,
    alpha_id: str,
    *,
    confirmed: bool = False,
    force: bool = False,
    ledger: Optional[Ledger] = None,
    preparation: Optional[Preparation] = None,
) -> dict:
    """Submit an alpha. Requires ``confirmed=True``.

    Raises :class:`SubmissionRefused` rather than submitting when unconfirmed,
    over budget, or blocked by the gate.
    """
    prep = preparation or prepare(session, alpha_id)

    if not confirmed:
        raise SubmissionRefused(
            "submission not confirmed — this is irreversible and consumes daily "
            "quota. Review the report, then pass --confirm."
        )
    if not prep.report.passed and not force:
        blocking = ", ".join(c.name for c in prep.report.failures) or "pending checks"
        raise SubmissionRefused(
            f"gate is not clean ({blocking}); pass --force to submit anyway"
        )
    if prep.alpha_id != alpha_id:
        raise SubmissionRefused("preparation belongs to a different alpha")
    if ledger is None:
        raise SubmissionRefused("submission requires a persistent quota ledger")
    if str(ledger.path) == ":memory:":
        raise SubmissionRefused("submission requires a persistent quota ledger")
    try:
        reservation = ledger.reserve_submission(alpha_id)
    except SubmissionConflict as exc:
        raise SubmissionRefused(str(exc)) from exc

    # The reservation survives interruption, timeout and process death. Only a
    # definite rejection releases it; an ambiguous response remains UNKNOWN.
    outcome = "UNKNOWN"
    payload: Any = None
    try:
        response = session.request("POST", endpoints.alpha_submit(alpha_id))
        if response.status_code in {400, 401, 403, 404, 422, 429}:
            outcome = "FAILED"
            raise ApiError(f"submission rejected ({response.status_code})", response)
        if not 200 <= response.status_code < 300:
            raise ApiError(f"submission outcome unknown ({response.status_code}); do not retry", response)

        deadline = time.monotonic() + config.PACING.poll_timeout
        while response.headers.get("Retry-After") is not None:
            if time.monotonic() > deadline:
                raise ApiError("submission did not resolve in time; do not retry")
            session.governor.sleep_retry_after(response)
            response = session.request("GET", endpoints.alpha_submit(alpha_id))
            if not 200 <= response.status_code < 300:
                raise ApiError(f"submission polling failed ({response.status_code}); do not retry", response)
        if response.status_code == 202:
            raise ApiError("submission accepted but not resolved; do not retry")
        if response.content and response.content.strip():
            try:
                payload = response.json()
            except ValueError:
                raise ApiError("submission returned an unreadable result; do not retry") from None
            if isinstance(payload, dict) and str(payload.get("status", "")).upper() in {
                "ERROR", "FAIL", "FAILED", "PENDING", "RUNNING", "IN_PROGRESS"
            }:
                raise ApiError("submission result is unresolved; verify on BRAIN and do not retry")
        outcome = "SUBMITTED"
    finally:
        ledger.finish_submission(reservation, outcome, payload)
    return {
        "alpha_id": alpha_id,
        "url": endpoints.alpha_url(alpha_id),
        "outcome": outcome,
        "detail": payload,
    }
