"""SQLite ledger of everything this tool does.

Two jobs:

* an audit trail — every simulation, check, and submission is recorded with
  its full settings and result, so results are reproducible after the fact;
* budget enforcement — daily caps are counted straight off these tables.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS simulations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    REAL    NOT NULL,
    code          TEXT    NOT NULL,
    settings_json TEXT    NOT NULL,
    status        TEXT    NOT NULL,          -- PENDING | COMPLETE | ERROR
    sim_url       TEXT,
    alpha_id      TEXT,
    error         TEXT,
    sharpe        REAL,
    fitness       REAL,
    turnover      REAL,
    returns       REAL,
    drawdown      REAL,
    margin        REAL,
    long_count    INTEGER,
    short_count   INTEGER,
    checks_json   TEXT,
    source        TEXT,                      -- manual | mine | batch
    label         TEXT
);

CREATE INDEX IF NOT EXISTS idx_sim_created  ON simulations (created_at);
CREATE INDEX IF NOT EXISTS idx_sim_alpha    ON simulations (alpha_id);
CREATE INDEX IF NOT EXISTS idx_sim_code     ON simulations (code);

CREATE TABLE IF NOT EXISTS submissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  REAL NOT NULL,
    alpha_id    TEXT NOT NULL,
    outcome     TEXT NOT NULL,               -- SUBMITTED | FAILED
    detail_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_sub_created ON submissions (created_at);

CREATE TABLE IF NOT EXISTS kv (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);

-- Cross-process simulation slot queue.
--
-- BRAIN counts concurrent simulations per *account*, not per process. Two
-- agents working this repo at once each ran their own in-memory SlotManager,
-- each believing it held the account's only slot, and every second POST came
-- back 429. This table is the shared waiting line: one row per waiter, granted
-- in ticket order, capped at the learned concurrency.
CREATE TABLE IF NOT EXISTS slot_queue (
    ticket       INTEGER PRIMARY KEY AUTOINCREMENT,
    owner        TEXT NOT NULL,          -- host:pid:thread, for diagnostics
    label        TEXT,
    requested_at REAL NOT NULL,
    granted_at   REAL,                   -- NULL while still waiting
    heartbeat_at REAL NOT NULL           -- stale rows are reaped, see STALE_SLOT_AFTER
);

CREATE INDEX IF NOT EXISTS idx_slot_granted ON slot_queue (granted_at);
"""

#: A waiter or holder that has not touched its row in this many seconds is
#: assumed dead — killed agent, crashed process — and gets reaped so its slot
#: returns to the pool.
#:
#: Two invariants keep this safe, and both must hold if the number is changed:
#: waiters refresh their heartbeat on every ``try_grant_slot`` attempt (every
#: SLOT_POLL_INTERVAL), and holders refresh on every simulation poll — so the
#: gap between a holder's heartbeats is one ``Retry-After`` cycle. This must
#: stay comfortably above the largest Retry-After BRAIN sends, or a live
#: simulation gets reaped and a second agent starts one alongside it.
STALE_SLOT_AFTER = 180.0

#: How long to sleep between attempts to claim a slot.
SLOT_POLL_INTERVAL = 1.0


#: BRAIN runs on US Eastern. Every timestamp the API returns carries a -04:00
#: (EDT) or -05:00 (EST) offset, and `/users/self/activities/*` buckets its
#: daily counters on Eastern calendar dates — so that is where the quotas roll.
BRAIN_TZ_NAME = "America/New_York"

#: Used only if the host has no IANA database. EDT is the earlier of the two
#: possible midnights in UTC terms, so it widens the counting window rather
#: than narrowing it, and a missing tzdb can never let a budget overrun.
_BRAIN_TZ_FALLBACK = timezone(timedelta(hours=-4))


def _brain_tz() -> tzinfo:
    try:
        return ZoneInfo(BRAIN_TZ_NAME)
    except Exception:  # no system tzdata, no `tzdata` package
        return _BRAIN_TZ_FALLBACK


def _brain_day_start(ts: Optional[float] = None) -> float:
    """Epoch seconds at the most recent midnight *in BRAIN's timezone*.

    Counting on UTC midnight instead skews the window by four or five hours,
    which reports a fresh budget while the platform still counts yesterday's
    submissions against you.
    """
    now = datetime.fromtimestamp(ts if ts is not None else time.time(), tz=_brain_tz())
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()


