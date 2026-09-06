"""Minimal, private account notes; never serialize complete user records."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import account, config
from .privacy import redact


def collect(session, ledger) -> dict:
    def fields(record, names):
        # Nested API objects can contain profile details or authentication data.
        return {name: value for name in names
                if isinstance(value := record.get(name), (str, int, float, bool))
                or value is None}

    me = session.whoami()
    standing = account.standing(session)
    return redact({
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "account": fields(me, ("id", "level")),
        "competitions": [fields(row, (
            "competition", "status", "rank", "score", "alphas", "level",
            "points_to_next_level", "next_level_at",
        )) for row in standing["competitions"]],
        "concurrency": ledger.get("learned_concurrency", config.DEFAULT_CONCURRENCY),
        "simulations_today": ledger.simulations_today(),
        "simulation_budget": config.BUDGET.simulations_per_day,
        "submissions_today": ledger.submissions_today(),
        "submission_budget": config.BUDGET.submissions_per_day,
    })


def write(snapshot: dict, directory: Path, *, overwrite: bool = False) -> Path:
    """Atomically install a 0600 file, refusing existing notes unless requested."""
    path = directory / "ACCOUNT.local.md"
    if path.is_symlink():
        raise ValueError("ACCOUNT.local.md must not be a symlink")
    content = (
        "# Private WQO account snapshot\n\n"
        "Generated account observations, not universal platform limits. "
        "Keep this file out of Git and public posts. Quotas below are local ledger values.\n\n"
        "```json\n" + json.dumps(redact(snapshot), indent=2) + "\n```\n"
    )
    fd, name = tempfile.mkstemp(prefix=".wqo-account-", dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            # Atomic no-clobber creation, including when another process wins.
            os.link(temporary, path)
        return path
    finally:
        temporary.unlink(missing_ok=True)
