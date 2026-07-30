"""Offline tests — no network, no credentials.

Run with:  .venv/bin/python -m pytest tests -q
"""

from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wqo import alphas as alphas_mod  # noqa: E402
from wqo import config, gate  # noqa: E402
from wqo.config import GateThresholds, Pacing  # noqa: E402
from wqo.mining import generator, rank, templates  # noqa: E402
from wqo.pacing import RateGovernor, is_retryable  # noqa: E402
from wqo.simulate import SimResult, SlotManager, build_settings  # noqa: E402
from wqo.store import BudgetExceeded, Ledger, check_submission_budget  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=200, headers=None, body=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    def json(self):
        return self._body


# --------------------------------------------------------------------------
# pacing
# --------------------------------------------------------------------------


def make_governor():
    slept = []
    clock = {"t": 0.0}

    def sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    governor = RateGovernor(
        Pacing(min_interval=1.0, jitter=0.0, backoff_base=2.0, backoff_max=10.0),
        sleep=sleep,
        clock=lambda: clock["t"],
    )
    return governor, slept, clock


def test_wait_turn_enforces_min_interval():
    governor, slept, _ = make_governor()
    assert governor.wait_turn() == 0.0  # first call is free
    assert governor.wait_turn() == pytest.approx(1.0)
    assert slept == [1.0]


def test_backoff_is_bounded_and_grows():
    governor, _, _ = make_governor()
    # Full jitter means each draw sits inside [0, window]; window doubles per
    # attempt and is clamped at backoff_max.
    for attempt, window in ((1, 1.0), (2, 2.0), (3, 4.0), (10, 10.0)):
        for _ in range(50):
            assert 0.0 <= governor.backoff_delay(attempt) <= window


def test_retry_after_is_honored_verbatim():
    governor, _, _ = make_governor()
    assert governor.retry_after_seconds(FakeResponse(headers={"Retry-After": "7.5"})) == 7.5
    assert governor.retry_after_seconds(FakeResponse(headers={"Retry-After": "0"})) == 0.0
    # Missing or malformed header falls back to the configured default.
    assert governor.retry_after_seconds(FakeResponse(), default=3.0) == 3.0
    assert governor.retry_after_seconds(
        FakeResponse(headers={"Retry-After": "soon"}), default=3.0
    ) == 3.0


def test_retryable_statuses():
    assert is_retryable(FakeResponse(429))
    assert is_retryable(FakeResponse(503))
    assert not is_retryable(FakeResponse(200))
    assert not is_retryable(FakeResponse(400))


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------


@pytest.fixture
def ledger(tmp_path):
    with Ledger(tmp_path / "test.sqlite") as led:
        yield led


def test_ledger_records_simulation_lifecycle(ledger):
    settings = build_settings(region="USA")
    row_id = ledger.start_simulation("rank(close)", settings)
    ledger.attach_sim_url(row_id, "https://api.worldquantbrain.com/simulations/abc")
    ledger.finish_simulation(
        row_id,
        {"id": "AL1", "is": {"sharpe": 1.4, "fitness": 1.1, "turnover": 0.2, "checks": []}},
    )
    row = ledger.recent_simulations(1)[0]
    assert row["status"] == "COMPLETE"
    assert row["alpha_id"] == "AL1"
    assert row["sharpe"] == 1.4
    assert ledger.simulations_today() == 1


def test_ledger_finds_prior_identical_run(ledger):
    settings = build_settings(region="USA")
    row_id = ledger.start_simulation("rank(close)", settings)
    ledger.finish_simulation(row_id, {"id": "AL1", "is": {"sharpe": 1.0}})

    assert ledger.find_by_code("rank(close)", settings)["alpha_id"] == "AL1"
    # Different settings must not collide with the cached result.
    assert ledger.find_by_code("rank(close)", build_settings(region="EUR")) is None
    assert ledger.find_by_code("rank(open)", settings) is None


def test_submission_budget_blocks_at_cap(ledger, monkeypatch):
    from wqo import config as cfg

    monkeypatch.setattr(cfg.BUDGET, "submissions_per_day", 1)
    check_submission_budget(ledger)  # nothing used yet
    ledger.record_submission("AL1", "SUBMITTED")
    with pytest.raises(BudgetExceeded):
        check_submission_budget(ledger)


def test_failed_submissions_do_not_consume_budget(ledger):
    ledger.record_submission("AL1", "FAILED", {"detail": "nope"})
    assert ledger.submissions_today() == 0