class Ledger:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else config.LEDGER_PATH
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False because simulate_many runs a worker pool that
        # shares this ledger; self._lock serializes access so the shared
        # connection is only ever used by one thread at a time.
        #
        # isolation_level=None puts the connection in autocommit, which matters
        # for the slot queue: parallel agents are separate *processes*, and an
        # open implicit transaction would hide their writes from each other.
        self.conn = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None
        )
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        # busy_timeout first: switching journal modes takes an exclusive lock,
        # and two agents starting at the same moment would otherwise race each
        # other straight into "database is locked" on the very first statement.
        self.conn.execute("PRAGMA busy_timeout=10000")
        if str(self.path) != ":memory:":
            self._enable_wal()
        self.conn.executescript(SCHEMA)

    def _enable_wal(self) -> None:
        """Switch the database to WAL, tolerating a concurrent opener.

        WAL lets readers and one writer proceed at once, which is what makes
        several agents usable against one ledger. Switching *into* it needs a
        brief exclusive lock, so two agents starting simultaneously can collide
        — but only one of them has to win: the mode is a property of the file,
        so the loser simply inherits WAL from the winner. Raising here would
        make `wqo` unusable whenever a second agent happened to start at the
        same instant.
        """
        try:
            mode = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
            if str(mode).lower() != "wal":
                self.conn.execute("PRAGMA journal_mode=WAL").fetchone()
        except sqlite3.OperationalError:
            pass  # another agent is mid-switch; its mode applies to us too

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- simulations -------------------------------------------------------

    def start_simulation(
        self,
        code: str,
        settings: dict,
        *,
        source: str = "manual",
        label: Optional[str] = None,
    ) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO simulations (created_at, code, settings_json, status, source, label)"
                " VALUES (?, ?, ?, 'PENDING', ?, ?)",
                (time.time(), code, json.dumps(settings, sort_keys=True), source, label),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def attach_sim_url(self, row_id: int, sim_url: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE simulations SET sim_url = ? WHERE id = ?", (sim_url, row_id)
            )
            self.conn.commit()

    def finish_simulation(self, row_id: int, alpha: dict) -> None:
        """Record a completed simulation from a full ``/alphas/{id}`` payload."""
        is_stats = alpha.get("is") or {}
        with self._lock:
            self.conn.execute(
                """UPDATE simulations SET
                       status = 'COMPLETE', alpha_id = ?, sharpe = ?, fitness = ?,
                       turnover = ?, returns = ?, drawdown = ?, margin = ?,
                       long_count = ?, short_count = ?, checks_json = ?
                   WHERE id = ?""",
                (
                    alpha.get("id"),
                    is_stats.get("sharpe"),
                    is_stats.get("fitness"),
                    is_stats.get("turnover"),
                    is_stats.get("returns"),
                    is_stats.get("drawdown"),
                    is_stats.get("margin"),
                    is_stats.get("longCount"),
                    is_stats.get("shortCount"),
                    json.dumps(is_stats.get("checks") or []),
                    row_id,
                ),
            )
            self.conn.commit()

    def fail_simulation(self, row_id: int, error: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE simulations SET status = 'ERROR', error = ? WHERE id = ?",
                (error, row_id),
            )
            self.conn.commit()

    def simulations_today(self) -> int:
        with self._lock:
            cur = self.conn.execute(
                "SELECT COUNT(*) FROM simulations WHERE created_at >= ?", (_brain_day_start(),)
            )
            return int(cur.fetchone()[0])

    def find_by_code(self, code: str, settings: dict) -> Optional[sqlite3.Row]:
        """Look up a prior completed run of the exact same code+settings.

        Used to skip re-simulating something already tested, which is both
        faster and one fewer request against the account.
        """
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM simulations WHERE code = ? AND settings_json = ?"
                " AND status = 'COMPLETE' ORDER BY created_at DESC LIMIT 1",
                (code, json.dumps(settings, sort_keys=True)),
            )
            return cur.fetchone()

    def recent_simulations(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM simulations ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            return list(cur.fetchall())

    # -- submissions -------------------------------------------------------

    def record_submission(self, alpha_id: str, outcome: str, detail: Any = None) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO submissions (created_at, alpha_id, outcome, detail_json)"
                " VALUES (?, ?, ?, ?)",
                (time.time(), alpha_id, outcome, json.dumps(detail) if detail else None),
            )
            self.conn.commit()

    def submissions_today(self) -> int:
        with self._lock:
            cur = self.conn.execute(
                "SELECT COUNT(*) FROM submissions WHERE created_at >= ? AND outcome = 'SUBMITTED'",
                (_brain_day_start(),),
            )
            return int(cur.fetchone()[0])

    # -- cross-process slot queue ------------------------------------------

    def enqueue_slot(self, owner: str, label: Optional[str] = None) -> int:
        """Join the waiting line. Returns the ticket used by every other call."""
        now = time.time()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO slot_queue (owner, label, requested_at, heartbeat_at)"
                " VALUES (?, ?, ?, ?)",
                (owner, label, now, now),
            )
            return int(cur.lastrowid)

    def try_grant_slot(
        self, ticket: int, limit: int, stale_after: float = STALE_SLOT_AFTER
    ) -> bool:
        """Claim a slot for ``ticket`` if one is free and nobody is ahead.

        Runs inside ``BEGIN IMMEDIATE`` so that two processes racing for the
        last slot cannot both win. Returns False if the caller should wait —
        including the case where its own row was reaped, which the caller
        detects with :meth:`slot_ticket_alive`.
        """
        now = time.time()
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.execute(
                    "DELETE FROM slot_queue WHERE heartbeat_at < ?",
                    (now - stale_after,),
                )
                granted = int(
                    self.conn.execute(
                        "SELECT COUNT(*) FROM slot_queue WHERE granted_at IS NOT NULL"
                    ).fetchone()[0]
                )
                # Waiters with a lower ticket go first, so a long-running mining
                # batch cannot starve a single interactive simulation forever.
                ahead = int(
                    self.conn.execute(
                        "SELECT COUNT(*) FROM slot_queue"
                        " WHERE granted_at IS NULL AND ticket < ?",
                        (ticket,),
                    ).fetchone()[0]
                )
                if granted + ahead >= limit:
                    granted_here = False
                else:
                    cur = self.conn.execute(
                        "UPDATE slot_queue SET granted_at = ?, heartbeat_at = ?"
                        " WHERE ticket = ? AND granted_at IS NULL",
                        (now, now, ticket),
                    )
                    granted_here = cur.rowcount > 0
                # Waiting is not idle: refresh our own heartbeat so a long queue
                # does not reap the very waiters standing in it.
                self.conn.execute(
                    "UPDATE slot_queue SET heartbeat_at = ? WHERE ticket = ?",
                    (now, ticket),
                )
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            self.conn.execute("COMMIT")
            return granted_here

    def heartbeat_slot(self, ticket: int) -> bool:
        """Mark ``ticket`` alive. False means it was reaped and must re-queue."""
        with self._lock:
            cur = self.conn.execute(
                "UPDATE slot_queue SET heartbeat_at = ? WHERE ticket = ?",
                (time.time(), ticket),
            )
            return cur.rowcount > 0

    def slot_ticket_alive(self, ticket: int) -> bool:
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM slot_queue WHERE ticket = ?", (ticket,)
            ).fetchone()
            return row is not None

    def release_slot(self, ticket: int) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM slot_queue WHERE ticket = ?", (ticket,))

    def slot_queue_state(self, stale_after: float = STALE_SLOT_AFTER) -> dict:
        """Who holds a slot and who is waiting — for `wqo account slots`."""
        now = time.time()
        with self._lock:
            self.conn.execute(
                "DELETE FROM slot_queue WHERE heartbeat_at < ?", (now - stale_after,)
            )
            rows = self.conn.execute(
                "SELECT * FROM slot_queue ORDER BY ticket"
            ).fetchall()
        holders, waiters = [], []
        for row in rows:
            entry = {
                "ticket": row["ticket"],
                "owner": row["owner"],
                "label": row["label"],
                "waiting_for": round(now - row["requested_at"], 1),
            }
            if row["granted_at"] is not None:
                entry["held_for"] = round(now - row["granted_at"], 1)
                holders.append(entry)
            else:
                waiters.append(entry)
        return {"holding": holders, "waiting": waiters}

    # -- key/value ---------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            cur = self.conn.execute("SELECT value_json FROM kv WHERE key = ?", (key,))
            row = cur.fetchone()
            return json.loads(row[0]) if row else default

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO kv (key, value_json, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json,"
                " updated_at = excluded.updated_at",
                (key, json.dumps(value), time.time()),
            )
            self.conn.commit()


class BudgetExceeded(RuntimeError):
    pass


def check_simulation_budget(ledger: Ledger, wanted: int = 1) -> None:
    used = ledger.simulations_today()
    cap = config.BUDGET.simulations_per_day
    if used + wanted > cap:
        raise BudgetExceeded(
            f"daily simulation budget exhausted: {used}/{cap} used today "
            f"(raise with WQO_SIM_BUDGET)"
        )


def check_submission_budget(ledger: Ledger) -> None:
    used = ledger.submissions_today()
    cap = config.BUDGET.submissions_per_day
    if used + 1 > cap:
        raise BudgetExceeded(
            f"daily submission budget exhausted: {used}/{cap} used today "
            f"(raise with WQO_SUBMIT_BUDGET)"
        )
