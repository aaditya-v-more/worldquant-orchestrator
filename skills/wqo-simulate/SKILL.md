---
name: wqo-simulate
description: Backtest alpha expressions and settings sweeps on WorldQuant BRAIN with WQO. Use for simulation requests, cached results and interpretation of backtest metrics.
---

# WorldQuant BRAIN — simulation

## Setup

Read [setup and operational boundaries](references/runtime.md) before running
commands. Use the bundled `scripts/wqo.sh` runner for every `wqo` command below;
it installs the CLI locally when missing. This skill works without other skills
or a source checkout.

## One expression

```bash
wqo sim run --code "-ts_delta(ts_backfill(close, 60), 5)" \
  --region USA --universe TOP3000 --delay 1 \
  --neutralization SUBINDUSTRY --decay 6 --truncation 0.08
```

Returns JSON: `alpha_id`, `url`, `sharpe`, `fitness`, `turnover`, `returns`,
`drawdown`, `margin`, `grade`, `checks_passed` (e.g. `"6/8"`).

`grade` is BRAIN's own verdict — `INFERIOR`, `AVERAGE`, `GOOD`, `EXCELLENT`,
`SPECTACULAR` — computed server-side. It is a hint about where to spend
attention, not an eligibility signal: `checks_passed` and `wqo-analyze` decide
what can actually be submitted.

Settings flags all have defaults; only pass what differs. Simulations can take a
few minutes — the command polls on the server's own `Retry-After` cadence and
blocks until done.

## Out-of-sample tail

`--test-period` holds back the end of the backtest window:

```bash
wqo sim run --code "rank(close)" --test-period 1y
```

Accepts `1y`, `6m`, `1y6m` or the ISO form `P1Y6M`. Default is none — the whole
window is in-sample. Reserving a tail shortens the window the reported Sharpe is
measured over, so numbers from different test periods are not comparable. Use it
to sanity-check one promising alpha, not as a standing default.

## Batches and sweeps

Write a JSON list, then:

```bash
wqo sim batch --file ideas.json
```

```json
[
  {"code": "rank(close)", "label": "baseline"},
  {"code": "zscore(volume)", "label": "vol", "settings": {"neutralization": "MARKET"}}
]
```

Plain strings work too. Per-entry `settings` merge over the command-line defaults,
so a settings sweep is the same expression repeated with different `settings`.

Concurrency is learned from the account, not assumed. A new account starts at 1
slot and the tool raises it only after clean runs. Don't try to force it higher.

## Caching

Identical code + identical settings is not re-simulated; the prior result is
returned with `"cached": true`. Pass `--no-cache` to force a re-run.

```bash
wqo sim recent --limit 20
```

Shows the local ledger of past runs.

## Writing the expression

Full rules in [expression notes](references/fastexpr.md). The ones that
cost a wasted slot to learn:

- **No scientific notation.** `1e-9` fails with `Unexpected character 'e'`.
  Write `0.000000001`.
- **Backfill sparse fundamentals**: `ts_backfill(field, 60)`. Without it the
  field is NaN most days, which silently concentrates the book into a handful of
  names and surfaces as an unrelated-looking `CONCENTRATED_WEIGHT` failure.
- **Check the operator exists** — `wqo data operators`. Availability depends on the account; an unavailable operator fails the simulation.
- **Groups are bare identifiers**: `group_neutralize(rank(x), subindustry)`, not
  a quoted string.
- **`adv20` is a real field** in `pv1`. Use it for liquidity gating instead of
  recomputing `ts_mean(volume, 20)`.

## Interpreting results

- A negative Sharpe may motivate testing a sign-reversed expression; re-simulate and re-check eligibility rather than assuming it is good.
- `checks_passed` below the total means BRAIN flagged something; run `wqo-analyze`
  or `wqo gate <id>` to see which check.
- A failed simulation returns `"status": "ERROR"` with the message. Review the status and sanitized diagnostic before considering another simulation.

## Budget

Daily simulation budget defaults to 300 (`WQO_SIM_BUDGET`). Exit code 3 means it's
exhausted; stop and tell the user rather than raising the cap unilaterally.

Companion skill names above are optional guidance. If none are installed, use
the equivalent `wqo` command through this skill's bundled runner.
