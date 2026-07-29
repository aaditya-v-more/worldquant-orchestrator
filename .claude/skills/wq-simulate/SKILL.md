---
name: wq-simulate
description: Backtest alpha expressions on WorldQuant BRAIN. Use when the user wants to simulate, backtest, or test an alpha expression, run a sweep over settings or datafields, or asks what the Sharpe/fitness/turnover of an expression is.
---

# WorldQuant BRAIN — simulation

## One expression

```bash
.venv/bin/python -m wqo sim run --code "-ts_delta(ts_backfill(close, 120), 5)" \
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

## Interpreting results

- Sign doesn't matter — a Sharpe of −1.8 is a good alpha with a minus sign missing.
- `checks_passed` below the total means BRAIN flagged something; run `wq-analyze`
  or `python -m wqo gate <id>` to see which check.
- A failed simulation returns `"status": "ERROR"` with the message. Syntax and
  unknown-operator errors are in there verbatim — read it before retrying.

## Budget

Daily simulation budget defaults to 300 (`WQO_SIM_BUDGET`). Exit code 3 means it's
exhausted; stop and tell the user rather than raising the cap unilaterally.
