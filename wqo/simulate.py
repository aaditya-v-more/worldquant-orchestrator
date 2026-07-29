"""Alpha simulation: submit, poll, normalize, record.

The BRAIN simulation flow is asynchronous:

    POST /simulations              -> 201 + Location: <progress url>
    GET  <progress url>            -> {"progress": 0.42}   (repeat, honoring Retry-After)
    GET  <progress url>            -> {"alpha": "<id>"}    (done)
    GET  /alphas/<id>              -> full record with is.checks / is.sharpe / ...

Slot pressure shows up as a 429 on the POST. :class:`SlotManager` learns the
account's real concurrency from those 429s instead of assuming a tier.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Iterable, Optional

from . import config, endpoints
from .session import ApiError, BrainSession
from .store import Ledger, check_simulation_budget

SLOTS_KEY = "learned_concurrency"


@dataclass
class SimJob:
    code: str
    settings: dict
    label: Optional[str] = None

    def payload(self) -> dict:
        return {"type": "REGULAR", "settings": self.settings, "regular": self.code}


@dataclass
class SimResult:
    code: str
    settings: dict
    status: str  # COMPLETE | ERROR
    alpha_id: Optional[str] = None
    alpha: Optional[dict] = None
    error: Optional[str] = None
    sim_url: Optional[str] = None
    label: Optional[str] = None
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "COMPLETE"

    @property
    def stats(self) -> dict:
        return (self.alpha or {}).get("is") or {}

    def summary(self) -> dict:
        s = self.stats
        return {
            "label": self.label,
            "code": self.code,
            "status": self.status,
            "alpha_id": self.alpha_id,
            "url": endpoints.alpha_url(self.alpha_id) if self.alpha_id else None,
            "sharpe": s.get("sharpe"),
            "fitness": s.get("fitness"),
            "turnover": s.get("turnover"),
            "returns": s.get("returns"),
            "drawdown": s.get("drawdown"),
            "margin": s.get("margin"),
            "checks_passed": _checks_passed(s),
            "error": self.error,
            "cached": self.cached,
        }


def _checks_passed(is_stats: dict) -> Optional[str]:
    checks = is_stats.get("checks")
    if not checks:
        return None
    passed = sum(1 for c in checks if c.get("result") == "PASS")
    return f"{passed}/{len(checks)}"


def build_settings(**overrides) -> dict:
    """Merge caller overrides onto :data:`config.DEFAULT_SETTINGS`."""
    settings = dict(config.DEFAULT_SETTINGS)
    for key, value in overrides.items():
        if value is not None:
            settings[key] = value
    return settings


class SlotManager:
    """Adaptive concurrency limiter.

    Starts at whatever concurrency was learned on a previous run (1 for a fresh
    account), grows by one after a run of clean acquisitions, and shrinks
    immediately on a 429. Growth is gated on a ``_throttled`` flag so that, once
    a 429 proves the limit too high, the next clean run only clears the flag and
    does not grow — this keeps a single-slot account from drifting up to the max
    on polling traffic that never sees a 429. The session's own 429 retry loop
    is the safety net; this just avoids walking into the wall repeatedly.
    """

    def __init__(self, ledger: Optional[Ledger] = None, initial: Optional[int] = None):
        self.ledger = ledger
        learned = ledger.get(SLOTS_KEY) if ledger else None
        self.limit = int(initial or learned or config.DEFAULT_CONCURRENCY)
        self.limit = max(1, min(self.limit, config.MAX_CONCURRENCY))
        self._active = 0
        self._clean_streak = 0
        # Set when a POST 429 proves the current limit too high; cleared by the
        # next clean acquisition. Growth is blocked while it is set so a single
        # polling success can never undo a real throttle signal.
        self._throttled = False
        self._cond = threading.Condition()

    def acquire(self) -> None:
        with self._cond:
            while self._active >= self.limit:
                self._cond.wait()
            self._active += 1

    def release(self) -> None:
        with self._cond:
            self._active -= 1
            self._cond.notify()

    def report_success(self) -> None:
        with self._cond:
            # A clean run is only evidence of spare capacity once we are not
            # reacting to a recent throttle; otherwise it just clears the flag.
            if self._throttled:
                self._throttled = False
                self._clean_streak = 0
                return
            self._clean_streak += 1
            if self._clean_streak >= 3 and self.limit < config.MAX_CONCURRENCY:
                self.limit += 1
                self._clean_streak = 0
                self._persist()
                self._cond.notify_all()

    def report_throttled(self) -> None:
        with self._cond:
            self._clean_streak = 0
            self._throttled = True
            if self.limit > 1:
                self.limit -= 1
                self._persist()

    def _persist(self) -> None:
        if self.ledger:
            self.ledger.set(SLOTS_KEY, self.limit)


def _poll_until_done(
    session: BrainSession, sim_url: str, *, on_progress=None
) -> dict:
    """Poll a simulation progress URL until it resolves, honoring Retry-After."""
    deadline = time.monotonic() + config.PACING.poll_timeout
    while True:
        response = session.request("GET", sim_url)
        if response.status_code >= 400:
            raise ApiError(
                f"simulation poll failed ({response.status_code}): "
                f"{response.text[:300]}",
                response,
            )
        try:
            body = response.json()
        except ValueError:
            body = {}

        if body.get("alpha"):
            return body
        status = str(body.get("status", "")).upper()
        if status in {"ERROR", "FAIL", "FAILED"}:
            raise ApiError(body.get("message") or f"simulation {status.lower()}")

        if on_progress and "progress" in body:
            on_progress(body["progress"])

        if time.monotonic() > deadline:
            raise ApiError(
                f"simulation did not finish within {config.PACING.poll_timeout:.0f}s: {sim_url}"
            )

        # Retry-After of 0 means "poll again now"; the loop handles that fine.
        session.governor.sleep_retry_after(response)


def simulate_one(
    session: BrainSession,
    job: SimJob,
    *,
    ledger: Optional[Ledger] = None,
    slots: Optional[SlotManager] = None,
    source: str = "manual",
    reuse_cached: bool = True,
    on_progress=None,
) -> SimResult:
    """Run one simulation end to end."""
    if ledger and reuse_cached:
        prior = ledger.find_by_code(job.code, job.settings)
        if prior and prior["alpha_id"]:
            alpha = session.json("GET", endpoints.alpha(prior["alpha_id"]))
            return SimResult(
                code=job.code,
                settings=job.settings,
                status="COMPLETE",
                alpha_id=prior["alpha_id"],
                alpha=alpha,
                label=job.label,
                cached=True,
            )

    if ledger:
        check_simulation_budget(ledger)
        row_id = ledger.start_simulation(
            job.code, job.settings, source=source, label=job.label
        )
    else:
        row_id = None

    if slots:
        slots.acquire()
    try:
        # A 429 here is slot pressure; feed it straight to the SlotManager so it
        # shrinks the limit now rather than after this job burns its retry budget.
        response = session.request(
            "POST",
            endpoints.SIMULATIONS,
            json=job.payload(),
            on_throttle=slots.report_throttled if slots else None,
        )
        if response.status_code == 429:
            if slots:
                slots.report_throttled()
            raise ApiError("simulation slots exhausted", response)
        if response.status_code >= 400:
            raise ApiError(
                f"simulation rejected ({response.status_code}): {response.text[:300]}",
                response,
            )
        sim_url = response.headers.get("Location")
        if not sim_url:
            raise ApiError(
                "simulation accepted but no Location header was returned; "
                f"body: {response.text[:300]}",
                response,
            )
        sim_url = endpoints.absolute(sim_url)
        if ledger and row_id is not None:
            ledger.attach_sim_url(row_id, sim_url)

        body = _poll_until_done(session, sim_url, on_progress=on_progress)
        alpha_id = body["alpha"]
        alpha = session.json("GET", endpoints.alpha(alpha_id))
        if slots:
            slots.report_success()
        if ledger and row_id is not None:
            ledger.finish_simulation(row_id, alpha)
        return SimResult(
            code=job.code,
            settings=job.settings,
            status="COMPLETE",
            alpha_id=alpha_id,
            alpha=alpha,
            sim_url=sim_url,
            label=job.label,
        )
    except Exception as exc:  # noqa: BLE001 — recorded and returned, not swallowed
        if ledger and row_id is not None:
            ledger.fail_simulation(row_id, str(exc))
        return SimResult(
            code=job.code,
            settings=job.settings,
            status="ERROR",
            error=str(exc),
            label=job.label,
        )
    finally:
        if slots:
            slots.release()


def simulate_many(
    session: BrainSession,
    jobs: Iterable[SimJob],
    *,
    ledger: Optional[Ledger] = None,
    slots: Optional[SlotManager] = None,
    source: str = "batch",
    reuse_cached: bool = True,
    on_result=None,
) -> list[SimResult]:
    """Run a batch of simulations, never exceeding the learned slot count."""
    jobs = list(jobs)
    if not jobs:
        return []
    if ledger:
        check_simulation_budget(ledger, wanted=len(jobs))
    slots = slots or SlotManager(ledger)

    queue: "Queue[SimJob]" = Queue()
    for job in jobs:
        queue.put(job)

    results: list[SimResult] = []
    results_lock = threading.Lock()

    # A fixed worker pool bounded by MAX_CONCURRENCY; SlotManager throttles how
    # many of these are actually in flight at once. Pooling matters because a
    # mining run can queue thousands of jobs and we will not spawn a thread each.
    pool_size = min(len(jobs), config.MAX_CONCURRENCY)

    def worker() -> None:
        while True:
            try:
                job = queue.get_nowait()
            except Empty:
                return
            result = simulate_one(
                session,
                job,
                ledger=ledger,
                slots=slots,
                source=source,
                reuse_cached=reuse_cached,
            )
            with results_lock:
                results.append(result)
                if on_result:
                    on_result(result)
            queue.task_done()

    threads = []
    for _ in range(pool_size):
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        threads.append(thread)
        # Stagger starts so the first burst does not all hit POST at once.
        time.sleep(config.PACING.min_interval)

    for thread in threads:
        thread.join()
    return results