def test_daily_budget_rolls_on_eastern_midnight_not_utc():
    # Shipped once counting on UTC midnight, which reports a fresh budget four
    # or five hours before BRAIN's own day actually turns over.
    from datetime import datetime, timezone

    from wqo.store import _brain_day_start

    def day_start_utc(iso: str) -> datetime:
        ts = datetime.fromisoformat(iso).timestamp()
        return datetime.fromtimestamp(_brain_day_start(ts), tz=timezone.utc)

    # Summer (EDT, UTC-4): 03:00 UTC is still the previous Eastern day.
    assert day_start_utc("2026-07-30T03:00:00+00:00") == datetime(
        2026, 7, 29, 4, 0, tzinfo=timezone.utc
    )
    assert day_start_utc("2026-07-30T05:00:00+00:00") == datetime(
        2026, 7, 30, 4, 0, tzinfo=timezone.utc
    )
    # Winter (EST, UTC-5): the boundary shifts an hour later in UTC.
    assert day_start_utc("2026-01-15T18:00:00+00:00") == datetime(
        2026, 1, 15, 5, 0, tzinfo=timezone.utc
    )


def test_slot_queue_is_shared_between_processes(tmp_path):
    # Two Ledger objects on one file stand in for two agents running `wqo` at
    # once. Before the shared queue each had its own in-memory SlotManager,
    # both believed they held the account's only slot, and the second POST 429'd.
    path = tmp_path / "shared.sqlite"
    with Ledger(path) as agent_a, Ledger(path) as agent_b:
        first = agent_a.enqueue_slot("agent-a")
        second = agent_b.enqueue_slot("agent-b")

        assert agent_a.try_grant_slot(first, limit=1) is True
        assert agent_b.try_grant_slot(second, limit=1) is False, "one slot, one holder"

        state = agent_b.slot_queue_state()
        assert [h["owner"] for h in state["holding"]] == ["agent-a"]
        assert [w["owner"] for w in state["waiting"]] == ["agent-b"]

        agent_a.release_slot(first)
        assert agent_b.try_grant_slot(second, limit=1) is True


def test_slot_queue_grants_in_ticket_order(tmp_path):
    # Without the "nobody ahead of me" rule a mining batch polling in a tight
    # loop would keep winning the slot and starve a waiting interactive run.
    path = tmp_path / "fifo.sqlite"
    with Ledger(path) as led:
        early = led.enqueue_slot("early")
        late = led.enqueue_slot("late")

        assert led.try_grant_slot(late, limit=1) is False, "must not jump the queue"
        assert led.try_grant_slot(early, limit=1) is True


def test_slot_queue_reaps_dead_holders(tmp_path):
    # A killed agent must not hold the account's only slot forever.
    path = tmp_path / "reap.sqlite"
    with Ledger(path) as led:
        dead = led.enqueue_slot("crashed")
        assert led.try_grant_slot(dead, limit=1) is True

        alive = led.enqueue_slot("healthy")
        assert led.try_grant_slot(alive, limit=1) is False

        # The crashed agent stops heartbeating; age its row past the reaper.
        led.conn.execute(
            "UPDATE slot_queue SET heartbeat_at = ? WHERE ticket = ?",
            (time.time() - 10_000, dead),
        )
        assert led.try_grant_slot(alive, limit=1) is True
        assert led.slot_ticket_alive(dead) is False


def test_slot_queue_lets_two_run_when_limit_allows(tmp_path):
    path = tmp_path / "two.sqlite"
    with Ledger(path) as led:
        a, b, c = (led.enqueue_slot(f"agent-{i}") for i in range(3))
        assert led.try_grant_slot(a, limit=2) is True
        assert led.try_grant_slot(b, limit=2) is True
        assert led.try_grant_slot(c, limit=2) is False


def _slot_agent(db_path, name, out):  # runs in a separate process
    from wqo.store import Ledger as L

    led = L(db_path)
    for i in range(2):
        ticket = led.enqueue_slot(name, label=f"job{i}")
        while not led.try_grant_slot(ticket, limit=1):
            time.sleep(0.02)
        out.put(("held", len(led.slot_queue_state()["holding"])))
        time.sleep(0.05)
        led.release_slot(ticket)
    led.close()


