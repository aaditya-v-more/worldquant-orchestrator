"""SQLite ledger of everything this tool does.

Two jobs:

* an audit trail — every simulation, check, and submission is recorded with
  its full settings and result, so results are reproducible after the fact;
* budget enforcement — daily caps are counted straight off these tables.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
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
    outcome     TEXT NOT NULL,               -- SUBMITTED | FAILED
    detail_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_sub_created ON submissions (created_at);

CREATE TABLE IF NOT EXISTS kv (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


def _utc_day_start(ts: Optional[float] = None) -> float:
    """Epoch seconds at the most recent UTC midnight.

    BRAIN's daily quotas roll over on its own clock, not the local one; UTC is
    the closest stable proxy and keeps budget accounting deterministic.
    """
    now = datetime.fromtimestamp(ts if ts is not None else time.time(), tz=timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()


class Ledger:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else config.LEDGER_PATH
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
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
        cur = self.conn.execute(
            "INSERT INTO simulations (created_at, code, settings_json, status, source, label)"
            " VALUES (?, ?, ?, 'PENDING', ?, ?)",
            (time.time(), code, json.dumps(settings, sort_keys=True), source, label),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def attach_sim_url(self, row_id: int, sim_url: str) -> None:
        self.conn.execute(
            "UPDATE simulations SET sim_url = ? WHERE id = ?", (sim_url, row_id)
        )
        self.conn.commit()

    def finish_simulation(self, row_id: int, alpha: dict) -> None:
        """Record a completed simulation from a full ``/alphas/{id}`` payload."""
        is_stats = alpha.get("is") or {}
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
        self.conn.execute(
            "UPDATE simulations SET status = 'ERROR', error = ? WHERE id = ?",
            (error, row_id),
        )
        self.conn.commit()

    def simulations_today(self) -> int:
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM simulations WHERE created_at >= ?", (_utc_day_start(),)
        )
        return int(cur.fetchone()[0])

    def find_by_code(self, code: str, settings: dict) -> Optional[sqlite3.Row]:
        """Look up a prior completed run of the exact same code+settings.

        Used to skip re-simulating something already tested, which is both
        faster and one fewer request against the account.
        """
        cur = self.conn.execute(
            "SELECT * FROM simulations WHERE code = ? AND settings_json = ?"
            " AND status = 'COMPLETE' ORDER BY created_at DESC LIMIT 1",
            (code, json.dumps(settings, sort_keys=True)),
        )
        return cur.fetchone()

    def recent_simulations(self, limit: int = 20) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM simulations ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return list(cur.fetchall())

    # -- submissions -------------------------------------------------------

    def record_submission(self, alpha_id: str, outcome: str, detail: Any = None) -> None:
        self.conn.execute(
            "INSERT INTO submissions (created_at, alpha_id, outcome, detail_json)"
            " VALUES (?, ?, ?, ?)",
            (time.time(), alpha_id, outcome, json.dumps(detail) if detail else None),
        )
        self.conn.commit()

    def submissions_today(self) -> int:
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM submissions WHERE created_at >= ? AND outcome = 'SUBMITTED'",
            (_utc_day_start(),),
        )
        return int(cur.fetchone()[0])

    # -- key/value ---------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        cur = self.conn.execute("SELECT value_json FROM kv WHERE key = ?", (key,))
        row = cur.fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value: Any) -> None:
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
