# worldquant-orchestrator

End-to-end control of [WorldQuant BRAIN](https://platform.worldquantbrain.com)
from any coding agent: data discovery, alpha generation, backtesting, analysis, and
submission — driven through BRAIN's official REST API rather than the web UI.

Two layers:

- **`wqo/`** — a Python client and CLI. Usable on its own.
- **`.claude/skills/wq-*`** — thin skill wrappers so any agent knows when and how
  to invoke each part. Symlinked for Copilot and Qoder.

## Setup

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Create your credentials file yourself — nothing in this repo will write it:

```bash
printf '{"email": "you@example.com", "password": "..."}' > ~/.brain_credentials.json
chmod 600 ~/.brain_credentials.json
```

Then:

```bash
.venv/bin/python -m wqo auth status
```

### First login on a new account

BRAIN usually requires a Persona biometric check the first time an account
authenticates through the API. The command exits with code 2 and prints a URL.
Open it in a browser, complete the check, then:

```bash
.venv/bin/python -m wqo auth persona
```

This is a human step by design. Nothing here bypasses it.

## Commands

```bash
# account
python -m wqo auth login | status | persona | logout

# data discovery (locally cached for 7 days)
python -m wqo data datasets --region USA --delay 1 --universe TOP3000
python -m wqo data fields --dataset fundamental6 --search revenue
python -m wqo data operators

# backtesting
python -m wqo sim run --code "-ts_delta(ts_backfill(close, 60), 5)"
python -m wqo sim batch --file ideas.json
python -m wqo sim recent

# analysis
python -m wqo alpha get|pnl|yearly <alpha_id>
python -m wqo alpha corr <alpha_id> [--prod]
python -m wqo alpha list --status UNSUBMITTED --min-sharpe 1.25
python -m wqo alpha tag <alpha_id> --name "..." --color GREEN --tags a,b

# submission
python -m wqo gate <alpha_id>              # read-only report
python -m wqo submit <alpha_id>            # report only, refuses to submit
python -m wqo submit <alpha_id> --confirm  # actually submits

# mining
python -m wqo mine --dataset fundamental6 --budget 40 [--dry-run]

# account: competitions, standing, team, learn, notifications
python -m wqo account status                    # rank, score, level progress
python -m wqo account competitions [--mine]
python -m wqo account competition IQC2026S1 [--alphas|--agreement]
python -m wqo account activity                  # counters + referrals
python -m wqo account teams|events|tutorials|messages|agreements
python -m wqo account probe                     # what this level can reach

# anything not wrapped above
python -m wqo api GET /users/self/activities
python -m wqo discover
```

Everything prints JSON. Exit codes: `0` ok, `1` error, `2` auth/biometric,
`3` budget exhausted, `4` submission refused.

## Safety model

Submission is the only irreversible action, and it is deliberately awkward:

- `submit` without `--confirm` cannot submit. It prints the check report and
  exits 4.
- With `--confirm` but a failing gate, it still refuses unless `--force`.
- A local daily submission budget (default 3) is enforced before the request.

Credentials are read directly from disk into HTTP Basic auth. They are never
logged, echoed, or written by this tool.

## Rate limiting

This uses the official API, which is the sanctioned integration path — but it
behaves like a good client rather than hammering the endpoint:

- `Retry-After` is honored exactly, for simulation polling, checks, correlations,
  and 429s. The server sets the cadence.
- Minimum interval plus jitter between all requests.
- Exponential backoff with full jitter on 429/5xx.
- Concurrency is *learned* from the account: it starts at 1 slot, grows only after
  clean runs, and shrinks immediately on a 429. Persisted between runs.
- The session cookie is cached on disk and reused. Re-authenticating on every
  invocation is both slow and the most abnormal traffic pattern a client can
  produce.
- Local daily budgets on simulations and submissions.

Tunable via environment variables — `WQO_MIN_INTERVAL`, `WQO_JITTER`,
`WQO_SIM_BUDGET`, `WQO_SUBMIT_BUDGET`, `WQO_MAX_CONCURRENCY`, and the
`WQO_MIN_SHARPE` / `WQO_MAX_TURNOVER` style gate thresholds. See `wqo/config.py`.

## Editor support

The eight skills live in `.claude/skills/` and are symlinked so other agents pick
up the same files — edit once, every tool sees it:

```
.github/skills -> ../.claude/skills   # GitHub Copilot (VS Code, CLI, cloud agent)
.qoder/skills  -> ../.claude/skills   # Qoder
```

Both use the same `SKILL.md` + YAML frontmatter format, so no conversion is
needed. Copilot also reads `.claude/skills` directly; the `.github/skills` link
is there so the intent is explicit and the CLI and cloud agent resolve it too.

These are relative symlinks and survive a clone on macOS and Linux. On Windows,
git needs `core.symlinks=true` and Developer Mode, otherwise they land as plain
text files — copy the directories instead if that comes up.

## Reference

**Agents start here:** [`AGENTS.md`](AGENTS.md) — setup, hard rules, account
constraints, workflow, exit codes. `CLAUDE.md` is a symlink to it, so Claude
Code, Copilot, Cursor, Qoder and OpenCode all read one source of truth.

[`docs/fastexpr.md`](docs/fastexpr.md) — FASTEXPR syntax constraints, the
operator set actually available at this account level, and the `pv1` field list.

[`docs/alpha-research.md`](docs/alpha-research.md) — passing criteria, the fitness
formula, proven expression patterns, and a symptom → fix table. Distilled from
*Quantitative Alpha Research: WorldQuant BRAIN* (the source PDF is in the repo
root). The gate thresholds and mining templates are derived from it; where it
conflicts with BRAIN's own `/check`, BRAIN wins.

[`docs/api-map.md`](docs/api-map.md) — every website tab mapped to its endpoint,
plus what is *not* available. Notably there is no leaderboard endpoint and
`GET /alphas` is 405: you can read your own rank, never other people's alphas.

[`docs/scoring.md`](docs/scoring.md) — how Challenge points are earned, the
2,000-point daily cap, level thresholds, and the two different reset times.
BRAIN runs on US Eastern: quotas roll at midnight, scores refresh at 03:00.

[`docs/parallel-agents.md`](docs/parallel-agents.md) — several agents share one
account, so they share one simulation slot queue in `data/wqo.sqlite`. Check it
with `wqo auth slots` before assuming a stalled batch is broken.

## Layout

```
docs/
  alpha-research.md   distilled research reference
  api-map.md          tab -> endpoint map, and what is unavailable
  fastexpr.md         expression syntax and operator availability
  scoring.md          points, daily caps, reset times, level thresholds
  parallel-agents.md  shared slot queue for several agents on one account
wqo/
  endpoints.py    API URLs
  config.py       paths, pacing, budgets, gate thresholds
  session.py      authenticated session, cookie persistence, Persona handoff
  pacing.py       interval throttle, Retry-After, backoff
  store.py        SQLite ledger (audit trail + budget accounting)
  catalog.py      datasets / datafields / operators, cached
  simulate.py     submit, poll, normalize; adaptive slot manager
  alphas.py       records, PnL, yearly stats, correlations, properties
  gate.py         local thresholds + BRAIN checks -> PASS/FAIL report
  submit.py       confirmation-gated submission
  mining/         templates, candidate generation, ranking
  account.py      competitions, standing, team, learn, notifications
  __main__.py     CLI
```

## Tests

```bash
.venv/bin/python -m pytest tests -q
```

Offline only — no network, no credentials. Covers backoff and `Retry-After`
parsing, ledger and budget accounting, gate threshold logic, correlation
parsing, slot adaptation, template expansion, and ranking.
