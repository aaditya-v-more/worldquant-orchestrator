# Alpha research reference

Reviewed against WQO 0.1.0 on 2026-09-07. This reference separates local code
behavior from research examples. The earlier privately supplied report titled
*Quantitative Alpha Research: WorldQuant BRAIN* (dated 2026-06-13) has no verified
author or public source link. It is not distributed here or treated as an
authoritative citation. Traceable references appear below.

Expressions and simulation settings are sent to BRAIN. Examples are illustrative
research hypotheses; backtest results do not guarantee future performance.

## Local gate defaults

These are WQO defaults from [config.py](../wqo/config.py), implemented in
[gate.py](../wqo/gate.py), not universal BRAIN acceptance requirements. BRAIN's
returned checks determine platform eligibility; WQO can additionally refuse an
alpha under its local policy. A passing local report cannot guarantee acceptance.

| Metric | Local rule |
|---|---|
| Sharpe | Absolute value ≥ 1.25 |
| Fitness | Absolute value ≥ 1.0 |
| Turnover | 1%–70%, inclusive; missing value fails |
| Drawdown | Absolute value ≤ 10%; missing value is skipped |
| Self-correlation | < 0.70 when available; otherwise skipped |
| Production correlation | < 0.70 when available; otherwise skipped |
| Weight concentration | Read BRAIN's returned check and limit; no separate local 10% rule |

The local gate uses absolute Sharpe and fitness. A negative signal may warrant
inversion and a new backtest; the gate does not invert it automatically. Inspect
BRAIN's checks on the actual expression before considering submission.

At self-correlation ≥ 0.70, WQO fails the local criterion and mentions a configured
10% Sharpe-improvement exemption. It cannot evaluate that exemption from the
correlation value alone. Treat the message as a diagnostic, not a verified
current platform entitlement. Skipped checks are not passing measurements.

## Fitness interpretation

The working formula retained from earlier research notes is:

```
Fitness = Sharpe × sqrt( |Returns| / max(Turnover, 0.125) )
```

A public primary BRAIN definition was not independently verified in this review;
confirm it in the signed-in Learn documentation before relying on it. WQO uses
the `fitness` value returned by BRAIN rather than recomputing it with this formula.

Under this formula, Sharpe 1.26 and turnover 0.34 require absolute returns of
`0.34 / 1.26² ≈ 0.2142` for fitness 1.0. Returns and turnover use decimal units.
Below the 0.125 turnover floor, lowering turnover alone does not change the
formula's denominator. Changing decay can also change returns and Sharpe, so
this arithmetic is not a promise that a parameter change improves fitness.

## Example patterns to test

**Group-ranked reversal.** Rank a negative price change within a subindustry:

```
group_rank(-ts_delta(price_field, N), subindustry)
```

This is the repository's `group_rank_reversal` pattern. Group ranking does not
by itself establish portfolio neutrality or future predictive power.

**Correct attribution for Alpha #4.** Zura Kakushadze's *101 Formulaic Alphas*
(2016), [Appendix A, page 8](https://arxiv.org/pdf/1601.00991v3#page=8), gives:

```
(-1 * Ts_Rank(rank(low), 9))
```

That is the paper's notation, not a tested BRAIN command. The previously shown
`group_rank(-ts_delta(log(close), 1), subindustry)` is a different expression and
must not be attributed to Alpha #4.

**Conditional updates.** The `liquidity_gated` template uses:

```
trade_when(volume > adv20, alpha_signal, -1)
```

The third argument is an exit trigger, not a fallback signal value. Check the
operator definition available to your account before use. No reduction in market
impact or improvement in returns is established by this example. Confirm `adv20`
and every other input for the selected region, universe and delay.

**Sparse inputs.** `ts_backfill(fundamental_field, 60)` carries earlier observations
into gaps within a chosen lookback. Inspect coverage, update frequency and data
age first: 60 is an example, not a universal quarterly-data rule. Dense fields
may not need backfill, and carrying stale values has its own consequences.

**Other data families.** For vector fields, consider available `vec_sum` or
`vec_avg` operators; for estimates, investigate `ts_rank(estimate_field / close, N)`.
Replace placeholders with compatible fields discovered using `wqo data fields`.
No field ID here implies access for every account.

See [mining/templates.py](../wqo/mining/templates.py) for `group_rank_reversal`,
`liquidity_gated`, `BACKFILL`, `estimate_to_price`, `vector_mean_rank` and
`vector_sum_zscore`. Their presence in code is not evidence of profitable results.

## Diagnosing results

| Symptom | Hypothesis to investigate |
|---|---|
| Low Sharpe | Signal noise, sign, economic rationale and stability across periods |
| Concentrated weights | Sparse coverage, outliers, neutralization and truncation |
| High turnover | Signal update frequency, decay and conditional updates |
| Infrequent trading | Stale inputs, long smoothing windows or restrictive conditions |
| Self-correlation failure | Whether the data or hypothesis adds distinct information |
| Strong in-sample results | Selection bias and performance on held-out data |

These are investigation paths, not guaranteed fixes. Record failed candidates;
repeatedly tuning on a held-out window turns it into another training window.

## Grade and test period

When present, BRAIN's read-only `grade` runs from `INFERIOR` through `AVERAGE`,
`GOOD`, `EXCELLENT` and `SPECTACULAR`. WQO reports it and supports
`wqo alpha list --grade EXCELLENT`. Grade does not determine the gate verdict.

`--test-period` accepts `1y`, `6m`, `1y6m` or `P1Y6M`; WQO normalizes these into
BRAIN's `testPeriod` setting. The default is `P0Y0M`, with no reserved tail.
Compare in-sample statistics only over matching windows and settings. Reserving
a tail alone does not establish that WQO has fetched or evaluated out-of-sample
results; inspect which statistics the platform actually returns.

## Account eligibility and sources

Use `wqo account status` for returned competition progress. Fixed point thresholds
and consultant-invitation promises are omitted because current eligibility was
not verified. Refer to the terms and rules shown for your own account.

- Zura Kakushadze, *101 Formulaic Alphas* (2016; arXiv v3, 18 March 2016),
  [paper and publication record](https://arxiv.org/abs/1601.00991v3).
  Appendix A supports the Alpha #4 attribution above.
- Igor Tulchinsky (ed.), *Finding Alphas: A Quantitative Approach to Building
  Trading Strategies*, second edition (Wiley, 2019),
  [publisher record](https://onlinelibrary.wiley.com/doi/book/10.1002/9781119571278).
  Further reading on research methods, not a source for current BRAIN quotas.
- WorldQuant, [BRAIN platform](https://platform.worldquantbrain.com): signed-in
  Learn documentation, operator descriptions and account-specific check results.
  Access may require an account; current private documentation was not fetched
  for this review.
- WQO maintainers, [gate implementation](../wqo/gate.py) and
  [defaults](../wqo/config.py), reviewed 2026-09-07. These support the local rules
  above. This repository does not redistribute the referenced publications.