def test_slot_queue_holds_under_real_processes(tmp_path):
    # The two-Ledger tests above exercise the SQL; only real processes catch
    # the startup race, where two agents opening the ledger at the same instant
    # both tried to switch it into WAL and one died on "database is locked".
    import multiprocessing as mp

    db = str(tmp_path / "procs.sqlite")
    queue = mp.Queue()
    procs = [
        mp.Process(target=_slot_agent, args=(db, f"agent-{n}", queue))
        for n in range(3)
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=30)

    observed = []
    while not queue.empty():
        observed.append(queue.get()[1])

    assert [p.exitcode for p in procs] == [0, 0, 0], "an agent crashed on startup"
    assert len(observed) == 6, "every job must eventually get the slot"
    assert max(observed) == 1, f"slot limit violated: {observed}"


def _alpha_record(**overrides):
    record = {
        "id": "AL1",
        "name": None,
        "settings": {
            "region": "USA",
            "universe": "TOP3000",
            "delay": 1,
            "neutralization": "SUBINDUSTRY",
            "decay": 12,
            "truncation": 0.03,
        },
        "regular": {"code": "pv = ts_rank(ts_backfill(eps_mean, 60) / close, 66); pv"},
        "is": {
            "sharpe": 1.68,
            "fitness": 1.3,
            "turnover": 0.083,
            "returns": 0.075,
            "drawdown": 0.055,
            "checks": [{"name": "LOW_SHARPE", "result": "PASS"}],
        },
    }
    record.update(overrides)
    return record


def test_datafields_ignores_operators_and_locals():
    code = "pv = ts_rank(ts_backfill(eps_mean, 60) / close, 66); group_rank(pv, sector)"
    # ts_rank/ts_backfill/group_rank are calls, pv is assigned, sector is a
    # group argument — only the two real datafields should survive.
    assert alphas_mod.datafields_in(code) == ["eps_mean", "close"]


def test_describe_is_deterministic_and_uses_the_mining_label():
    alpha = _alpha_record()
    first = alphas_mod.describe(alpha, label="eps_to_price:eps_mean")
    second = alphas_mod.describe(alpha, label="eps_to_price:eps_mean")
    assert first == second, "labels must be reproducible, not time-dependent"
    assert first["name"] == "USA/TOP3000 D1 · eps_to_price:eps_mean · Sh1.68 Fit1.30"
    assert "tpl-eps_to_price" in first["tags"]
    assert first["tags"][0] == alphas_mod.TOOL_TAG
    assert first["color"] == alphas_mod.COLOR_PASS


def test_describe_colours_by_failing_check_count():
    def color_for(*results):
        checks = [{"name": f"C{i}", "result": r} for i, r in enumerate(results)]
        alpha = _alpha_record(**{"is": {"sharpe": 1.0, "checks": checks}})
        return alphas_mod.describe(alpha)["color"]

    assert color_for("PASS", "PASS") == alphas_mod.COLOR_PASS
    assert color_for("FAIL", "PASS") == alphas_mod.COLOR_BORDERLINE
    assert color_for("FAIL", "FAIL") == alphas_mod.COLOR_FAIL
    # No checks at all is unknown, not a pass.
    assert alphas_mod.describe(_alpha_record(**{"is": {}}))["color"] == (
        alphas_mod.COLOR_BORDERLINE
    )


def test_needs_labels_only_flags_anonymous_alphas():
    assert alphas_mod.needs_labels(_alpha_record()) is True
    assert alphas_mod.needs_labels(_alpha_record(name="   ")) is True
    assert alphas_mod.needs_labels(_alpha_record(name="mine")) is False


def test_describe_survives_a_bare_expression_with_no_stats():
    # Alphas simulated outside this tool arrive with no label and no is block.
    alpha = _alpha_record(regular={"code": "rank(close)"}, **{"is": {}})
    described = alphas_mod.describe(alpha)
    assert described["name"].endswith("close · Sh? Fit?")
    assert "close" in described["tags"]


def test_account_snapshot_renders_without_leaking_into_tracked_docs(tmp_path):
    from wqo import account as account_mod

    data = {
        "user_id": "AM00001",
        "level": "BRONZE",
        "concurrency": 1,
        "operator_count": 66,
        "submitted_alphas": 2,
        "competitions": [
            {
                "name": "Challenge",
                "rank": 29151,
                "score": 1950.0,
                "alphas": 1,
                "level": "SILVER",
                "next_level_at": 5000.0,
            }
        ],
        "gated": [{"path": "/users/self/consultant", "status": 403}],
    }
    target = tmp_path / "ACCOUNT.local.md"
    account_mod.write_snapshot(data, target, "2026-07-30 19:37 UTC")
    text = target.read_text()

    assert "AM00001" in text and "BRONZE" in text
    assert "/users/self/consultant" in text
    assert "29151" in text
    # The default location must stay gitignored — this file is per-user.
    assert config.ACCOUNT_SNAPSHOT_PATH.name == "ACCOUNT.local.md"


