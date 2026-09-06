"""Offline regressions: never instantiate a session with real credentials/cookies."""
import json
import multiprocessing as mp
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from wqo import config
from wqo import __main__ as cli
from wqo.session import ApiError, BrainSession, _write_private
from wqo.store import BudgetExceeded, Ledger, SubmissionConflict, _day_start
from wqo.submit import Preparation, SubmissionRefused, submit
from wqo.simulate import SlotManager


def prep(alpha_id="DEMO_ALPHA"):
    return Preparation({"id": alpha_id}, SimpleNamespace(passed=True), None, None)


def response(status=201, payload=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = b"" if payload is None else json.dumps(payload).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def session(tmp_path, monkeypatch):
    result = BrainSession(session_path=tmp_path / "empty.json", credentials_path=tmp_path / "never-read.json")
    result.governor.wait_turn = Mock()
    result.governor.sleep_backoff = Mock()
    result.governor.sleep_retry_after = Mock()
    result.authenticate = Mock(side_effect=AssertionError("no real authentication"))
    yield result
    result.close()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post"])
@pytest.mark.parametrize("path", ["/alphas/DEMO/submit", "https://api.worldquantbrain.com/alphas/DEMO/%73ubmit?x=1", "/simulations"])
def test_raw_mutations_refused_before_auth(monkeypatch, method, path):
    monkeypatch.setattr(cli, "_session", Mock(side_effect=AssertionError("must not authenticate")))
    assert cli.main(["api", method, path]) == 4


def test_raw_read_redacts_headers_nested_body_and_strings(monkeypatch, capsys):
    fake = Mock()
    fake.request.return_value = response(200, {"nested": [{"access_token": "hidden-body", "sessionid": "hidden-session"}], "message": "password=hidden-text"}, {"Set-Cookie": "hidden-cookie", "X-Api-Key": "hidden-key", "Content-Type": "application/json"})
    monkeypatch.setattr(cli, "_session", lambda args: fake)
    assert cli.main(["api", "GET", "/authentication"]) == 0
    output = capsys.readouterr().out
    assert "hidden" not in output
    assert "application/json" in output


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_write_timeout_is_not_retried_or_echoed(session, monkeypatch, method):
    send = Mock(side_effect=requests.Timeout("SECRET_WITHOUT_FIELD_NAME"))
    monkeypatch.setattr(requests.Session, "request", send)
    with pytest.raises(ApiError) as err:
        session.request(method, "/alphas/DEMO/submit?token=QUERY_SECRET")
    assert send.call_count == 1
    assert "SECRET" not in str(err.value)
    session.authenticate.assert_not_called()


@pytest.mark.parametrize("status", [401, 429, 500, 503])
def test_write_http_failures_are_not_replayed(session, monkeypatch, status):
    send = Mock(return_value=response(status))
    monkeypatch.setattr(requests.Session, "request", send)
    assert session.request("POST", "/alphas/DEMO/submit").status_code == status
    assert send.call_count == 1
    session.authenticate.assert_not_called()


def test_read_can_retry_and_redirects_are_disabled(session, monkeypatch):
    send = Mock(side_effect=[requests.Timeout(), response(200)])
    monkeypatch.setattr(requests.Session, "request", send)
    assert session.request("GET", "/authentication", allow_reauth=False).status_code == 200
    assert send.call_count == 2
    assert send.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("url", ["https://example.com/", "http://api.worldquantbrain.com/", "https://api.worldquantbrain.com@evil.test/"])
def test_foreign_origin_refused(session, monkeypatch, url):
    send = Mock(side_effect=AssertionError("must not send"))
    monkeypatch.setattr(requests.Session, "request", send)
    with pytest.raises(ApiError, match="origin"):
        session.request("GET", url)


def test_redirect_is_not_followed(session, monkeypatch):
    send = Mock(return_value=response(307, headers={"Location": "/alphas/DEMO/submit"}))
    monkeypatch.setattr(requests.Session, "request", send)
    with pytest.raises(ApiError, match="redirect"):
        session.request("POST", "/anything")
    assert send.call_count == 1


def test_error_bodies_omitted(session, monkeypatch):
    monkeypatch.setattr(requests.Session, "request", Mock(return_value=response(403, {"detail": "SECRET_WITHOUT_FIELD"})))
    with pytest.raises(ApiError) as err:
        session.json("GET", "/users/self?token=QUERY_SECRET")
    assert "SECRET" not in str(err.value)


def test_private_file_created_with_private_permissions(tmp_path):
    path = tmp_path / "cookie.json"
    _write_private(path, {"cookies": {"session": "synthetic"}})
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())["cookies"]["session"] == "synthetic"


