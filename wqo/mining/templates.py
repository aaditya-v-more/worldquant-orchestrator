"""Expression templates for systematic alpha search.

A template is a FASTEXPR string with ``{field}`` plus named knobs, together
with the value grid for those knobs. Expanding a template over a datafield and
its knob grid produces a family of related candidate alphas.

Templates declare which operators they use so the generator can drop any
template whose operators are not available at your access level — a new
account does not have the full operator set, and finding that out from a
failed simulation wastes a slot.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Iterator, Optional

#: Wrapping a sparse fundamental field in ts_backfill before anything else is
#: the single highest-value preprocessing step on BRAIN; without it a field
#: with quarterly updates spends most days as NaN. 60 trading days is the
#: documented norm for quarterly-reported data (docs/alpha-research.md).
BACKFILL_DAYS = 60
BACKFILL = "ts_backfill({field}, %d)" % BACKFILL_DAYS


@dataclass(frozen=True)
class Template:
    name: str
    expr: str
    operators: tuple[str, ...] = ()
    knobs: dict[str, tuple] = field(default_factory=dict)
    #: "matrix" for plain time-series fields, "vector" for vector fields.
    field_kinds: tuple[str, ...] = ("MATRIX",)
    #: Whether the raw field should be ts_backfill-wrapped first.
    backfill: bool = True
    #: Which entry of :data:`config.REGIMES` supplies decay, neutralization
    #: and truncation for this template. A momentum signal and a reversion
    #: signal want opposite decay, so the settings follow the template rather
    #: than being swept blindly across all of them.
    regime: str = "balanced"

    def expand(self, field_name: str) -> Iterator[str]:
        base = BACKFILL.format(field=field_name) if self.backfill else field_name
        if not self.knobs:
            yield self.expr.format(field=base)
            return
        keys = sorted(self.knobs)
        for combo in itertools.product(*(self.knobs[k] for k in keys)):
            yield self.expr.format(field=base, **dict(zip(keys, combo)))


DAYS = (5, 10, 22, 66)
LONG_DAYS = (22, 66, 252)
SHORT_DAYS = (5, 10, 22)
GROUPS = ("subindustry", "industry", "sector")


TEMPLATES: tuple[Template, ...] = (
    Template(
        name="cs_rank",
        expr="rank({field})",
        operators=("rank",),
    ),
    Template(
        name="cs_zscore",
        expr="zscore({field})",
        operators=("zscore",),
    ),
    Template(
        name="ts_reversal",
        expr="-ts_delta({field}, {d})",
        operators=("ts_delta",),
        knobs={"d": DAYS},
    ),
    Template(
        name="ts_momentum_rank",
        expr="ts_rank({field}, {d})",
        operators=("ts_rank",),
        knobs={"d": LONG_DAYS},
    ),
    Template(
        name="ts_zscore",
        expr="ts_zscore({field}, {d})",
        operators=("ts_zscore",),
        knobs={"d": LONG_DAYS},
    ),
    Template(
        name="mean_reversion_ratio",
        expr="{field} / (ts_mean({field}, {d}) + 0.000000001)",
        operators=("ts_mean",),
        knobs={"d": LONG_DAYS},
    ),
    Template(
        name="scaled_change",
        expr="ts_delta({field}, {d}) / (ts_std_dev({field}, {w}) + 0.000000001)",
        operators=("ts_delta", "ts_std_dev"),
        knobs={"d": DAYS, "w": LONG_DAYS},
    ),
    Template(
        name="group_neutral_rank",
        expr="group_neutralize(rank({field}), {g})",
        operators=("group_neutralize", "rank"),
        knobs={"g": GROUPS},
    ),
    Template(
        name="group_rank",
        expr="group_rank({field}, {g})",
        operators=("group_rank",),
        knobs={"g": GROUPS},
    ),
    Template(
        name="decayed_rank",
        expr="ts_decay_linear(rank({field}), {d})",
        operators=("ts_decay_linear", "rank"),
        knobs={"d": DAYS},
    ),
    Template(
        name="winsorized_zscore",
        expr="winsorize(zscore({field}), std=4)",
        operators=("winsorize", "zscore"),
    ),
    # The documented liquidity gate uses the adv20 field directly rather than
    # recomputing a 20-day volume average (docs/alpha-research.md).
    Template(
        name="liquidity_gated",
        expr="trade_when(volume > adv20, rank({field}), -1)",
        operators=("trade_when", "rank"),
    ),
    # Mean reversion with group ranking — the reference pattern; grouping by
    # subindustry strips sector-level bias and isolates the stock-specific move.
    Template(
        name="group_rank_reversal",
        expr="group_rank(-ts_delta({field}, {d}), {g})",
        operators=("group_rank", "ts_delta"),
        knobs={"d": (1, 5, 22), "g": GROUPS},
    ),
    # Analyst estimate revision: scale the estimate by price before ranking so
    # the signal is comparable across names.
    Template(
        name="estimate_to_price",
        expr="ts_rank({field} / close, {d})",
        operators=("ts_rank",),
        knobs={"d": LONG_DAYS},
    ),
    Template(
        name="corr_with_returns",
        expr="-ts_corr({field}, returns, {d})",
        operators=("ts_corr",),
        knobs={"d": LONG_DAYS},
    ),
    Template(
        name="vector_mean_rank",
        expr="rank(vec_avg({field}))",
        operators=("vec_avg", "rank"),
        field_kinds=("VECTOR",),
        backfill=False,
    ),
    Template(
        name="vector_sum_zscore",
        expr="zscore(vec_sum({field}))",
        operators=("vec_sum", "zscore"),
        field_kinds=("VECTOR",),
        backfill=False,
    ),
    # ------------------------------------------------------------------
    # Templates derived from *151 Trading Strategies* (Kakushadze & Serur)
    # ------------------------------------------------------------------
    # §3.1 Price-momentum: dual-horizon confirmation. A stock rising on both
    # a short and a long window has a stronger trend signal than either alone.
    Template(
        name="dual_momentum",
        expr="rank(ts_delta({field}, {d_short}) + ts_delta({field}, {d_long}))",
        operators=("ts_delta", "rank"),
        knobs={"d_short": (5, 10), "d_long": (22, 66)},
        regime="momentum",
    ),
    # §3.4 Low-volatility anomaly: stocks with lower recent volatility tend to
    # outperform on a risk-adjusted basis. The leading minus that "inverts" the
    # rank is omitted deliberately — scoring and the gate both take absolute
    # value, so a sign flip changes nothing but the reported sign.
    Template(
        name="low_volatility",
        expr="rank(ts_std_dev({field}, {d}))",
        operators=("ts_std_dev", "rank"),
        knobs={"d": (22, 66)},
        regime="balanced",
    ),
    # §3.7 Residual momentum: momentum after stripping group (sector/industry)
    # exposure. Isolates the stock-specific component of a trend.
    Template(
        name="residual_momentum",
        expr="group_neutralize(ts_delta({field}, {d}), {g})",
        operators=("group_neutralize", "ts_delta"),
        knobs={"d": SHORT_DAYS, "g": GROUPS},
        regime="momentum",
    ),
    # §3.9 Mean-reversion (Ornstein-Uhlenbeck style): z-scored distance from
    # the moving average. Larger deviation → stronger reversion expectation.
    Template(
        name="ma_distance_zscore",
        expr="ts_zscore({field} - ts_mean({field}, {d}), {d})",
        operators=("ts_zscore", "ts_mean"),
        knobs={"d": LONG_DAYS},
        regime="reversion",
    ),
    # §3.15 Channel breakout: position of current value within its own
    # min–max range over a lookback. Near 1 = breakout high, near 0 = low.
    Template(
        name="channel_position",
        expr="({field} - ts_min({field}, {d})) / (ts_max({field}, {d}) - ts_min({field}, {d}) + 0.000000001)",
        operators=("ts_min", "ts_max"),
        knobs={"d": LONG_DAYS},
        regime="momentum",
    ),
    # §10.4 Trend following (momentum) with exponential decay: weights recent
    # changes more heavily, producing a smoother momentum signal.
    Template(
        name="exp_decay_momentum",
        expr="ts_decay_linear(ts_delta({field}, 1), {d})",
        operators=("ts_decay_linear", "ts_delta"),
        knobs={"d": SHORT_DAYS},
        regime="momentum",
    ),
    # §10.3 Contrarian trading gated on market activity: mean-reversion signal
    # only fires when volume confirms participation (avoids stale reversals).
    # The third trade_when argument is the *exit* trigger, not a fallback
    # value; -1 never fires, matching liquidity_gated above.
    Template(
        name="volume_gated_reversal",
        expr="trade_when(volume > adv20, -ts_delta({field}, {d}), -1)",
        operators=("trade_when", "ts_delta"),
        knobs={"d": (1, 5, 10)},
        regime="reversion",
    ),
    # §3.6 / §3.20 Multifactor / Alpha combos: combine a level signal with a
    # change signal. Captures "cheap AND improving" style interactions.
    Template(
        name="multifactor_level_change",
        expr="rank({field}) + rank(-ts_delta({field}, {d}))",
        operators=("rank", "ts_delta"),
        knobs={"d": SHORT_DAYS},
        regime="value",
    ),
    # Volatility-scaled reversal (§3.4 + §3.9): mean-reversion normalized by
    # recent vol so the signal is comparable across high/low-vol names.
    Template(
        name="vol_scaled_reversal",
        expr="-ts_delta({field}, {d}) / (ts_std_dev({field}, {d}) + 0.000000001)",
        operators=("ts_delta", "ts_std_dev"),
        knobs={"d": SHORT_DAYS},
        regime="reversion",
    ),
    # §3.11/§3.12 Moving average crossover proxy: short MA minus long MA,
    # ranked cross-sectionally. Positive = short-term trend above long-term.
    Template(
        name="ma_crossover",
        expr="rank(ts_mean({field}, {d_fast}) - ts_mean({field}, {d_slow}))",
        operators=("ts_mean", "rank"),
        knobs={"d_fast": (5, 10), "d_slow": (22, 66)},
        regime="momentum",
    ),
    # §3.3 Value + momentum interaction: rank the field level, then weight by
    # recent momentum. Favors "cheap stocks that are starting to recover".
    Template(
        name="value_momentum_combo",
        expr="rank({field}) * ts_rank({field}, {d})",
        operators=("rank", "ts_rank"),
        knobs={"d": LONG_DAYS},
        regime="value",
    ),
    # §3.14 Support/resistance via arg-max/arg-min. Both operators report days
    # since the extreme, so the difference is signed: positive means the N-day
    # high is older than the low (the field has been falling toward support),
    # negative the reverse. It is a trend-direction signal, not a recency one.
    Template(
        name="days_since_extreme",
        expr="rank(ts_arg_max({field}, {d}) - ts_arg_min({field}, {d}))",
        operators=("ts_arg_max", "ts_arg_min", "rank"),
        knobs={"d": (22, 66)},
        regime="momentum",
    ),
)


def templates_for(
    field_kind: str, available_operators: Optional[set[str]] = None
) -> list[Template]:
    """Templates usable for a field kind, filtered by operator availability."""
    kind = (field_kind or "MATRIX").upper()
    out = []
    for template in TEMPLATES:
        if kind not in template.field_kinds:
            continue
        if available_operators is not None:
            needed = set(template.operators)
            if template.backfill:
                needed.add("ts_backfill")
            if not needed.issubset(available_operators):
                continue
        out.append(template)
    return out


def by_name(name: str) -> Template:
    for template in TEMPLATES:
        if template.name == name:
            return template
    raise KeyError(f"unknown template: {name}")
