"""SQLite ledger of everything this tool does.

Two jobs:

* an audit trail — every simulation, check, and submission is recorded with
  its full settings and result, so results are reproducible after the fact;
* budget enforcement — daily caps are counted straight off these tables.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Iterable, Optional

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
    outcome     TEXT NOT NULL,               -- PENDING | UNKNOWN | SUBMITTED | FAILED
    detail_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_sub_created ON submissions (created_at);

CREATE TABLE IF NOT EXISTS simulation_slots (
    owner TEXT PRIMARY KEY,
    pid INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


def _day_start(ts: Optional[float] = None) -> float:
    """US Eastern midnight, including daylight-saving transitions."""
    now = datetime.fromtimestamp(ts if ts is not None else time.time(),
                                 tz=ZoneInfo("America/New_York"))
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _submission_window_start() -> float:
    # Until the platform's reset convention is verified, also enforce a rolling
    # 24-hour cap. This cannot grant fresh quota early at UTC/Eastern midnight.
    now = time.time()
    return min(_day_start(now), now - 24 * 3600)


class SubmissionConflict(RuntimeError):
    pass


class Ledger:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else config.LEDGER_PATH
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False because simulate_many runs a worker pool that
        # shares this ledger; self._lock serializes access so the shared
        # connection is only ever used by one thread at a time.
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.conn.executescript(SCHEMA)
        self.conn.commit()

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
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                check_simulation_budget(self)
                cur = self.conn.execute(
                    "INSERT INTO simulations (created_at, code, settings_json, status, source, label)"
                    " VALUES (?, ?, ?, 'PENDING', ?, ?)",
                    (time.time(), code, json.dumps(settings, sort_keys=True), source, label),
                )
                self.conn.commit()
                return int(cur.lastrowid)
            except BaseException:
                self.conn.rollback()
                raise

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
                "SELECT COUNT(*) FROM simulations WHERE created_at >= ?", (_day_start(),)
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
        """Conservatively count recent successes and all unresolved writes."""
        with self._lock:
            return int(self.conn.execute(
                "SELECT COUNT(*) FROM submissions WHERE outcome IN ('PENDING', 'UNKNOWN')"
                " OR (created_at >= ? AND outcome = 'SUBMITTED')",
                (_submission_window_start(),),
            ).fetchone()[0])

    def reserve_submission(self, alpha_id: str) -> int:
        """Check and reserve under one SQLite write lock across all processes."""
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                prior = self.conn.execute(
                    "SELECT 1 FROM submissions WHERE alpha_id = ? AND outcome IN"
                    " ('PENDING', 'UNKNOWN', 'SUBMITTED') LIMIT 1", (alpha_id,)
                ).fetchone()
                if prior:
                    raise SubmissionConflict(
                        "alpha already submitted or has an unresolved submission; "
                        "verify its status on BRAIN before any further action"
                    )
                check_submission_budget(self)
                row = self.conn.execute(
                    "INSERT INTO submissions (created_at, alpha_id, outcome) VALUES (?, ?, 'PENDING')",
                    (time.time(), alpha_id),
                )
                self.conn.commit()
                return int(row.lastrowid)
            except BaseException:
                self.conn.rollback()
                raise

    def finish_submission(self, row_id: int, outcome: str, detail: Any = None) -> None:
        if outcome not in {"FAILED", "UNKNOWN", "SUBMITTED"}:
            raise ValueError("invalid submission outcome")
        with self._lock:
            self.conn.execute(
                "UPDATE submissions SET outcome = ?, detail_json = ? WHERE id = ?",
                (outcome, json.dumps(detail), row_id),
            )
            self.conn.commit()

    def try_acquire_slot(self, owner: str, limit: int) -> bool:
        if os.name != "posix":
            raise RuntimeError("shared simulation slots currently require macOS or Linux")
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                for row in self.conn.execute("SELECT owner, pid FROM simulation_slots").fetchall():
                    try:
                        os.kill(row["pid"], 0)
                    except ProcessLookupError:
                        self.conn.execute("DELETE FROM simulation_slots WHERE owner = ?", (row["owner"],))
                    except PermissionError:
                        pass  # Treat an uninspectable process as still active.
                learned = self.get("learned_concurrency", limit)
                cap = max(1, min(limit, int(learned), config.MAX_CONCURRENCY))
                count = self.conn.execute("SELECT COUNT(*) FROM simulation_slots").fetchone()[0]
                acquired = count < cap
                if acquired:
                    self.conn.execute("INSERT INTO simulation_slots VALUES (?, ?)", (owner, os.getpid()))
                self.conn.commit()
                return acquired
            except BaseException:
                self.conn.rollback()
                raise

    def release_slot(self, owner: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM simulation_slots WHERE owner = ?", (owner,))
            self.conn.commit()

    def update_concurrency(self, previous: int, proposed: int) -> int:
        # A stale worker must never overwrite another process's throttle.
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                current = int(self.get("learned_concurrency", previous))
                value = min(current, proposed) if proposed < previous else (
                    proposed if current == previous else current
                )
                self.set("learned_concurrency", value)
                return value
            except BaseException:
                self.conn.rollback()
                raise

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
            "(stop until quota is available)"
        )


def check_submission_budget(ledger: Ledger) -> None:
    used = ledger.submissions_today()
    cap = config.BUDGET.submissions_per_day
    if used + 1 > cap:
        raise BudgetExceeded(
            f"daily submission budget exhausted: {used}/{cap} used today "
            "(includes unresolved submissions and the rolling 24-hour safety window)"
        )