def _reserve_worker(path, start, output, alpha_id):
    with Ledger(path) as ledger:
        start.wait(10)
        try:
            ledger.reserve_submission(alpha_id)
            output.put("reserved")
        except (BudgetExceeded, SubmissionConflict):
            output.put("blocked")


@pytest.mark.parametrize("same_alpha", [False, True])
def test_three_processes_cannot_claim_same_slot_or_alpha(tmp_path, same_alpha):
    path = tmp_path / "ledger.sqlite"
    with Ledger(path) as ledger:
        for i in range(config.BUDGET.submissions_per_day - 1):
            ledger.record_submission(f"PRIOR_{i}", "SUBMITTED")
    ctx = mp.get_context("spawn")
    start, output = ctx.Event(), ctx.Queue()
    workers = [ctx.Process(target=_reserve_worker, args=(path, start, output, "DEMO" if same_alpha else f"DEMO_{i}")) for i in range(3)]
    for worker in workers:
        worker.start()
    start.set()
    outcomes = [output.get(timeout=15) for _ in workers]
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0
    assert outcomes.count("reserved") == 1
    with Ledger(path) as ledger:
        assert ledger.submissions_today() == config.BUDGET.submissions_per_day


@pytest.mark.parametrize("failure", ["timeout", "server", "poll", "interrupt", "malformed", "pending"])
def test_uncertain_submission_survives_restart_and_blocks_retry(tmp_path, failure):
    fake = Mock()
    if failure == "timeout":
        fake.request.side_effect = ApiError("timeout")
    elif failure == "interrupt":
        fake.request.side_effect = KeyboardInterrupt()
    elif failure == "server":
        fake.request.return_value = response(503)
    elif failure == "poll":
        fake.request.side_effect = [response(201, headers={"Retry-After": "0"}), response(403)]
    elif failure == "pending":
        fake.request.return_value = response(202, {"status": "PENDING"})
    else:
        malformed = response(200)
        malformed._content = b"not-json"
        fake.request.return_value = malformed
    path = tmp_path / "ledger.sqlite"
    with Ledger(path) as ledger:
        with pytest.raises((ApiError, KeyboardInterrupt)):
            submit(fake, "DEMO_ALPHA", confirmed=True, preparation=prep(), ledger=ledger)
        assert ledger.conn.execute("SELECT outcome FROM submissions").fetchone()[0] == "UNKNOWN"
    calls = fake.request.call_count
    with Ledger(path) as ledger:
        with pytest.raises(SubmissionRefused, match="unresolved"):
            submit(fake, "DEMO_ALPHA", confirmed=True, preparation=prep(), ledger=ledger)
        assert ledger.submissions_today() == 1
    assert fake.request.call_count == calls


def test_definite_rejection_releases_reservation(tmp_path):
    fake = Mock()
    fake.request.return_value = response(400)
    with Ledger(tmp_path / "ledger.sqlite") as ledger:
        with pytest.raises(ApiError, match="rejected"):
            submit(fake, "DEMO_ALPHA", confirmed=True, preparation=prep(), ledger=ledger)
        assert ledger.submissions_today() == 0


def test_success_counts_once_and_cannot_be_resubmitted(tmp_path):
    fake = Mock()
    fake.request.side_effect = [response(201, headers={"Retry-After": "0"}), response(200)]
    with Ledger(tmp_path / "ledger.sqlite") as ledger:
        assert submit(fake, "DEMO_ALPHA", confirmed=True, preparation=prep(), ledger=ledger)["outcome"] == "SUBMITTED"
        assert ledger.submissions_today() == 1
        with pytest.raises(SubmissionRefused):
            submit(fake, "DEMO_ALPHA", confirmed=True, preparation=prep(), ledger=ledger)
    assert [call.args[0] for call in fake.request.call_args_list] == ["POST", "GET"]


def test_submission_requires_persistent_ledger_and_matching_preparation(tmp_path):
    fake = Mock(side_effect=AssertionError("must not send"))
    with pytest.raises(SubmissionRefused, match="persistent"):
        submit(fake, "DEMO_ALPHA", confirmed=True, preparation=prep())
    with Ledger(tmp_path / "ledger.sqlite") as ledger:
        with pytest.raises(SubmissionRefused, match="different alpha"):
            submit(fake, "OTHER_ALPHA", confirmed=True, preparation=prep(), ledger=ledger)


