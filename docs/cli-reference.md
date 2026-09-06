# CLI reference

The WQO skills run these commands for you. For direct CLI or library use, see
[installation and upgrades](installation.md). For agent setup, start with
[the README](../README.md#-quick-start).

## 🛠 Commands

Everything prints JSON to stdout. `gate` and `submit` also render a table unless
`--json` is passed. The reference below uses `|` for alternatives, `[]` for
optional arguments and `<alpha_id>` for your identifier; these are notation,
not shell pipelines. Use `wqo <command> --help` for copyable argument syntax.

```text
# ── account ─────────────────────────────────────────────────────────
wqo auth login | status | persona | logout

# ── data discovery (locally cached for 7 days) ──────────────────────
wqo data datasets --region USA --delay 1 --universe TOP3000
wqo data fields --dataset fundamental6 --search revenue
wqo data operators

# ── backtesting ─────────────────────────────────────────────────────
wqo sim run --code "-ts_delta(ts_backfill(close, 60), 5)"
wqo sim run --code "rank(close)" --neutralization NONE --test-period 1y
wqo sim batch --file ideas.json
wqo sim recent

# ── analysis ────────────────────────────────────────────────────────
wqo alpha get|pnl|yearly <alpha_id>
wqo alpha corr <alpha_id> [--prod]
wqo alpha list --status UNSUBMITTED --min-sharpe 1.25
wqo alpha list --grade EXCELLENT
wqo alpha tag <alpha_id> --name "..." --color GREEN --tags a,b

# ── submission ──────────────────────────────────────────────────────
wqo gate <alpha_id>              # read-only report
wqo submit <alpha_id>            # report only, refuses to submit
wqo submit <alpha_id> --confirm  # actually submits

# ── mining ──────────────────────────────────────────────────────────
wqo mine --dataset fundamental6 --budget 40 [--dry-run]

# ── competitions, standing, team, learn, notifications ──────────────
wqo account status                    # rank, score, level progress
wqo account competitions [--mine]
wqo account competition IQC2026S1 [--alphas|--agreement]
wqo account activity                  # counters + referrals
wqo account teams|events|tutorials|messages|agreements
wqo account probe                     # what this level can reach

# ── anything not wrapped above ──────────────────────────────────────
wqo api GET /users/self/activities
wqo discover
```

WQO 0.1.1+ also provides `wqo account snapshot` to write dated, private
`ACCOUNT.local.md` notes in the current directory. Existing notes are preserved;
use `--overwrite` to refresh. See [the changelog](../CHANGELOG.md).

<table>
<tr>
<th align="left">Exit code</th><th align="left">Meaning</th>
</tr>
<tr><td><code>0</code></td><td>success</td></tr>
<tr><td><code>1</code></td><td>generic error, or gate blocked</td></tr>
<tr><td><code>2</code></td><td>auth required / biometric pending</td></tr>
<tr><td><code>3</code></td><td>daily budget exhausted</td></tr>
<tr><td><code>4</code></td><td>submission refused</td></tr>
</table>

---

## ⚙️ Simulation settings

Every field the web UI's settings panel exposes is a flag on `sim run`,
`sim batch` and `mine`, defaulting to `DEFAULT_SETTINGS` in
[`wqo/config.py`](../wqo/config.py):

| UI field | Flag | Default |
|---|---|---|
| Language | *fixed* — `FASTEXPR` | |
| Instrument Type | `--instrument-type` | `EQUITY` |
| Region | `--region` | `USA` |
| Universe | `--universe` | `TOP3000` |
| Delay | `--delay` | `1` |
| Neutralization | `--neutralization` | `SUBINDUSTRY` |
| Decay | `--decay` | `6` |
| Truncation | `--truncation` | `0.08` |
| Pasteurization | `--pasteurization` | `ON` |
| Unit Handling | `--unit-handling` | `VERIFY` |
| Nan Handling | `--nan-handling` | `OFF` |
| Test period | `--test-period` | none (`P0Y0M`) |

`--test-period` takes `1y`, `6m`, `1y6m` or the ISO form `P1Y6M`; anything else
is rejected rather than silently backtesting over the wrong window.

> [!NOTE]
> On `mine`, `--decay` and `--truncation` are unset by default so each template
> runs under the regime it declares (`config.REGIMES`). Pass them to pin one
> knob, or `--neutralizations` to sweep — a sweep multiplies jobs without adding
> expressions, and `--budget` caps the total.

---

## 🏅 Alpha grade

Alpha records carry a `grade` BRAIN computes itself:

<div align="center">

![INFERIOR](https://img.shields.io/badge/INFERIOR-6B7280?style=flat-square) ▸
![AVERAGE](https://img.shields.io/badge/AVERAGE-5B8DEF?style=flat-square) ▸
![GOOD](https://img.shields.io/badge/GOOD-22D3EE?style=flat-square) ▸
![EXCELLENT](https://img.shields.io/badge/EXCELLENT-34D399?style=flat-square) ▸
![SPECTACULAR](https://img.shields.io/badge/SPECTACULAR-A78BFA?style=flat-square)

</div>

It comes free on the record, so `sim run`, `mine` and `gate` all report it, and
`alpha list --grade EXCELLENT` filters on it. It is read-only and purely
informational — `is.checks` plus the local thresholds are what decide whether an
alpha may be submitted.

---

## 📡 Rate limiting

WQO paces requests to BRAIN's API using these controls:

- **`Retry-After` governs read retries and polling**, including simulation progress,
  checks and correlations. A throttled write stops without an automatic replay.
- Minimum interval plus jitter between all requests.
- Exponential backoff with full jitter on read requests receiving 429/5xx.
- **Concurrency is *learned* from the account:** it starts at 1 slot, grows only
  after clean runs, and shrinks immediately on a 429. Persisted between runs.
- The session cookie is cached on disk and reused. Re-authenticating on every
  invocation is both slow and the most abnormal traffic pattern a client can
  produce.
- Local daily budgets on simulations and submissions.

Tunable via environment variables — `WQO_MIN_INTERVAL`, `WQO_JITTER`,
`WQO_SIM_BUDGET`, `WQO_SUBMIT_BUDGET`, `WQO_MAX_CONCURRENCY`, and the
`WQO_MIN_SHARPE` / `WQO_MAX_TURNOVER` style gate thresholds. See
[`wqo/config.py`](../wqo/config.py).