def test_kv_roundtrip(ledger):
    ledger.set("learned_concurrency", 3)
    assert ledger.get("learned_concurrency") == 3
    ledger.set("learned_concurrency", 5)
    assert ledger.get("learned_concurrency") == 5
    assert ledger.get("missing", "fallback") == "fallback"


def test_ledger_is_usable_from_worker_threads(ledger):
    # simulate_many shares one Ledger across a thread pool; sqlite's default
    # check_same_thread=True raised ProgrammingError on every mining run.
    import threading

    settings = build_settings(region="USA")
    errors = []

    def worker(i):
        try:
            row_id = ledger.start_simulation(f"rank(close{i})", settings)
            ledger.finish_simulation(row_id, {"id": f"AL{i}", "is": {"sharpe": 1.0}})
            ledger.simulations_today()
        except Exception as exc:  # noqa: BLE001 — surfaced to the main thread
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert ledger.simulations_today() == 8


# --------------------------------------------------------------------------
# gate
# --------------------------------------------------------------------------


THRESHOLDS = GateThresholds(
    min_sharpe=1.25,
    min_fitness=1.0,
    min_turnover=0.01,
    max_turnover=0.70,
    max_self_correlation=0.70,
    max_prod_correlation=0.70,
)


def alpha_record(**stats):
    base = {
        "sharpe": 1.5,
        "fitness": 1.2,
        "turnover": 0.25,
        "returns": 0.2,
        "drawdown": 0.05,
        "checks": [],
    }
    base.update(stats)
    return {"id": "AL1", "is": base}


def test_gate_passes_a_clean_alpha():
    report = gate.build_report(
        alpha_record(), self_corr=0.2, prod_corr=0.3, thresholds=THRESHOLDS
    )
    assert report.passed
    assert report.failures == []


def test_gate_blocks_low_sharpe():
    report = gate.build_report(
        alpha_record(sharpe=0.8), self_corr=0.1, prod_corr=0.1, thresholds=THRESHOLDS
    )
    assert not report.passed
    assert "sharpe" in [c.name for c in report.failures]


def test_gate_accepts_strongly_negative_sharpe():
    # A -1.5 Sharpe alpha is a 1.5 Sharpe alpha with the sign flipped, so the
    # gate must not reject it on magnitude.
    report = gate.build_report(
        alpha_record(sharpe=-1.5, fitness=-1.2),
        self_corr=0.1,
        prod_corr=0.1,
        thresholds=THRESHOLDS,
    )
    assert report.passed


def test_gate_blocks_turnover_outside_band():
    low = gate.build_report(
        alpha_record(turnover=0.001), self_corr=0.1, prod_corr=0.1, thresholds=THRESHOLDS
    )
    high = gate.build_report(
        alpha_record(turnover=0.95), self_corr=0.1, prod_corr=0.1, thresholds=THRESHOLDS
    )
    assert not low.passed and not high.passed


def test_gate_blocks_high_correlation():
    report = gate.build_report(
        alpha_record(), self_corr=0.85, prod_corr=0.1, thresholds=THRESHOLDS
    )
    assert not report.passed
    assert "self_correlation" in [c.name for c in report.failures]


def test_gate_blocks_deep_drawdown():
    report = gate.build_report(
        alpha_record(drawdown=0.18), self_corr=0.1, prod_corr=0.1, thresholds=THRESHOLDS
    )
    assert not report.passed
    assert "drawdown" in [c.name for c in report.failures]


def test_drawdown_sign_is_ignored():
    # Drawdown is reported as a magnitude in some payloads and negative in
    # others; both mean the same 5% decline.
    for value in (0.05, -0.05):
        report = gate.build_report(
            alpha_record(drawdown=value),
            self_corr=0.1,
            prod_corr=0.1,
            thresholds=THRESHOLDS,
        )
        assert report.passed


def test_missing_drawdown_is_skipped_not_failed():
    record = alpha_record()
    del record["is"]["drawdown"]
    report = gate.build_report(
        record, self_corr=0.1, prod_corr=0.1, thresholds=THRESHOLDS
    )
    statuses = {c.name: c.status for c in report.criteria}
    assert statuses["drawdown"] == gate.SKIPPED
    assert report.passed


