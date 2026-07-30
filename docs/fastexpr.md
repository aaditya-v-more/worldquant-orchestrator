# FASTEXPR constraints

Syntax and availability rules for BRAIN's expression language. Most of these
cost a real simulation slot to discover, so check here before writing an
expression.

## Syntax

**No scientific notation.** The parser rejects it:

```
1e-9        →  Unexpected character 'e'
0.000000001 →  fine
```

This bit the `mean_reversion_ratio` and `scaled_change` templates. Any epsilon
you add to a denominator must be written as a decimal literal.

**Named arguments** use `=` with no spaces: `winsorize(zscore(x), std=4)`.

**Groups** are bare identifiers, not strings: `group_neutralize(rank(x), subindustry)`.
Valid values: `subindustry`, `industry`, `sector`, `market`.

## Operator availability depends on account level

A low-tier account has roughly 66 operators, and the count does not change on
the promotion from `NONE` to `BRONZE`. That is not the full set — some
documented operators simply are not there, and using one fails the simulation
and burns a slot. Check first:

```bash
.venv/bin/python -m wqo data operators
```

Available at this level, grouped roughly:

```
arithmetic   add subtract multiply divide inverse power signed_power sqrt log abs sign reverse min max
logical      and or not equal not_equal greater greater_equal less less_equal if_else is_nan
cross-sect   rank zscore scale quantile normalize winsorize bucket densify
time-series  ts_mean ts_sum ts_product ts_std_dev ts_delta ts_delay ts_rank ts_zscore ts_scale
             ts_corr ts_covariance ts_regression ts_decay_linear ts_backfill ts_quantile
             ts_arg_max ts_arg_min ts_av_diff ts_count_nans ts_step
group        group_mean group_rank group_zscore group_neutralize group_scale group_backfill
vector       vec_avg vec_sum
other        trade_when hump kth_element last_diff_value days_from_last_change
```

`wqo/mining/templates.py` declares each template's `operators` tuple, and the
generator drops templates whose operators are unavailable — so mining never
wastes a slot on this. Hand-written expressions get no such protection.

## Data fields

**Backfill sparse fundamentals.** Fundamentals report quarterly; between report
dates the field is NaN. A field that is NaN for most names on most days
concentrates the entire book into the few names that have data, which shows up
as a `CONCENTRATED_WEIGHT` failure that looks unrelated to the data.

```
ts_backfill(fundamental_field, 60)
```

60 trading days is the norm for quarterly data.

**`adv20` exists** in the `pv1` dataset — 20-day average daily volume. Use it
directly for liquidity gating instead of recomputing it:

```
trade_when(volume > adv20, rank(signal), -1)
```

The `pv1` dataset is the price/volume core: `open high low close vwap volume
adv20 cap returns sharesout dividend split adjfactor sector industry subindustry
market country exchange currency ticker cusip isin sedol`.

**Vector fields** need `vec_avg` or `vec_sum` before any cross-sectional
operator. Applying `rank` directly to a vector field fails.

**Field scope.** Datafields are scoped by region + delay + universe. A field
present for USA/TOP3000/delay-1 may not exist for EUR/TOP2500. Always query
`wqo data fields` with the settings the alpha will actually run under.

## Search result cap

`wqo data fields --search <term>` is capped at 100 results by the API —
`offset + limit > 100` returns `400 Invalid query`. The client stops at the
ceiling rather than erroring. Narrow the search or filter by `--dataset` if you
need more.

## Sign

Sharpe of −1.8 is a good alpha with a minus sign missing. The gate uses absolute
value for Sharpe and fitness. Do not discard negative results — invert them.
