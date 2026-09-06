---
name: wqo-account
description: Read WorldQuant BRAIN standings, competitions, teams, events and account activity with WQO. Use for account-level questions beyond authentication.
---

# WorldQuant BRAIN — account, competitions, standing

## Setup

Read [setup and operational boundaries](references/runtime.md) before running
commands. Use the bundled `scripts/wqo.sh` runner for every `wqo` command below;
it installs the CLI locally when missing. This skill works without other skills
or a source checkout.

## Your standing

```bash
wqo account status
```

Returns rank, score, alphas counted, current level, and points remaining to the
next level, per competition you have joined.

Level thresholds: Bronze 1,000 · Silver 5,000 · Gold 10,000 points.

## Competitions

```bash
wqo account competitions --mine   # ones you joined
wqo account competitions          # all available
wqo account competition IQC2026S1
wqo account competition challenge --alphas
```

`status: EXCLUDED` means the account is not eligible — usually sign-up closed or
a region/university restriction, not an error.

## Everything else

```bash
wqo account activity     # simulation/submission counts + referrals
wqo account teams
wqo account events       # webinars
wqo account tutorials    # the Learn tab
wqo account messages
wqo account agreements
wqo account probe        # what this account level can reach
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

Full probe results and the tab-to-endpoint map: `wqo account --help`.

## When an endpoint 403s

`/users/self/consultant` and `/alphas/{id}/correlations/prod` are gated by
account level. Report that plainly rather than treating it as a bug. Re-run
`account probe` after a level change to see what has opened up.

Companion skill names above are optional guidance. If none are installed, use
the equivalent `wqo` command through this skill's bundled runner.
