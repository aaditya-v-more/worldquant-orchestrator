---
name: wq-auth
description: Authenticate against WorldQuant BRAIN and check account status, quotas, and simulation concurrency. Use when a BRAIN command returns an auth error, when the user asks to log in / check their BRAIN account, when a biometric (Persona) verification is pending, or before any other wq-* skill runs for the first time in a session.
---

# WorldQuant BRAIN — authentication

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

## What this account can do

Several people share this repo on different BRAIN accounts, so nothing here
states a level, slot count, or score. Read the gitignored snapshot:

```bash
.venv/bin/python -m wqo account snapshot   # then read ACCOUNT.local.md
```

It reports account id, level, learned concurrency, operator count, standing,
and which endpoints 403 today. Regenerate it if it is missing or stale rather
than assuming last session's numbers still hold.

True on every low-tier account:

- **Few simulation slots.** Batches run near-sequentially; 40 candidates is
  roughly an hour of wall clock. Concurrency is learned from 429s and
  persisted — do not override it with `WQO_MAX_CONCURRENCY`.
- **Partial operator set.** Check `wqo data operators` before suggesting one.
- **Some endpoints 403 by level**, typically `/users/self/consultant` and
  `/alphas/{id}/correlations/prod`. The `MATCHES_COMPETITION` check still runs
  server-side, so the gate verdict is real; only the breakdown is unreadable.

## Quotas roll on BRAIN's clock, not yours

BRAIN runs on US Eastern (UTC−4 summer / −5 winter). Simulation and submission
quotas roll at **midnight Eastern**; the Challenge score refreshes at **03:00
Eastern** with a 2,000-point daily cap. Detail in `docs/scoring.md`.

`auth status` reports `simulations_today` / `submissions_today` from the local
SQLite ledger, which only records work done through this tool. Anything
submitted from the website is invisible to it. When the number matters, check
the server:

```bash
.venv/bin/python -m wqo api GET /users/self/activities/submissions
```

## Commands

```bash
.venv/bin/python -m wqo auth status
```

Prints the logged-in user, daily simulation/submission usage against budget, and
the learned concurrency. Run this first in a session — it authenticates using the
cached cookie if one is valid, and only re-authenticates when it isn't.

```bash
.venv/bin/python -m wqo auth login     # force a fresh login
.venv/bin/python -m wqo auth persona   # finish a biometric check
.venv/bin/python -m wqo auth logout    # drop the cached session
```

## Credentials

Credentials live in `~/.brain_credentials.json`, created by the user:

```json
{"email": "...", "password": "..."}
```

**Never write, edit, echo, or read back this file's contents.** If it is missing,
tell the user to create it themselves and run `chmod 600 ~/.brain_credentials.json`.
Do not offer to type the password for them.

## Biometric verification

New accounts usually hit a Persona identity check. When that happens the command
exits with code 2 and prints a URL. This is not an error to work around:

1. Give the user the URL and ask them to complete it in a browser.
2. Wait for them to say they're done.
3. Run `.venv/bin/python -m wqo auth persona`.

Never attempt to bypass, automate, or solve this check.

## Exit codes

| Code | Meaning | Action |
|---|---|---|
| 0 | fine | continue |
| 2 | auth required or biometric pending | read stderr, follow the biometric flow above |
| 3 | daily budget exhausted | stop; tell the user, don't raise the cap without asking |
