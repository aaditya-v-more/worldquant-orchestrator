# AGENTS.md

Contract for any agent working in this repo. Read this before running anything.

This repo drives [WorldQuant BRAIN](https://platform.worldquantbrain.com) through
its official REST API: data discovery, alpha generation, backtesting, analysis,
and submission. Everything the website does is reachable from here.

---

## Run commands like this

Always from the repo root, always through the venv:

```bash
cd /path/to/worldquant-orchestrator
.venv/bin/python -m wqo <command>
```

If `.venv` does not exist:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

System Python is 3.9 and will not run this code — it uses `X | None` annotations
and modern generics.

Every command prints JSON to stdout. `gate` and `submit` also render a table
unless `--json` is passed.

---

## Hard rules

**1. Never submit an alpha without the user's explicit yes, in this
conversation, for that specific alpha.**

Submission is irreversible, consumes a daily quota of 3, and permanently affects
future self-correlation. `wqo submit <id>` without `--confirm` is safe — it only
prints the check report and exits 4. Adding `--confirm` is the live action.
Approval for one alpha is never approval for the next.

**2. Never bypass the Persona biometric check.** If auth returns exit code 2
with an inquiry URL, hand the URL to the user and wait. Then run
`wqo auth persona`. Do not attempt to automate or work around it.

**3. Never write, read back, echo, or log `~/.brain_credentials.json`.** The
user creates it themselves. If it is missing, tell them the format and let them
write it.

**4. Do not raise budgets or force concurrency to work around a limit.**
`WQO_SIM_BUDGET`, `WQO_SUBMIT_BUDGET`, and `WQO_MAX_CONCURRENCY` exist, but
hitting a cap is information, not an obstacle. Report it and stop.

**5. Report results honestly.** Mining produces mostly mediocre alphas. Say how
many failed. If nothing clears the gate, say so rather than widening thresholds.

---

## Account facts live in `ACCOUNT.local.md`, not here

Several people work in this repo on different BRAIN accounts. Level, score,
slot count, operator count and which endpoints 403 all differ per user and
change without warning, so **this file asserts none of them**. Read the
gitignored snapshot instead:

```bash
.venv/bin/python -m wqo account snapshot   # regenerate, then read ACCOUNT.local.md
```

If `ACCOUNT.local.md` is missing or older than a few days, regenerate it before
planning work. Never commit it and never copy its numbers into a tracked file.

What is true for every account here:

| Constraint | Consequence |
|---|---|
| Few simulation slots | Batches run near-sequentially. Check the snapshot for the learned count |
| Partial operator set | Not every documented operator exists. Check `wqo data operators` before suggesting one |
| Some endpoints 403 | Level gates, not bugs. The snapshot lists which ones today |

Concurrency is learned automatically from 429s and persisted. Do not override it.

### You are probably not the only agent running

BRAIN counts slots and budgets per *account*, so several agents in this repo
share one waiting line, held in `data/wqo.sqlite`. `SlotManager` takes a ticket
and blocks until granted; grants go in ticket order and dead holders are reaped
after 180 s.

```bash
.venv/bin/python -m wqo auth slots     # who holds a slot, who is queued
```

A batch that seems stalled is usually waiting behind another agent, not broken.
Check the queue before diagnosing anything else, and never work around it by
raising `WQO_MAX_CONCURRENCY`. Details in `docs/parallel-agents.md`.

### Daily limits roll at two different times

BRAIN runs on US Eastern (UTC−4 summer / −5 winter), not UTC or local time.

- **Submissions (3/day) and simulations (300/day)** roll at **midnight Eastern**.
- **Challenge score (max 2,000 points/day)** refreshes at **03:00 Eastern**.

An alpha submitted between 00:00 and 03:00 Eastern spends a slot from the new
day's quota and still waits a full cycle to score. Full detail, worked example,
and sources in `docs/scoring.md`.

The local ledger only sees submissions made through this tool. When it and
`/users/self/activities/submissions` disagree, the server is right.

---

## Writing FASTEXPR expressions

Gotchas that cost real simulations to discover — see `docs/fastexpr.md`:

- **No scientific notation.** `1e-9` fails with `Unexpected character 'e'`. Write
  `0.000000001`.
- **Backfill sparse fundamentals.** `ts_backfill(field, 60)` or the field is NaN
  most days, which silently concentrates the whole book into a few names.
- **`adv20` is a real field** in the `pv1` dataset. Use it for liquidity gating
  rather than recomputing `ts_mean(volume, 20)`.
- **Group names** are `subindustry`, `industry`, `sector`, `market`.
- Sign is irrelevant — Sharpe −1.8 is a good alpha with a minus sign missing.

---

## Workflow

```
wq-auth      →  confirm session, quotas, level
wq-data      →  find datasets and datafields
wq-mine      →  generate + backtest candidates       (or wq-simulate for one)
wq-analyze   →  gate report, diagnose failures
wq-alphas    →  label survivors (`alpha label`), tag and organize
wq-submit    →  report, ask the user, then submit
wq-account   →  rank, competitions, events, standing
```

Skills live in `.claude/skills/`, symlinked to `.github/skills` (Copilot) and
`.qoder/skills` (Qoder). Same files, one source of truth — edit once.

---

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | success | continue |
| 1 | generic error, or gate blocked | read stderr; a blocked gate is a normal result |
| 2 | auth required / biometric pending | follow the Persona flow, do not retry blindly |
| 3 | daily budget exhausted | stop and tell the user |
| 4 | submission refused | expected without `--confirm` |

---

## What is not available

There is **no leaderboard endpoint**. `/leaderboards`, `/rankings`,
`/competitions/{id}/leaderboard` all 404, and `GET /alphas` returns 405. You can
read your own rank via `wqo account status`, never other users' alphas. This is
deliberate — alphas are contributor IP.

Do not re-probe these. Full map in `docs/api-map.md`.

Anything not wrapped by a command is still reachable:

```bash
.venv/bin/python -m wqo api GET /users/self/activities
```

---

## Reference

| File | Contents |
|---|---|
| `docs/alpha-research.md` | Passing criteria, fitness formula, proven patterns, symptom → fix |
| `docs/api-map.md` | Every tab mapped to its endpoint; what 404s and 403s |
| `docs/fastexpr.md` | Expression syntax constraints and operator availability |
| `docs/scoring.md` | Challenge scoring, the 2,000/day cap, quota reset times, level thresholds |
| `docs/parallel-agents.md` | Shared slot queue, what is and is not coordinated between agents |
| `ACCOUNT.local.md` | **Gitignored.** This user's level, slots, standing, 403s. `wqo account snapshot` |
| `wqo/config.py` | All tunables and gate thresholds |

## Tests

```bash
.venv/bin/python -m pytest tests -q
```

Offline — no network, no credentials. Run before committing. If you change gate
thresholds, slot behaviour, or templates, add a regression test; several of the
existing ones encode bugs that shipped once already.
