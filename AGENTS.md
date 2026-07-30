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

## Account facts

Current account is `<your account id>`, `level: NONE` — the lowest tier. This shapes
everything:

| Constraint | Consequence |
|---|---|
| ~1 simulation slot | Batches run near-sequentially. 40 candidates is roughly an hour |
| 66 operators available | Not the full set. Check `wqo data operators` before suggesting one |
| `/alphas/{id}/correlations/prod` → 403 | Production correlation detail unreadable; the `MATCHES_COMPETITION` check still runs server-side |
| `/users/self/consultant` → 403 | Consultant surface closed |

Concurrency is learned automatically from 429s and persisted. Do not override it.

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
wq-alphas    →  tag and organize survivors
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
| `wqo/config.py` | All tunables and gate thresholds |

## Tests

```bash
.venv/bin/python -m pytest tests -q
```

Offline — no network, no credentials. Run before committing. If you change gate
thresholds, slot behaviour, or templates, add a regression test; several of the
existing ones encode bugs that shipped once already.
