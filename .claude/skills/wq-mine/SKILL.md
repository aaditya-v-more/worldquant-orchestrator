---
name: wq-mine
description: Autonomously search for WorldQuant BRAIN alphas — generate candidate expressions from a dataset's datafields, backtest them in batch, rank the survivors and produce a submit-ready shortlist. Use when the user asks to find, mine, hunt for, or generate new alphas, or to explore a dataset for signal.
---

# WorldQuant BRAIN — alpha mining

## Before running anything

```bash
cd /path/to/worldquant-orchestrator   # the repo root
```

All commands below use `.venv/bin/python -m wqo`. If `.venv` is missing, or you
have not read the hard rules (never submit without explicit confirmation, never
bypass the Persona biometric check, never touch the credentials file), read
[`AGENTS.md`](../../../AGENTS.md) in the repo root first.

Exit codes: `0` ok · `1` error or gate blocked · `2` auth/biometric · `3` budget
exhausted · `4` submission refused.

One pass = generate candidates → backtest → rank → shortlist. It never submits.

## Run

```bash
# see what would be tested, without spending any simulations
.venv/bin/python -m wqo mine --dataset fundamental6 --budget 40 --dry-run

# actually run it
.venv/bin/python -m wqo mine --dataset fundamental6 --region USA --delay 1 \
  --universe TOP3000 --budget 40 --shortlist 10 -v
```

Key flags:

| Flag | Meaning |
|---|---|
| `--dataset` | restrict to one dataset (find IDs with `wq-data`) |
| `--search` | restrict to datafields matching text |
| `--templates` | comma-separated template names |
| `--neutralizations` | sweep neutralizations, e.g. `SUBINDUSTRY,MARKET` |
| `--decay` `--truncation` | pin one knob; unset means the template decides |
| `--test-period` | out-of-sample tail, e.g. `1y`. Default none |
| `--max-fields` | how many datafields to draw from (highest coverage first) |
| `--budget` | hard cap on simulations this run |
| `--seed` | reproducible candidate sampling |

Expressions already simulated are skipped automatically, so repeated runs explore
new ground instead of re-testing the same ideas.

## Settings come from the template, not from you

Each template declares a regime — momentum, reversion, value, balanced — and
`config.REGIMES` supplies its neutralization, decay and truncation. Left alone,
every expression runs once under its own regime, so one candidate costs exactly
one simulation slot.

Passing `--neutralizations` turns that into a sweep: every expression is
simulated under every neutralization listed. Since `--budget` caps the job list,
an N-way sweep divides the number of *distinct* expressions actually tested by
N. On a one-slot account that trades search breadth for redundancy — sweep when
refining a known-good idea, not when hunting for one.

`--decay` and `--truncation` pin a single knob and leave the rest of each
template's regime intact.

## Workflow

1. **Pick a hunting ground.** Use `wq-data` to find a dataset with a decent
   `valueScore` and low `alphaCount` — less crowded means lower self-correlation.
2. **Dry-run first** and show the user the candidate list, especially on a fresh
   account where every simulation is slow.
3. **Run within budget.** Start small (20–40). A new account has one simulation
   slot; 40 candidates is genuinely an hour of wall clock.
4. **Read the shortlist.** Each entry has `score`, the IS stats, and `notes`
   explaining what held it back.
5. **Deepen the winners.** Take the top 2–3 and iterate manually with
   `wq-simulate`: sweep decay, truncation, neutralization around them. Refining a
   good idea beats generating more random ones.
6. **Gate them** with `wq-analyze`, then hand to `wq-submit` — which will ask the
   user before anything is submitted.

## Templates

Built-in families: cross-sectional rank/zscore, time-series reversal and momentum,
mean-reversion ratios, volatility-scaled changes, group-neutral variants, decayed
ranks, winsorized zscores, liquidity-gated signals, correlation-with-returns,
analyst-estimate-to-price, and vector-field aggregations. See
`wqo/mining/templates.py`.

Four of these are the documented reference patterns (`docs/alpha-research.md`):

| Template | Pattern |
|---|---|
| `group_rank_reversal` | `group_rank(-ts_delta(field, N), subindustry)` |
| `liquidity_gated` | `trade_when(volume > adv20, rank(field), -1)` |
| every fundamental template | wrapped in `ts_backfill(field, 60)` |
| `estimate_to_price` | `ts_rank(field / close, N)` |

Templates whose operators the account doesn't have are dropped before simulating,
so no slot is wasted discovering an operator is unavailable.

To add a family, append a `Template` to `TEMPLATES` in that file — declare its
`operators` so the availability filter works.

## Known trap: trivial price reversal

A mining run will surface `rank(-returns)` and `-returns` style expressions near
the top on raw Sharpe (1.4–1.7 observed). They are textbook one-day reversal,
almost certainly already in production, and will die on `MATCHES_COMPETITION`.

Treat a high-Sharpe candidate built only from `close`, `returns`, or `volume`
with suspicion. Gate it before getting excited, and prefer the
`group_rank_reversal` family on a real datafield even when its Sharpe is lower —
those are the ones with a chance of clearing correlation.

## Discipline

- Mining produces many mediocre alphas and occasionally a good one. Report the
  shortlist honestly, including how many candidates failed.
- Don't chase Sharpe by widening thresholds. If nothing clears the gate, say so.
- Never submit from a mining run. Submission always goes through `wq-submit` with
  the user confirming each alpha.