@pytest.mark.parametrize("instant, midnight", [
    ("2026-01-10T12:00:00+00:00", "2026-01-10T05:00:00+00:00"),
    ("2026-07-10T12:00:00+00:00", "2026-07-10T04:00:00+00:00"),
    ("2026-03-08T12:00:00+00:00", "2026-03-08T05:00:00+00:00"),
    ("2026-11-01T12:00:00+00:00", "2026-11-01T04:00:00+00:00"),
])
def test_eastern_midnight_handles_dst(instant, midnight):
    assert _day_start(datetime.fromisoformat(instant).timestamp()) == datetime.fromisoformat(midnight).timestamp()


def test_midnight_does_not_release_recent_or_unknown_submissions(tmp_path, monkeypatch):
    clock = datetime(2026, 7, 10, 3, 59, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr("wqo.store.time.time", lambda: clock)
    with Ledger(tmp_path / "ledger.sqlite") as ledger:
        ledger.record_submission("DONE", "SUBMITTED")
        ledger.reserve_submission("UNRESOLVED")
        clock += 120  # Eastern midnight passes.
        assert ledger.submissions_today() == 2
        clock += 25 * 3600
        assert ledger.submissions_today() == 1
        with pytest.raises(SubmissionConflict):
            ledger.reserve_submission("DONE")


def _slot_worker(path, start, output):
    with Ledger(path) as ledger:
        slots = SlotManager(ledger, initial=1)
        start.wait(10)
        slots.acquire()
        output.put(("start", time.monotonic()))
        time.sleep(0.1)
        output.put(("end", time.monotonic()))
        slots.release()


def test_three_processes_share_one_simulation_slot(tmp_path):
    path = tmp_path / "ledger.sqlite"
    with Ledger(path):
        pass
    ctx = mp.get_context("spawn")
    start, output = ctx.Event(), ctx.Queue()
    workers = [ctx.Process(target=_slot_worker, args=(path, start, output)) for _ in range(3)]
    for worker in workers:
        worker.start()
    start.set()
    events = [output.get(timeout=15) for _ in range(6)]
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0
    assert [event for event, _ in sorted(events, key=lambda event: event[1])] == ["start", "end"] * 3


def test_stale_worker_does_not_override_throttle(tmp_path):
    with Ledger(tmp_path / "ledger.sqlite") as ledger:
        ledger.set("learned_concurrency", 3)
        stale = SlotManager(ledger)
        other = SlotManager(ledger)
        other.report_throttled()
        for _ in range(3):
            stale.report_success()
        assert ledger.get("learned_concurrency") == 2


def _simulation_budget_worker(path, start, output):
    with Ledger(path) as ledger:
        start.wait(10)
        try:
            ledger.start_simulation("rank(close)", {})
            output.put("reserved")
        except BudgetExceeded:
            output.put("blocked")


def test_simulation_budget_atomic_across_three_processes(tmp_path):
    path = tmp_path / "ledger.sqlite"
    with Ledger(path) as ledger:
        for _ in range(config.BUDGET.simulations_per_day - 1):
            ledger.start_simulation("rank(close)", {})
    ctx = mp.get_context("spawn")
    start, output = ctx.Event(), ctx.Queue()
    workers = [ctx.Process(target=_simulation_budget_worker, args=(path, start, output)) for _ in range(3)]
    for worker in workers:
        worker.start()
    start.set()
    outcomes = [output.get(timeout=15) for _ in workers]
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0
    assert outcomes.count("reserved") == 1


def test_batch_budget_race_reaches_caller_and_releases_slot(tmp_path, monkeypatch):
    from wqo.simulate import SimJob, simulate_many
    with Ledger(tmp_path / "ledger.sqlite") as ledger:
        monkeypatch.setattr(ledger, "start_simulation", Mock(side_effect=BudgetExceeded("race")))
        with pytest.raises(BudgetExceeded, match="race"):
            simulate_many(Mock(), [SimJob("rank(close)", {})], ledger=ledger)
        assert ledger.conn.execute("SELECT COUNT(*) FROM simulation_slots").fetchone()[0] == 0


def _abandoned_slot(path, output):
    with Ledger(path) as ledger:
        SlotManager(ledger).acquire()
        output.put("acquired")
        # Deliberately exit without releasing the local permit.


def test_exited_process_slot_is_reclaimed(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ctx = mp.get_context("spawn")
    output = ctx.Queue()
    worker = ctx.Process(target=_abandoned_slot, args=(path, output))
    worker.start()
    assert output.get(timeout=15) == "acquired"
    worker.join(10)
    assert worker.exitcode == 0
    with Ledger(path) as ledger:
        assert ledger.try_acquire_slot("new-process", 1)
        ledger.release_slot("new-process")


def test_accepted_but_unresolved_response_is_not_reported_as_success(tmp_path):
    fake = Mock()
    fake.request.return_value = response(202)
    with Ledger(tmp_path / "ledger.sqlite") as ledger:
        with pytest.raises(ApiError, match="not resolved"):
            submit(fake, "DEMO_ALPHA", confirmed=True, preparation=prep(), ledger=ledger)
        assert ledger.conn.execute("SELECT outcome FROM submissions").fetchone()[0] == "UNKNOWN"


def test_account_snapshot_is_private_minimal_and_does_not_print_profile(tmp_path, monkeypatch, capsys):
    from wqo import snapshot

    monkeypatch.chdir(tmp_path)
    fake = Mock()
    fake.whoami.return_value = {"id": "SYNTHETIC_ACCOUNT", "level": "NONE", "email": "private@example.invalid", "password": "DO_NOT_COPY"}
    fake.json.return_value = {"results": [{
        "id": "DEMO_COMPETITION", "status": "ACTIVE",
        "leaderboard": {"rank": 12, "score": 34, "university": "PRIVATE_UNIVERSITY"},
        "progress": {"level": "BRONZE", "score": {"remaining": 56}},
    }]}
    monkeypatch.setattr(cli, "_session", lambda args: fake)
    monkeypatch.setattr(cli, "_ledger", lambda: Ledger(tmp_path / "ledger.sqlite"))
    assert cli.main(["account", "snapshot"]) == 0
    path = tmp_path / "ACCOUNT.local.md"
    output = json.loads(capsys.readouterr().out)
    assert output == {"path": str(path), "written": True}
    content = path.read_text()
    assert "SYNTHETIC_ACCOUNT" in content
    assert '"rank": 12' in content and '"concurrency": 1' in content
    assert "private@example" not in content and "DO_NOT_COPY" not in content
    assert "PRIVATE_UNIVERSITY" not in content
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".wqo-account-*"))
    assert all(call.args[0] == "GET" for call in fake.json.call_args_list)


