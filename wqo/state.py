"""Explicit migration of private local state from older source checkouts."""
from __future__ import annotations

from contextlib import closing
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

_STATE_FILES = ("wqo.sqlite", "catalog.sqlite", "pending_persona.json", "wqo.log")


def migrate_data(source: Path, destination: Path) -> None:
    """Copy state without overwriting or destroying the source.

    Run with all other wqo processes stopped. SQLite backup includes WAL data;
    an existing destination is refused to avoid merging two quota histories.
    """
    source, destination = source.resolve(), destination.resolve()
    if source == destination or destination.is_relative_to(source):
        raise ValueError("source and destination must be separate directories")
    if not (source / "wqo.sqlite").is_file():
        raise ValueError("source has no wqo.sqlite ledger")
    if destination.exists():
        raise ValueError("destination already exists; use WQO_DATA_DIR to keep using the existing ledger")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Build privately, then publish the whole directory in one rename. A CLI
    # creating a ledger at the destination concurrently makes the rename fail.
    staging = Path(tempfile.mkdtemp(dir=destination.parent, prefix=".wqo-migrate-"))
    try:
        for name in _STATE_FILES:
            src, dest = source / name, staging / name
            if not src.exists():
                continue
            if src.is_symlink():
                raise ValueError("state migration refuses symlinked files")
            if name.endswith(".sqlite"):
                fd, temporary = tempfile.mkstemp(dir=staging, prefix=".migration-")
                os.close(fd)
                try:
                    with closing(sqlite3.connect(src.as_uri() + "?mode=ro", uri=True)) as old:
                        if name == "wqo.sqlite":
                            tables = {row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                            if not {"simulations", "submissions", "kv"} <= tables:
                                raise ValueError("source ledger has an unexpected schema")
                            if "simulation_slots" in tables and old.execute("SELECT COUNT(*) FROM simulation_slots").fetchone()[0]:
                                raise ValueError("source has simulation permits; stop/reconcile those processes first")
                        with closing(sqlite3.connect(temporary)) as new:
                            old.backup(new)
                    os.replace(temporary, dest)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            else:
                with dest.open("xb") as output:
                    os.chmod(dest, 0o600)
                    with src.open("rb") as input_file:
                        shutil.copyfileobj(input_file, output)
        if destination.exists():
            raise ValueError("destination was created during migration; it has not been overwritten")
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