def test_high_self_correlation_explains_the_sharpe_exemption():
    # Crossing 0.7 is not automatically fatal — BRAIN allows it when the new
    # alpha's Sharpe beats the one it duplicates by >10%. We cannot evaluate
    # that locally, so the criterion must say so rather than assert a verdict.
    report = gate.build_report(
        alpha_record(), self_corr=0.85, prod_corr=0.1, thresholds=THRESHOLDS
    )
    criterion = next(c for c in report.criteria if c.name == "self_correlation")
    assert criterion.status == gate.FAIL
    assert "10%" in criterion.detail


def test_missing_correlation_is_skipped_not_failed():
    report = gate.build_report(alpha_record(), thresholds=THRESHOLDS)
    statuses = {c.name: c.status for c in report.criteria}
    assert statuses["self_correlation"] == gate.SKIPPED
    assert report.passed


def test_brain_checks_are_authoritative():
    report = gate.build_report(
        alpha_record(
            checks=[
                {"name": "LOW_SHARPE", "result": "PASS", "value": 1.5, "limit": 1.25},
                {"name": "CONCENTRATED_WEIGHT", "result": "FAIL"},
            ]
        ),
        self_corr=0.1,
        prod_corr=0.1,
        thresholds=THRESHOLDS,
    )
    assert not report.passed
    assert "concentrated_weight" in [c.name for c in report.failures]


def test_pending_brain_check_blocks_pass():
    report = gate.build_report(
        alpha_record(checks=[{"name": "SELF_CORRELATION", "result": "PENDING"}]),
        self_corr=0.1,
        prod_corr=0.1,
        thresholds=THRESHOLDS,
    )
    assert not report.passed
    assert report.pending


def test_report_renders_without_error():
    report = gate.build_report(alpha_record(), self_corr=0.2, prod_corr=0.2)
    text = report.render()
    assert "AL1" in text and "PASSED" in text


# --------------------------------------------------------------------------
# correlation parsing
# --------------------------------------------------------------------------


def test_max_correlation_from_recordset():
    from wqo import alphas

    payload = {
        "schema": {"properties": [{"name": "alphaId"}, {"name": "correlation"}]},
        "records": [["AL1", 0.31], ["AL2", 0.62], ["AL3", 0.15]],
    }
    assert alphas.max_correlation(payload) == pytest.approx(0.62)
    assert alphas.max_correlation({"max": 0.44}) == pytest.approx(0.44)
    assert alphas.max_correlation(None) is None
    assert alphas.max_correlation({"records": []}) is None


# --------------------------------------------------------------------------
# slots
# --------------------------------------------------------------------------


def test_slot_manager_shrinks_on_throttle_and_grows_on_success(ledger):
    slots = SlotManager(ledger, initial=3)
    slots.report_throttled()
    assert slots.limit == 2
    assert ledger.get("learned_concurrency") == 2

    # The first clean run only clears the throttle flag; growth needs a streak
    # of genuinely clean acquisitions afterwards. Growth back to 3 is *not*
    # asserted here — 3 is now a known-bad ceiling and re-probing it takes a
    # much longer streak (see test_slot_manager_remembers_a_throttled_ceiling).
    slots.report_success()
    assert slots.limit == 2

    # A manager that has never been throttled grows on the ordinary streak.
    fresh = SlotManager(ledger, initial=2)
    fresh._ceiling = None
    for _ in range(3):
        fresh.report_success()
    assert fresh.limit == 3


def test_slot_manager_throttle_blocks_drift_on_single_slot(ledger):
    # A one-slot account that keeps hitting 429s must not creep upward just
    # because polling succeeds in between; every throttle must win.
    slots = SlotManager(ledger, initial=1)
    for _ in range(20):
        slots.report_success()  # polling success: never a 429
        slots.report_throttled()  # but the next POST proves one slot
        assert slots.limit == 1


def test_slot_manager_remembers_a_throttled_ceiling(ledger):
    # Once BRAIN 429s at 3 concurrent, growing back to 3 must take far more
    # evidence than the ordinary streak, otherwise the limit oscillates
    # 2 -> 3 -> 429 -> 2 forever on an account that only has 2 slots.
    from wqo.simulate import GROWTH_STREAK, RETRY_CEILING_STREAK

    slots = SlotManager(ledger, initial=3)
    slots.report_throttled()
    assert slots.limit == 2

    slots.report_success()  # clears the throttle flag, does not grow
    assert slots.limit == 2

    for _ in range(GROWTH_STREAK):
        slots.report_success()
    assert slots.limit == 2, "must not re-probe the ceiling on a short streak"

    for _ in range(RETRY_CEILING_STREAK):
        slots.report_success()
    assert slots.limit == 3, "a long clean streak may re-probe the ceiling"


