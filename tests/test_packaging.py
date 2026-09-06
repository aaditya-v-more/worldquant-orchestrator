"""Package configuration and state migration, using synthetic temporary ledgers."""
import json
import sqlite3
from pathlib import Path

import pytest

from wqo import __version__, config
from wqo import __main__ as cli
from wqo.state import migrate_data
from wqo.store import Ledger, SubmissionConflict


def test_default_state_is_independent_of_checkout(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert config.default_data_dir() == tmp_path / ".local/share/wqo"
    monkeypatch.setenv("XDG_DATA_HOME", "relative/not/valid")
    assert config.default_data_dir() == tmp_path / ".local/share/wqo"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "custom"))
    assert config.default_data_dir() == tmp_path / "custom/wqo"


def test_version_and_state_need_no_auth_or_files(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "BrainSession", lambda **kwargs: pytest.fail("must not authenticate"))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "not-created")
    monkeypatch.setattr(config, "LEDGER_PATH", config.DATA_DIR / "wqo.sqlite")
    with pytest.raises(SystemExit) as exit:
        cli.main(["--version"])
    assert exit.value.code == 0
    assert capsys.readouterr().out.strip() == f"wqo {__version__}"
    assert cli.main(["state"]) == 0
    assert json.loads(capsys.readouterr().out)["data_dir"] == str(config.DATA_DIR)
    assert not config.DATA_DIR.exists()


def test_migration_preserves_wal_quota_and_unresolved_history(tmp_path):
    source, destination = tmp_path / "legacy", tmp_path / "new"
    with Ledger(source / "wqo.sqlite") as old:
        old.conn.execute("PRAGMA journal_mode=WAL")
        old.record_submission("SYNTHETIC_DONE", "SUBMITTED")
        old.reserve_submission("SYNTHETIC_PENDING")
        old.set("learned_concurrency", 1)
        (source / "pending_persona.json").write_text('{"inquiry":"synthetic"}')
        migrate_data(source, destination)
        with Ledger(destination / "wqo.sqlite") as new:
            assert new.submissions_today() == old.submissions_today() == 2
            assert new.get("learned_concurrency") == 1
            with pytest.raises(SubmissionConflict):
                new.reserve_submission("SYNTHETIC_PENDING")
        assert (destination / "pending_persona.json").read_text() == '{"inquiry":"synthetic"}'
        assert (destination / "wqo.sqlite").stat().st_mode & 0o777 == 0o600
        assert destination.stat().st_mode & 0o777 == 0o700
        assert (source / "wqo.sqlite").exists()


def test_migration_does_not_overwrite_existing_state(tmp_path):
    source, destination = tmp_path / "legacy", tmp_path / "new"
    with Ledger(source / "wqo.sqlite"):
        pass
    with Ledger(destination / "wqo.sqlite") as current:
        current.reserve_submission("SYNTHETIC_PENDING")
        with pytest.raises(ValueError, match="already exists"):
            migrate_data(source, destination)
        assert current.submissions_today() == 1


def test_migration_refuses_active_slots(tmp_path):
    source, destination = tmp_path / "legacy", tmp_path / "new"
    with Ledger(source / "wqo.sqlite") as ledger:
        assert ledger.try_acquire_slot("synthetic-owner", 1)
        with pytest.raises(ValueError, match="simulation permits"):
            migrate_data(source, destination)
    assert not destination.exists()


def test_failed_migration_never_exposes_partial_ledger(tmp_path):
    source, destination = tmp_path / "legacy", tmp_path / "new"
    with Ledger(source / "wqo.sqlite"):
        pass
    (source / "catalog.sqlite").write_bytes(b"invalid database")
    with pytest.raises(sqlite3.DatabaseError):
        migrate_data(source, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".wqo-migrate-*"))


def test_migration_copies_only_state_files_and_refuses_symlinks(tmp_path):
    source, destination = tmp_path / "legacy", tmp_path / "new"
    with Ledger(source / "wqo.sqlite"):
        pass
    (source / "private.txt").write_text("synthetic")
    (source / "pending_persona.json").symlink_to(source / "private.txt")
    with pytest.raises(ValueError, match="symlink"):
        migrate_data(source, destination)
    assert not destination.exists()
