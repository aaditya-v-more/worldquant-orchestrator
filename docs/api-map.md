# API reachability map

Every website tab probed against the API from account `<your account id>` (`level: NONE`),
2026-07-30. Re-run the probe yourself with:

```bash
.venv/bin/python -m wqo account probe
```

## Tab → endpoint

| Tab | Endpoint | Status | Wrapped by |
|---|---|---|---|
| Simulate | `POST /simulations` | 201 | `wqo sim` |
| Alphas | `GET /users/self/alphas`, `/alphas/{id}` | 200 | `wqo alpha` |
| Learn | `GET /tutorials` | 200 (5 courses) | `wqo account tutorials` |
| Data | `/data-sets`, `/data-fields`, `/operators` | 200 | `wqo data` |
| Competitions | `/competitions` (279), `/users/self/competitions` | 200 | `wqo account competitions` |
| Team | `/users/self/teams` | 200 (0 teams) | `wqo account teams` |
| IQC 2026 | `/competitions` → `IQC2026S1/S2/S3` | 200, all `EXCLUDED` | `wqo account competitions` |
| Refer a friend | `/users/self/activities/referrals` | 200 (0) | `wqo account activity` |
| Consultant program | `/users/self/consultant` | **403** | — level-gated |
| Community | — | **no API** | — separate forum system |

Also reachable: `/events` (11 webinars), `/users/self/messages`,
`/users/self/agreements`, `/users/self/activities`.

## What an alpha record contains

`GET /alphas/{id}` returns everything in one call — no follow-up request is
needed for the fields below:

| Field | Notes |
|---|---|
| `settings` | the full settings panel, plus `startDate` / `endDate` |
| `regular.code` | the expression, with `description` and `operatorCount` |
| `is` | `sharpe`, `fitness`, `turnover`, `returns`, `drawdown`, `margin`, `pnl`, `bookSize`, `longCount`, `shortCount` |
| `is.checks` | the same array `/alphas/{id}/check` returns, already resolved |
| `grade` | `INFERIOR` / `AVERAGE` / `GOOD` / `EXCELLENT` / `SPECTACULAR` |
| `stage`, `status` | `IS` / `OS`, `UNSUBMITTED` / `ACTIVE` |
| `classifications` | e.g. `DATA_USAGE:SINGLE_DATA_SET` |
| `name`, `tags`, `color`, `category`, `favorite`, `hidden` | the editable properties |

`grade` and `classifications` are computed server-side and read-only — `PATCH`
only accepts the editable properties in the last row.

The `settings` block echoes `startDate` / `endDate` rather than the `testPeriod`
that produced them; `testPeriod` is a request-side field only.

## There is no leaderboard endpoint

All of these 404:

```
/leaderboards          /leaderboard           /rankings
/users/leaderboard     /users/self/leaderboard
/competitions/{id}/leaderboard                /competitions/{id}/ranking
/users/self/rank       /users/self/points     /users/self/statistics
```

And `GET /alphas` returns **405 Method Not Allowed** — alphas cannot be
enumerated globally, only your own via `/users/self/alphas`.

This is by design, not a permissions gap. Alphas are contributor IP and the
platform's product; exposing other users' expressions would defeat the model.

**What you can see is your own standing**, nested as a `leaderboard` object
inside each of *your* competition records:

```json
{ "rank": 246107, "user": "<your account id>", "score": 0.0, "alphas": 0,
  "level": null, "university": "<your university>", "country": "IN" }
```

Your position among everyone — never who is above you or what they wrote.
`wqo account status` reads this.

## Other 404s (probed, not available)

```
/consultant   /referrals   /learn      /documentation   /glossary
/forum        /posts       /community  /news            /announcements
/pyramids     /users/self/pyramids     /users/self/settings   /messages
/datasets     /support     /alphas/{id}/competitions
```

`/teams`, `/agreements`, `/alphas`, `/simulations` exist but reject bare `GET`
with 405 — they are collection endpoints with other verbs, or require the
`/users/self/` prefix.

## Level-gated (403 today, may open later)

| Endpoint | Note |
|---|---|
| `/users/self/consultant` | consultant programme surface |
| `/alphas/{id}/correlations/prod` | production correlation detail |

The `MATCHES_COMPETITION` check still runs server-side and appears in the gate
report even though the detail endpoint is closed, so the pass/fail is real —
you just cannot read the breakdown. Re-run `wqo account probe` after a level
change to see what opened up.