def test_slot_manager_grows_freely_below_the_ceiling(ledger):
    from wqo.simulate import GROWTH_STREAK

    slots = SlotManager(ledger, initial=5)
    slots.report_throttled()  # ceiling = 5, limit = 4
    slots.report_success()  # clears flag
    # 4 -> 5 would touch the ceiling, so drop lower first and confirm normal
    # growth still works well below it.
    slots.report_throttled()  # ceiling = 4, limit = 3
    slots.report_throttled()  # ceiling = 3, limit = 2
    slots.report_success()
    slots._ceiling = 9  # far above; ordinary growth applies
    for _ in range(GROWTH_STREAK):
        slots.report_success()
    assert slots.limit == 3


def test_slot_manager_never_drops_below_one(ledger):
    slots = SlotManager(ledger, initial=1)
    slots.report_throttled()
    assert slots.limit == 1


def test_slot_manager_reloads_learned_value(ledger):
    ledger.set("learned_concurrency", 4)
    assert SlotManager(ledger).limit == 4


# --------------------------------------------------------------------------
# templates / generation / ranking
# --------------------------------------------------------------------------


def test_template_expansion_backfills_and_substitutes():
    template = templates.by_name("ts_reversal")
    exprs = list(template.expand("close"))
    prefix = f"-ts_delta(ts_backfill(close, {templates.BACKFILL_DAYS})"
    assert all(e.startswith(prefix) for e in exprs)
    assert len(exprs) == len(templates.DAYS)


def test_backfill_window_matches_quarterly_reporting():
    # 60 trading days is the documented norm for quarterly fundamentals; a
    # shorter window leaves NaN gaps that distort cross-sectional ranks.
    assert templates.BACKFILL_DAYS == 60


def test_template_expressions_avoid_scientific_notation():
    # BRAIN's FASTEXPR parser rejects literals like 1e-9 ("Unexpected character
    # 'e'"), so epsilons must be written as plain decimals.
    import re

    for template in templates.TEMPLATES:
        assert not re.search(r"\d[eE][+-]?\d", template.expr), template.name


def test_reference_patterns_are_available():
    names = {t.name for t in templates.TEMPLATES}
    assert {"group_rank_reversal", "liquidity_gated", "estimate_to_price"} <= names

    gated = next(t for t in templates.TEMPLATES if t.name == "liquidity_gated")
    assert "adv20" in gated.expr  # use the real field, not a recomputed average

    reversal = next(t for t in templates.TEMPLATES if t.name == "group_rank_reversal")
    expr = next(reversal.expand("close"))
    assert expr.startswith("group_rank(-ts_delta(")


def test_templates_filtered_by_available_operators():
    available = {"rank", "ts_backfill"}
    usable = templates.templates_for("MATRIX", available)
    names = {t.name for t in usable}
    assert "cs_rank" in names
    assert "group_neutral_rank" not in names  # needs group_neutralize


def test_vector_templates_only_offered_for_vector_fields():
    matrix = {t.name for t in templates.templates_for("MATRIX", None)}
    vector = {t.name for t in templates.templates_for("VECTOR", None)}
    assert "vector_mean_rank" in vector and "vector_mean_rank" not in matrix
    assert "cs_rank" in matrix and "cs_rank" not in vector


# -- 151 Trading Strategies templates ---------------------------------------


def test_template_expansions_are_distinct():
    """Every knob combination must reach the expression.

    Counting expansions against the size of the knob grid only restates what
    ``expand`` does. What can actually break is a knob that is declared but
    never interpolated, or two knobs sharing a placeholder: both collapse
    distinct combinations onto duplicate expressions, silently spending
    simulation slots on the same candidate twice.
    """
    for template in templates.TEMPLATES:
        exprs = list(template.expand("close"))
        assert len(exprs) == len(set(exprs)), (
            f"{template.name}: duplicate expansions, a knob is unused in expr"
        )


def test_template_knobs_all_appear_in_expression():
    for template in templates.TEMPLATES:
        for knob in template.knobs:
            assert "{%s}" % knob in template.expr, (
                f"{template.name}: knob {knob!r} declared but not used"
            )


