# Challenge scoring, quotas, and when they reset

Two different daily limits govern this account and they roll over at
**different times**. Conflating them wastes a submission slot.

| Limit | Value | Rolls over |
|---|---|---|
| Submission quota | 3 alphas/day | midnight US Eastern |
| Simulation quota | 300/day (`WQO_SIM_BUDGET`) | midnight US Eastern |
| Challenge score earned | 2,000 points/day | **03:00 US Eastern** |

Eastern is UTC−04:00 in summer (EDT), UTC−05:00 in winter (EST). Every
timestamp the API returns carries that offset, and `/users/self/activities/*`
buckets its counters on Eastern calendar dates — that is the evidence the
platform runs on this clock, not UTC.

`wqo/store.py` counts local budget usage from `_brain_day_start()`, which is
Eastern midnight. It counted UTC midnight once; that reported a fresh budget
four hours before BRAIN's day actually turned over. `test_offline.py` pins it.

## The 2,000-point daily cap

Score comes from the quantity *and* quality of submitted alphas. It is
recomputed daily, and a single day contributes at most **2,000 points** toward
your Challenge total. Scores refresh at **03:00 Eastern**.

An alpha submitted after 03:00 does not score at that morning's refresh — it
waits for the next one, roughly 24 hours later, and lands in the day bucket it
was submitted into.

Neither the cap nor the refresh time is exposed by any endpoint. They come from
WorldQuant's published Challenge rules, corroborated by observed account
behaviour (below). Do not tell the user the API confirms them.

### Worked example — observed on one account, July 2026

```
KPEQWOzx  submitted 2026-07-29 15:56 ET   ->  scored at the 07-30 03:00 refresh
QP96Mp15  submitted 2026-07-30 03:07 ET   ->  missed it by 7 minutes
```

After the 07-30 refresh: `score: 1950.0`, `alphas: 1`. One alpha, one day,
1,950 of the available 2,000 — and the second submission sat ungraded because
it landed seven minutes on the wrong side of the boundary.

Practical consequence: submitting late in the Eastern day is fine, but
submitting between 00:00 and 03:00 ET is the worst window — it burns a slot
from the new day's quota while still waiting a full cycle to score.

## Level thresholds

Bronze 1,000 · Silver 5,000 · Gold 10,000 points. Consultant invitations are
discussed around 10,000.

The score is cumulative toward level — it is not reset daily. Only the *rate of
accrual* is capped. `wqo account status` reports current score, rank, and
points remaining:

```bash
.venv/bin/python -m wqo account status
```

Read `progress.score.remaining` and `progress.level` from
`/users/self/competitions` for the same numbers unwrapped.

## Checking usage against the server, not the local ledger

The local SQLite ledger only knows about submissions made *through this tool*.
Anything submitted from the website is invisible to it, so it can report a
fresh budget while the server already counted one. The server is authoritative:

```bash
.venv/bin/python -m wqo api GET /users/self/activities/submissions
```

`records.records` is a list of `[eastern_date, count]` pairs. Trust that over
`auth status`'s `submissions_today` whenever the two disagree.

## Sources

- [WorldQuant Challenge rules](https://www.scribd.com/document/870788462/WorldQuant-Challenge-WorldQuant-BRAIN)
- [WorldQuant Challenge overview and rules](https://www.scribd.com/document/820043965/WorldQuant)
- [IQC guidelines](https://www.worldquant.com/brain/iqc-guidelines/)
- Platform FAQ (403s to non-browser fetch; open in a browser):
  <https://support.worldquantbrain.com/hc/en-us/articles/21210168520855>
