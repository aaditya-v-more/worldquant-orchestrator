---
name: wq-mine
description: Autonomously search for WorldQuant BRAIN alphas — generate candidate expressions from a dataset's datafields, backtest them in batch, rank the survivors and produce a submit-ready shortlist. Use when the user asks to find, mine, hunt for, or generate new alphas, or to explore a dataset for signal.
---

# WorldQuant BRAIN — alpha mining

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
| `--max-fields` | how many datafields to draw from (highest coverage first) |
| `--budget` | hard cap on simulations this run |
| `--seed` | reproducible candidate sampling |

Expressions already simulated are skipped automatically, so repeated runs explore
new ground instead of re-testing the same ideas.

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

## Discipline

- Mining produces many mediocre alphas and occasionally a good one. Report the
  shortlist honestly, including how many candidates failed.
- Don't chase Sharpe by widening thresholds. If nothing clears the gate, say so.
- Never submit from a mining run. Submission always goes through `wq-submit` with
  the user confirming each alpha.
