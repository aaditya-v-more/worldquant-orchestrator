---
name: wq-analyze
description: Analyze a WorldQuant BRAIN alpha's performance — IS statistics, PnL series, yearly breakdown, self and production correlation, and the full pre-submission check report. Use when the user asks how an alpha performed, why it failed a check, whether it is correlated with existing alphas, or whether it is ready to submit.
---

# WorldQuant BRAIN — alpha analysis

## Full pre-submission report

```bash
.venv/bin/python -m wqo gate <alpha_id>
```

This is the one command that answers "is this submittable?". It is **read-only** —
it never submits. It runs BRAIN's own `/check` endpoint plus local thresholds and
prints a per-criterion PASS/FAIL table. Exit code 0 means clean, 1 means blocked.

Add `--json` for structured output, `--no-correlations` to skip the (slow)
correlation calls.

## Individual pieces

```bash
.venv/bin/python -m wqo alpha get <alpha_id>            # full record
.venv/bin/python -m wqo alpha pnl <alpha_id>            # PnL series
.venv/bin/python -m wqo alpha yearly <alpha_id>         # per-year stats
.venv/bin/python -m wqo alpha corr <alpha_id>           # vs. your own alphas
.venv/bin/python -m wqo alpha corr <alpha_id> --prod    # vs. production alphas
```

Correlation output includes a `max` field — that's the number the gate compares
against the 0.70 limit.

## What the checks mean

| Check | Reading |
|---|---|
| `LOW_SHARPE` | IS Sharpe under the required minimum |
| `LOW_FITNESS` | fitness under minimum; usually turnover-driven |
| `LOW_TURNOVER` / `HIGH_TURNOVER` | outside the acceptable trading band |
| `CONCENTRATED_WEIGHT` | too much book in too few names — add neutralization or truncate harder |
| `LOW_SUB_UNIVERSE_SHARPE` | works on large caps only; doesn't generalize |
| `SELF_CORRELATION` | too close to an alpha you already submitted |
| `MATCHES_COMPETITION` | too close to a production alpha |
| `UNITS` / `IS_LADDER_SHARPE` | unit mismatch or unstable across sub-periods |

## Passing criteria (delay 1)

| Metric | Requirement |
|---|---|
| Sharpe | > 1.25 |
| Fitness | > 1.0 |
| Turnover | 1% – 70% |
| Drawdown | < 10% |
| Weight concentration | < 10% |
| Self-correlation | < 0.7, **or** Sharpe >10% better than the alpha it correlates with |

## Why fitness fails when Sharpe passes

```
Fitness = Sharpe × sqrt( |Returns| / max(Turnover, 0.125) )
```

Fitness is Sharpe discounted by turnover. Sharpe 1.26 at turnover 0.34 needs
returns near 0.28 to reach fitness 1.0 — cutting turnover is almost always
easier than lifting returns.

## Fixing common failures

- **Low fitness** → raise `--decay` or wrap in `ts_decay_linear(..., n)`. Turnover
  is the lever.
- **Concentrated weight** → first check for NaN gaps: a field that is empty for
  most names concentrates the whole book into the few that have data. Wrap
  fundamentals in `ts_backfill(field, 60)`. Then `group_neutralize(..., subindustry)`
  or lower `--truncation`.
- **High turnover** → raise `--decay`; gate execution with
  `trade_when(volume > adv20, signal, -1)`.
- **Infrequent trading** → lower `--decay`; confirm the field updates as often as
  you assumed.
- **Low sub-universe Sharpe** → re-simulate on TOP1000 to see whether the signal
  is genuinely large-cap-only.
- **Self correlation** → change the *datafield*, not the wrapper. Changing
  neutralization or region also works; changing the operator around the same
  field usually does not.
- **Low Sharpe** → smooth the signal (moving average or decay).

Re-simulate after each change with `wq-simulate` and re-run the gate.

Deeper reference, including proven expression patterns: `docs/alpha-research.md`.