def test_new_templates_produce_valid_expressions():
    """Expanded expressions must not contain unresolved {placeholders}."""
    for template in templates.TEMPLATES:
        for expr in template.expand("revenue"):
            assert "{" not in expr and "}" not in expr, (
                f"{template.name}: unresolved placeholder in {expr!r}"
            )


def test_new_templates_declare_operators():
    """Every template must declare at least one operator for account-level gating."""
    for template in templates.TEMPLATES:
        assert len(template.operators) > 0, f"{template.name} declares no operators"


def test_151_templates_present():
    """All 12 templates from the 151 Strategies PR must exist."""
    names = {t.name for t in templates.TEMPLATES}
    expected = {
        "dual_momentum", "low_volatility", "residual_momentum",
        "ma_distance_zscore", "channel_position", "exp_decay_momentum",
        "volume_gated_reversal", "multifactor_level_change",
        "vol_scaled_reversal", "ma_crossover", "value_momentum_combo",
        "days_since_extreme",
    }
    assert expected <= names, f"missing: {expected - names}"


def test_every_template_regime_is_defined():
    """A typo in a regime name must not silently fall back to balanced."""
    for template in templates.TEMPLATES:
        assert template.regime in config.REGIMES, (
            f"{template.name}: unknown regime {template.regime!r}"
        )


class FakeCatalog:
    """Minimal stand-in for Catalog: one well-covered matrix field, all operators."""

    def fields(self, **_kwargs):
        return [{"id": "close", "type": "MATRIX", "coverage": 1.0}]

    def operators(self):
        ops = {op for t in templates.TEMPLATES for op in t.operators}
        # templates_for adds ts_backfill to the requirements of any backfilled
        # template; without it every template filters out and generate()
        # returns nothing, which would make these tests pass vacuously.
        ops.add("ts_backfill")
        return [{"name": name} for name in ops]


def _jobs(**spec_kwargs):
    spec = generator.GenerationSpec(budget=10_000, seed=0, **spec_kwargs)
    jobs = generator.generate(FakeCatalog(), spec)
    assert jobs, "fixture produced no jobs; the assertions below would be vacuous"
    return jobs


def test_generate_costs_one_slot_per_expression_by_default():
    """No settings sweep means job count equals distinct expression count.

    The budget truncates the job list, so sweeping every expression across N
    variants would cut the number of distinct expressions actually simulated
    by N — on a one-slot account that trades search breadth for redundancy.
    """
    jobs = _jobs()
    assert len(jobs) == len({j.code for j in jobs})


def test_generate_applies_the_regime_declared_by_the_template():
    by_name = {t.name: t for t in templates.TEMPLATES}
    for job in _jobs():
        template_name = job.label.split(":", 1)[0]
        expected = config.REGIMES[by_name[template_name].regime]
        for key, value in expected.items():
            assert job.settings[key] == value, f"{job.label}: {key} is {job.settings[key]}"


def test_explicit_variants_still_sweep_every_expression():
    """Callers that want a settings sweep keep it by passing variants."""
    variants = ({"decay": 2}, {"decay": 20})
    jobs = _jobs(variants=variants)
    assert len(jobs) == 2 * len({j.code for j in jobs})
    assert {j.settings["decay"] for j in jobs} == {2, 20}


def sim_result(sharpe, fitness=1.2, turnover=0.25, checks=None, drawdown=0.05, returns=0.15):
    return SimResult(
        code="rank(close)",
        settings={},
        status="COMPLETE",
        alpha_id="AL1",
        alpha={
            "id": "AL1",
            "is": {
                "sharpe": sharpe,
                "fitness": fitness,
                "turnover": turnover,
                "drawdown": drawdown,
                "returns": returns,
                "checks": checks or [],
            },
        },
    )


def test_score_prefers_higher_sharpe():
    assert rank.score(sim_result(2.0)).score > rank.score(sim_result(1.3)).score


def test_score_penalises_turnover_overshoot():
    ok = rank.score(sim_result(1.5, turnover=0.3)).score
    churny = rank.score(sim_result(1.5, turnover=0.95)).score
    assert churny < ok


def test_failed_simulations_score_lowest():
    failed = SimResult(code="x", settings={}, status="ERROR", error="boom")
    assert rank.score(failed).score == float("-inf")


def test_score_penalises_drawdown_overshoot():
    """Drawdown exceeding the threshold must reduce the score proportionally."""
    clean = rank.score(sim_result(1.5, drawdown=0.05)).score
    risky = rank.score(sim_result(1.5, drawdown=0.20)).score
    assert risky < clean
    # Penalty is bounded: even extreme drawdown should not go below -inf
    extreme = rank.score(sim_result(1.5, drawdown=0.90)).score
    assert extreme > float("-inf")
    assert extreme < risky