def test_account_snapshot_preserves_notes_and_refuses_symlink(tmp_path, monkeypatch, capsys):
    from wqo import snapshot

    monkeypatch.chdir(tmp_path)
    target = tmp_path / "ACCOUNT.local.md"
    target.write_text("manually maintained notes")
    monkeypatch.setattr(cli, "_session", Mock(side_effect=AssertionError("must not authenticate")))
    assert cli.main(["account", "snapshot"]) == 1
    assert target.read_text() == "manually maintained notes"
    with pytest.raises(FileExistsError):
        snapshot.write({}, tmp_path)
    assert target.read_text() == "manually maintained notes"
    target.unlink()
    other = tmp_path / "do-not-change"
    other.write_text("keep")
    target.symlink_to(other)
    assert cli.main(["account", "snapshot", "--overwrite"]) == 1
    assert other.read_text() == "keep"
    assert not list(tmp_path.glob(".wqo-account-*"))


def test_account_snapshot_refresh_is_atomic_and_private(tmp_path, monkeypatch):
    from wqo import snapshot

    path = snapshot.write({"account": {"id": "OLD"}}, tmp_path)
    path.chmod(0o644)
    original = snapshot.os.replace
    monkeypatch.setattr(snapshot.os, "replace", Mock(side_effect=OSError("synthetic failure")))
    with pytest.raises(OSError):
        snapshot.write({"account": {"id": "NEW"}}, tmp_path, overwrite=True)
    assert '"OLD"' in path.read_text()
    assert not list(tmp_path.glob(".wqo-account-*"))
    monkeypatch.setattr(snapshot.os, "replace", original)
    snapshot.write({"account": {"id": "NEW"}}, tmp_path, overwrite=True)
    assert '"NEW"' in path.read_text() and '"OLD"' not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600


def test_account_snapshot_api_failure_preserves_existing_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "ACCOUNT.local.md"
    path.write_text("keep previous snapshot")
    fake = Mock()
    fake.whoami.side_effect = ApiError("synthetic unavailable")
    monkeypatch.setattr(cli, "_session", lambda args: fake)
    monkeypatch.setattr(cli, "_ledger", lambda: Ledger(tmp_path / "ledger.sqlite"))
    assert cli.main(["account", "snapshot", "--overwrite"]) == 1
    assert path.read_text() == "keep previous snapshot"
    assert not capsys.readouterr().out
