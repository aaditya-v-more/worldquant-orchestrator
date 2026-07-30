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

from wqo import gate  # noqa: E402
from wqo.config import GateThresholds, Pacing  # noqa: E402
from wqo.mining import rank, templates  # noqa: E402
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


# -- 151 Trading Strategies template expansion counts -----------------------


def test_new_template_expansion_counts():
    """Each multi-knob template must expand to exactly len(knob1) × len(knob2) × … expressions."""
    import math

    for template in templates.TEMPLATES:
        exprs = list(template.expand("close"))
        if template.knobs:
            expected = math.prod(len(v) for v in template.knobs.values())
        else:
            expected = 1
        assert len(exprs) == expected, (
            f"{template.name}: expected {expected} expansions, got {len(exprs)}"
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


def test_score_rewards_returns():
    """Higher returns should boost the score (capped at +1.0)."""
    low_ret = rank.score(sim_result(1.5, returns=0.05)).score
    high_ret = rank.score(sim_result(1.5, returns=0.40)).score
    assert high_ret > low_ret
    # Bonus is capped: returns=0.5 and returns=1.0 give the same bonus
    capped_a = rank.score(sim_result(1.5, returns=0.5)).score
    capped_b = rank.score(sim_result(1.5, returns=1.0)).score
    assert capped_a == pytest.approx(capped_b)


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
