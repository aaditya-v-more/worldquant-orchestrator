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
from .store import Ledger, check_submission_budget


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
    if ledger:
        check_submission_budget(ledger)

    response = session.request("POST", endpoints.alpha_submit(alpha_id))
    if response.status_code >= 400:
        detail = response.text[:400]
        if ledger:
            ledger.record_submission(alpha_id, "FAILED", {"detail": detail})
        raise ApiError(f"submission rejected ({response.status_code}): {detail}", response)

    # Submission is processed asynchronously; poll it out the same way as
    # any other Retry-After gated endpoint.
    deadline = time.monotonic() + config.PACING.poll_timeout
    payload: Any = None
    while True:
        if response.headers.get("Retry-After") is None:
            if response.content and response.content.strip():
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
            break
        if time.monotonic() > deadline:
            raise ApiError(f"submission of {alpha_id} did not resolve in time")
        session.governor.sleep_retry_after(response)
        response = session.request("GET", endpoints.alpha_submit(alpha_id))
        if response.status_code >= 400:
            detail = response.text[:400]
            if ledger:
                ledger.record_submission(alpha_id, "FAILED", {"detail": detail})
            raise ApiError(
                f"submission failed ({response.status_code}): {detail}", response
            )

    if ledger:
        ledger.record_submission(alpha_id, "SUBMITTED", payload)
    return {
        "alpha_id": alpha_id,
        "url": endpoints.alpha_url(alpha_id),
        "outcome": "SUBMITTED",
        "detail": payload,
    }
