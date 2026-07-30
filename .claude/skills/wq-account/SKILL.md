---
name: wq-account
description: Read WorldQuant BRAIN account-level information — competition standing and rank, level progress toward Bronze/Silver/Gold, competitions and IQC stages, teams, referrals, webinar events, the Learn tab tutorials, and platform messages. Use when the user asks about their rank, score, points, level, competitions, team, referrals, events, or what parts of the platform their account can reach.
---

# WorldQuant BRAIN — account, competitions, standing

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

## Your standing

```bash
.venv/bin/python -m wqo account status
```

Returns rank, score, alphas counted, current level, and points remaining to the
next level, per competition you have joined.

Level thresholds: Bronze 1,000 · Silver 5,000 · Gold 10,000 points.

## Competitions

```bash
.venv/bin/python -m wqo account competitions --mine   # ones you joined
.venv/bin/python -m wqo account competitions          # all (279)
.venv/bin/python -m wqo account competition IQC2026S1
.venv/bin/python -m wqo account competition challenge --alphas
```

`status: EXCLUDED` means the account is not eligible — usually sign-up closed or
a region/university restriction, not an error.

## Everything else

```bash
.venv/bin/python -m wqo account activity     # simulation/submission counts + referrals
.venv/bin/python -m wqo account teams
.venv/bin/python -m wqo account events       # webinars
.venv/bin/python -m wqo account tutorials    # the Learn tab
.venv/bin/python -m wqo account messages
.venv/bin/python -m wqo account agreements
.venv/bin/python -m wqo account probe        # what this account level can reach
```

`account activity` is the Refer a friend tab plus period-bucketed simulation and
submission counters (yesterday, month to date, previous month, year to date).

## There is no leaderboard of other people's alphas

If asked for "top performing alphas" or "what are the best alphas on the
platform", the answer is that BRAIN does not expose this. Every leaderboard
path 404s and `GET /alphas` returns 405 — alphas can only be listed for
yourself. This is deliberate: alphas are contributor IP.

What exists is *your own* rank within a competition, which `account status`
reports. Don't imply more is available, and don't try to scrape it.

Full probe results and the tab-to-endpoint map: `docs/api-map.md`.

## When an endpoint 403s

`/users/self/consultant` and `/alphas/{id}/correlations/prod` are gated by
account level. Report that plainly rather than treating it as a bug. Re-run
`account probe` after a level change to see what has opened up.
