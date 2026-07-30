---
name: wq-simulate
description: Backtest alpha expressions on WorldQuant BRAIN. Use when the user wants to simulate, backtest, or test an alpha expression, run a sweep over settings or datafields, or asks what the Sharpe/fitness/turnover of an expression is.
---

# WorldQuant BRAIN — simulation

## Before running anything

```bash
cd /path/to/worldquant-orchestrator
```

All commands below use `.venv/bin/python -m wqo`. If `.venv` is missing, or you
have not read the hard rules (never submit without explicit confirmation, never
bypass the Persona biometric check, never touch the credentials file), read
[`AGENTS.md`](../../../AGENTS.md) in the repo root first.

Exit codes: `0` ok · `1` error or gate blocked · `2` auth/biometric · `3` budget
exhausted · `4` submission refused.

## One expression

```bash
.venv/bin/python -m wqo sim run --code "-ts_delta(ts_backfill(close, 60), 5)" \
  --region USA --universe TOP3000 --delay 1 \
  --neutralization SUBINDUSTRY --decay 6 --truncation 0.08
```

Returns JSON: `alpha_id`, `url`, `sharpe`, `fitness`, `turnover`, `returns`,
`drawdown`, `margin`, `checks_passed` (e.g. `"6/8"`).

Settings flags all have defaults; only pass what differs. Simulations can take a
few minutes — the command polls on the server's own `Retry-After` cadence and
blocks until done.

## Batches and sweeps

Write a JSON list, then:

```bash
.venv/bin/python -m wqo sim batch --file ideas.json
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
.venv/bin/python -m wqo sim recent --limit 20
```

Shows the local ledger of past runs.

## Writing the expression

Full rules in [`docs/fastexpr.md`](../../../docs/fastexpr.md). The ones that
cost a wasted slot to learn:

- **No scientific notation.** `1e-9` fails with `Unexpected character 'e'`.
  Write `0.000000001`.
- **Backfill sparse fundamentals**: `ts_backfill(field, 60)`. Without it the
  field is NaN most days, which silently concentrates the book into a handful of
  names and surfaces as an unrelated-looking `CONCENTRATED_WEIGHT` failure.
- **Check the operator exists** — `wqo data operators`. This account has 66, not
  the full set, and an unavailable operator fails the simulation.
- **Groups are bare identifiers**: `group_neutralize(rank(x), subindustry)`, not
  a quoted string.
- **`adv20` is a real field** in `pv1`. Use it for liquidity gating instead of
  recomputing `ts_mean(volume, 20)`.

## Interpreting results

- Sign doesn't matter — a Sharpe of −1.8 is a good alpha with a minus sign missing.
- `checks_passed` below the total means BRAIN flagged something; run `wq-analyze`
  or `python -m wqo gate <id>` to see which check.
- A failed simulation returns `"status": "ERROR"` with the message. Syntax and
  unknown-operator errors are in there verbatim — read it before retrying.

## Budget

Daily simulation budget defaults to 300 (`WQO_SIM_BUDGET`). Exit code 3 means it's
exhausted; stop and tell the user rather than raising the cap unilaterally.
