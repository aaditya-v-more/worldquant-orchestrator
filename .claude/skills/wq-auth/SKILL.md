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

`<your account id>`, `level: NONE` — the lowest tier. Consequences worth knowing before
planning any work:

- **~1 simulation slot.** Batches run near-sequentially; 40 candidates is roughly
  an hour of wall clock. Concurrency is learned from 429s and persisted — do not
  override it with `WQO_MAX_CONCURRENCY`.
- **66 operators**, not the full set. Check `wqo data operators` before
  suggesting one.
- **`/alphas/{id}/correlations/prod` returns 403.** The `MATCHES_COMPETITION`
  check still runs server-side, so the gate verdict is real; only the breakdown
  is unreadable.
- **`/users/self/consultant` returns 403.**

Re-run `wqo account probe` after a level change to see what opened up.

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