def test_score_ignores_returns():
    """Returns must not move the score on its own.

    It already enters through fitness, and rewarding it again would refund
    part of the drawdown penalty to the highest-drawdown candidates, which
    tend to be the highest-returns ones.
    """
    low_ret = rank.score(sim_result(1.5, returns=0.05)).score
    high_ret = rank.score(sim_result(1.5, returns=0.40)).score
    assert low_ret == pytest.approx(high_ret)


def test_shortlist_drops_alphas_over_the_drawdown_limit():
    """A deep-drawdown alpha is a certain gate failure, so it never shortlists."""
    deep = sim_result(2.6, fitness=1.9, drawdown=0.26)
    clean = sim_result(1.5, fitness=1.1, drawdown=0.04)
    best = rank.shortlist([deep, clean], limit=5)
    assert [s.result.stats["drawdown"] for s in best] == [0.04]


def test_shortlist_keeps_alphas_with_no_reported_drawdown():
    """gate.py skips an unreported drawdown; the shortlist must agree."""
    result = sim_result(1.5)
    del result.alpha["is"]["drawdown"]
    assert len(rank.shortlist([result], limit=5)) == 1


def test_score_drawdown_penalty_is_bounded():
    """The drawdown penalty must not exceed -3.0 (1.5 * min(overshoot, 2.0))."""
    base = rank.score(sim_result(1.5, drawdown=0.05)).score
    worst = rank.score(sim_result(1.5, drawdown=1.0)).score
    # The difference from drawdown alone should be at most 3.0
    # (other factors like returns are constant between the two calls)
    assert base - worst <= 3.0 + 0.01  # small float tolerance


def test_shortlist_drops_failing_and_weak_candidates():
    results = [
        sim_result(2.0),
        sim_result(0.5),  # below min sharpe
        sim_result(1.9, checks=[{"name": "CONCENTRATED_WEIGHT", "result": "FAIL"}]),
    ]
    best = rank.shortlist(results, limit=5)
    assert len(best) == 1
    assert best[0].result.stats["sharpe"] == 2.0


# --------------------------------------------------------------------------
# submission guard — the safety-critical path
# --------------------------------------------------------------------------


def preparation(passed: bool):
    from wqo.submit import Preparation

    checks = [] if passed else [{"name": "CONCENTRATED_WEIGHT", "result": "FAIL"}]
    alpha = alpha_record(checks=checks)
    report = gate.build_report(alpha, self_corr=0.1, prod_corr=0.1, thresholds=THRESHOLDS)
    assert report.passed is passed
    return Preparation(alpha=alpha, report=report, self_corr=0.1, prod_corr=0.1)


class ExplodingSession:
    """Any HTTP call from here is a bug — submission must not reach the network."""

    def request(self, *args, **kwargs):
        raise AssertionError("submission attempted without confirmation")


def test_submit_refuses_without_confirmation():
    from wqo.submit import SubmissionRefused, submit

    with pytest.raises(SubmissionRefused, match="not confirmed"):
        submit(
            ExplodingSession(),
            "AL1",
            confirmed=False,
            preparation=preparation(passed=True),
        )


def test_submit_refuses_when_gate_is_dirty_even_if_confirmed():
    from wqo.submit import SubmissionRefused, submit

    with pytest.raises(SubmissionRefused, match="gate is not clean"):
        submit(
            ExplodingSession(),
            "AL1",
            confirmed=True,
            preparation=preparation(passed=False),
        )


def test_submit_respects_budget_before_sending(ledger, monkeypatch):
    from wqo import config as cfg
    from wqo.submit import submit

    monkeypatch.setattr(cfg.BUDGET, "submissions_per_day", 1)
    ledger.record_submission("AL0", "SUBMITTED")
    with pytest.raises(BudgetExceeded):
        submit(
            ExplodingSession(),
            "AL1",
            confirmed=True,
            ledger=ledger,
            preparation=preparation(passed=True),
        )


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------


def test_build_settings_overrides_and_ignores_none():
    settings = build_settings(region="EUR", delay=None, decay=12)
    assert settings["region"] == "EUR"
    assert settings["decay"] == 12
    assert settings["delay"] == 1  # None must not clobber the default
    assert settings["language"] == "FASTEXPR"
