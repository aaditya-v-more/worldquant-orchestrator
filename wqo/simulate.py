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

import os
import socket
import threading
import time
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Iterable, Optional

from . import config, endpoints
from .session import ApiError, BrainSession
from .store import SLOT_POLL_INTERVAL, Ledger, check_simulation_budget

SLOTS_KEY = "learned_concurrency"

#: Clean simulations required before trying one more concurrent slot.
GROWTH_STREAK = 3
#: Clean simulations required before re-probing a level BRAIN already threw a
#: 429 at. Deliberately much larger than GROWTH_STREAK.
RETRY_CEILING_STREAK = 25


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


def _owner_id() -> str:
    """Identify this process/thread in the shared queue, for diagnostics."""
    return f"{socket.gethostname()}:{os.getpid()}:{threading.current_thread().name}"


class SlotManager:
    """Adaptive concurrency limiter, shared across processes.

    Starts at whatever concurrency was learned on a previous run (1 for a fresh
    account), grows by one after a run of clean acquisitions, and shrinks
    immediately on a 429. Growth is gated on a ``_throttled`` flag so that, once
    a 429 proves the limit too high, the next clean run only clears the flag and
    does not grow — this keeps a single-slot account from drifting up to the max
    on polling traffic that never sees a 429. The session's own 429 retry loop
    is the safety net; this just avoids walking into the wall repeatedly.

    The limit is enforced **per account, not per process**. With a ledger
    attached, :meth:`acquire` takes a ticket in the ledger's ``slot_queue``
    table and blocks until it is granted, so several agents running `wqo` at
    the same time form one queue instead of each firing at the account's only
    slot and collecting 429s.
    """

    def __init__(
        self,
        ledger: Optional[Ledger] = None,
        initial: Optional[int] = None,
        *,
        cross_process: bool = True,
        label: Optional[str] = None,
    ):
        self.ledger = ledger
        learned = ledger.get(SLOTS_KEY) if ledger else None
        self.limit = int(initial or learned or config.DEFAULT_CONCURRENCY)
        self.limit = max(1, min(self.limit, config.MAX_CONCURRENCY))
        self._active = 0
        self._clean_streak = 0
        # Set when a POST 429 proves the current limit too high; cleared by the
        # next clean acquisition. Growth is blocked while it is set so a single
        # success can never immediately undo a real throttle signal.
        self._throttled = False
        # The lowest limit BRAIN has ever throttled us at. Growing back to it
        # requires a much longer clean streak, so a 1-slot account settles at 1
        # instead of oscillating 1 -> 2 -> 429 -> 1 forever.
        self._ceiling: Optional[int] = None
        self._cond = threading.Condition()
        self._shared = bool(ledger) and cross_process
        self._label = label

    def acquire(self, label: Optional[str] = None) -> Optional[int]:
        """Block until a slot is free. Returns the ticket to hand to release()."""
        with self._cond:
            while self._active >= self.limit:
                self._cond.wait()
            self._active += 1
        if not self._shared:
            return None
        try:
            return self._acquire_shared(label or self._label)
        except Exception:
            # Never let a queue failure strand the in-process counter.
            with self._cond:
                self._active -= 1
                self._cond.notify()
            raise

    def _acquire_shared(self, label: Optional[str]) -> int:
        assert self.ledger is not None
        ticket = self.ledger.enqueue_slot(_owner_id(), label)
        while True:
            # The limit can shrink under us after a 429 in another agent, so it
            # is re-read from the ledger rather than captured once.
            limit = self._shared_limit()
            if self.ledger.try_grant_slot(ticket, limit):
                return ticket
            if not self.ledger.slot_ticket_alive(ticket):
                # Reaped while waiting — this process stalled. Rejoin the line.
                ticket = self.ledger.enqueue_slot(_owner_id(), label)
            time.sleep(SLOT_POLL_INTERVAL)

    def _shared_limit(self) -> int:
        if not self.ledger:
            return self.limit
        learned = self.ledger.get(SLOTS_KEY)
        limit = int(learned) if learned else self.limit
        return max(1, min(limit, config.MAX_CONCURRENCY))

    def heartbeat(self, ticket: Optional[int]) -> None:
        """Keep a held slot from being reaped during a long simulation poll."""
        if ticket is not None and self.ledger:
            self.ledger.heartbeat_slot(ticket)

    def release(self, ticket: Optional[int] = None) -> None:
        if ticket is not None and self.ledger:
            self.ledger.release_slot(ticket)
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
            if self.limit >= config.MAX_CONCURRENCY:
                return
            # Re-probing a level BRAIN already rejected costs a 429 and a retry
            # cycle, so demand far more evidence before trying it again.
            needed = RETRY_CEILING_STREAK if self._at_ceiling() else GROWTH_STREAK
            if self._clean_streak >= needed:
                self.limit += 1
                self._clean_streak = 0
                self._persist()
                self._cond.notify_all()

    def _at_ceiling(self) -> bool:
        return self._ceiling is not None and self.limit + 1 >= self._ceiling

    def report_throttled(self) -> None:
        with self._cond:
            self._clean_streak = 0
            self._throttled = True
            # Remember the level that failed, keeping the lowest ever seen.
            self._ceiling = (
                self.limit if self._ceiling is None else min(self._ceiling, self.limit)
            )
            if self.limit > 1:
                self.limit -= 1
                self._persist()

    def _persist(self) -> None:
        if self.ledger:
            self.ledger.set(SLOTS_KEY, self.limit)


def _poll_until_done(
    session: BrainSession, sim_url: str, *, on_progress=None, heartbeat=None
) -> dict:
    """Poll a simulation progress URL until it resolves, honoring Retry-After."""
    deadline = time.monotonic() + config.PACING.poll_timeout
    while True:
        # Prove to the shared slot queue that this holder is still alive; a
        # simulation can poll for minutes and must not be reaped mid-flight.
        if heartbeat:
            heartbeat()
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

    ticket = slots.acquire(label=job.label) if slots else None
    try:
        # A 429 here is slot pressure; feed it straight to the SlotManager so it
        # shrinks the limit now rather than after this job burns its retry budget.
        response = session.request(
            "POST",
            endpoints.SIMULATIONS,
            json=job.payload(),
            on_throttle=slots.report_throttled if slots else None,
        )
        # No 429 check here: session.request() never returns a retryable status
        # — it either retries past it or raises ApiError. on_throttle above is
        # what feeds slot pressure back to the SlotManager.
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

        body = _poll_until_done(
            session,
            sim_url,
            on_progress=on_progress,
            heartbeat=(lambda: slots.heartbeat(ticket)) if slots else None,
        )
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
            slots.release(ticket)


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

    # A small fixed worker pool; SlotManager throttles how many are actually in
    # flight. Pooling matters because a mining run can queue thousands of jobs
    # and we will not spawn a thread each.
    #
    # Sized to the learned limit plus one rather than to MAX_CONCURRENCY. The
    # extra threads a bigger pool would create are harmless — SlotManager parks
    # them before they reach the shared queue — but they are also useless, and
    # one spare is enough to keep the pipeline warm if the limit grows mid-run.
    pool_size = min(len(jobs), max(2, slots.limit + 1), config.MAX_CONCURRENCY)

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
