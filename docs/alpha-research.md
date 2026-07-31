# Alpha research reference

Distilled from *Quantitative Alpha Research: WorldQuant BRAIN* (Updated Edition,
2026-06-13) — the source PDF is `worldquant .pdf` in the repo root. Only the
parts that change how this tool behaves are recorded here; background material
and unverified compensation figures are noted at the bottom rather than encoded.

Where a number here conflicts with what BRAIN's own `/check` endpoint returns,
**BRAIN wins**. This file drives our local pre-filter, not the real gate.

---

## Passing criteria (delay 1)

| Metric | Requirement | Where enforced |
|---|---|---|
| Sharpe | > 1.25 | `GateThresholds.min_sharpe` |
| Fitness | > 1.0 | `GateThresholds.min_fitness` |
| Turnover | 1% – 70% | `min_turnover` / `max_turnover` |
| Drawdown | < 10% | `max_drawdown` |
| Weight concentration | < 10% | BRAIN's `CONCENTRATED_WEIGHT` check |
| Self-correlation | < 0.7 **or** Sharpe >10% better than the correlated alpha | `max_self_correlation` + `self_correlation_sharpe_exemption` |

The self-correlation exemption matters: crossing 0.7 is not automatically fatal
if the new alpha is meaningfully stronger than the one it duplicates. Our gate
still marks it FAIL, because evaluating the exemption needs the other alpha's
Sharpe — the criterion's `detail` says so rather than pretending it's final.

## Fitness

```
Fitness = Sharpe × sqrt( |Returns| / max(Turnover, 0.125) )
```

This is why fitness fails while Sharpe passes: fitness is Sharpe discounted by
turnover. The `max(Turnover, 0.125)` floor means trading less than 12.5% a day
earns no further fitness credit — below that, only returns and Sharpe help.

Practical consequence: an alpha with Sharpe 1.26 and turnover 0.34 needs
returns near 0.28 to reach fitness 1.0. Cutting turnover is usually easier than
raising returns.

---

## Proven patterns

**Mean reversion with group ranking.** Grouping by subindustry strips
sector-level bias so what's left is the stock-specific move.

```
group_rank(-ts_delta(price_field, N), subindustry)
```

The *101 Formulaic Alphas* #4 instance of it:

```
group_rank(-ts_delta(log(close), 1), subindustry)
```

**Liquidity-gated execution.** Trade only when the day's volume clears the
20-day average, cutting market impact. `adv20` is a real field in `pv1` — use it
rather than recomputing `ts_mean(volume, 20)`.

```
trade_when(volume > adv20, alpha_signal, -1)
```

The `-1` is the fallback when the condition is false.

**Fundamental data repair.** Fundamentals report quarterly; between report
dates the field is empty. Backfill carries the last known value forward.

```
ts_backfill(fundamental_field, 60)
```

N = 60 trading days is the norm for quarterly data. Skipping this is the most
common reason a fundamental alpha looks like noise.

**Alternative data.**

| Type | Pattern | Example field |
|---|---|---|
| Social media buzz | `vec_sum(buzz_vector)` | `scl12_alltype_buzzvec` |
| News sentiment | `vec_avg(news_vector)` | `nws12_afterhsz_sl` |
| Analyst estimate revision | `ts_rank(estimate_field / close, N)` | `est_epsr / close` |

All four families are implemented in `wqo/mining/templates.py` as
`group_rank_reversal`, `liquidity_gated`, the `BACKFILL` wrapper, and
`estimate_to_price` / `vector_mean_rank` / `vector_sum_zscore`.

---

## Problem → fix

| Symptom | Fix |
|---|---|
| Low Sharpe | Smooth the signal — moving average or exponential decay |
| Weight concentration | Backfill to remove NaN gaps that distort rankings; also `group_neutralize` or lower truncation |
| High turnover | Raise `decay`; gate execution with `trade_when` |
| Infrequent trading | Lower `decay`; check the field actually updates as often as you assume |
| Self-correlation failure | Change the *datafield*, not the wrapper. Or change neutralization or region |
| Overfitting | Validate out-of-sample; distrust parameters tuned to historical noise |

Note the weight-concentration entry: NaN gaps are a *cause* of concentrated
weight, not just a data-quality nuisance. A field that is NaN for most names on
most days concentrates the whole book into the few names that have data.

---

## Grade

Every alpha record carries a `grade` alongside its `is` statistics — BRAIN's own
one-word verdict, computed server-side and read-only:

```
INFERIOR  <  AVERAGE  <  GOOD  <  EXCELLENT  <  SPECTACULAR
```

It arrives free on `GET /alphas/{id}`, so `wqo sim run`, `wqo mine` and
`wqo gate` all report it without an extra call, and `wqo alpha list --grade
EXCELLENT` filters on it.

It is reported, never acted on. Submission eligibility is decided by the checks
in `is.checks`, not by the grade, and the local thresholds in `wqo/config.py`
are what pre-filter mining output. Treat a high grade as a hint that an alpha is
worth a closer look, not as a substitute for the gate.

---

## Test period

`testPeriod` reserves the tail of the backtest window as out-of-sample, written
as an ISO-8601 duration in years and months — `P1Y0M` for one year, `P0Y0M`
(the default) to keep the whole window in-sample. The CLI accepts `1y`, `6m`,
`1y6m` or the full `P1Y6M` and normalizes them.

Reserving a year shortens the in-sample window the reported Sharpe is measured
over, so IS numbers are not comparable across different test periods. Set it
when you want a held-out check on a specific alpha, not as a default for mining.

---

## Terminology

- **Alpha** — expression producing a ranked signal across a universe, predicting future returns.
- **Neutralization** — removing exposure to systematic factors (market, sector, industry).
- **Turnover** — fraction of the portfolio replaced daily; drives transaction costs.
- **Decay** — smoothing parameter that reduces turnover by weighting recent signals more heavily.
- **Simulation** — backtest on historical data.

BRAIN is a signal-aggregation system: contributors supply predictive signals,
portfolio managers combine thousands of them to trade real capital. That framing
explains the correlation limits — a signal that duplicates an existing one adds
nothing to the aggregate.

---

## Consultant levels

| Level | Points |
|---|---|
| Bronze | 1,000 |
| Silver | 5,000 |
| Gold | 10,000 — eligible for consultant invitation |

## Sources

- *Finding Alphas* (Tulchinsky, ed.) — official WorldQuant methodology guide.
- *101 Formulaic Alphas* — [arXiv:1601.00991](https://arxiv.org/abs/1601.00991). Catalogue of expressions; starting points, not finished strategies.
- BRAIN Learn section — operators, datafields, simulation settings.

## Deliberately not encoded

- **Compensation figures.** The source lists ~$1.50 per accepted alpha, $500–600/month for consistent contributors, up to $1,500/month for top performers, all marked "reported". Unverified and irrelevant to how the tool behaves.
- **Interview preparation questions.** Relevant to a Gold-level consultant application, not to alpha automation.
- **Quantity vs. quality framing.** Background context; the mining loop already implements a middle path — broad generation, then refinement of the shortlist.
