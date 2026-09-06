---
name: wqo-auth
description: Authenticate WQO with WorldQuant BRAIN and handle session errors or human Persona verification. Use for login, logout, account authentication status and quota checks.
---

# WorldQuant BRAIN — authentication

## Setup

Read [setup and operational boundaries](references/runtime.md) before running
commands. Use the bundled `scripts/wqo.sh` runner for every `wqo` command below;
it installs the CLI locally when missing. This skill works without other skills
or a source checkout.

## What this account can do

Run `wqo auth status` for your account and learned concurrency. The observations
below came from a `NONE` account on 2026-07-30 and were not re-probed in the
2026-09-07 documentation review; they are not universal tier limits:

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
wqo auth status
```

Prints the logged-in user, daily simulation/submission usage against budget, and
the learned concurrency. Run this first in a session — it authenticates using the
cached cookie if one is valid, and only re-authenticates when it isn't.

```bash
wqo auth login     # force a fresh login
wqo auth persona   # finish a biometric check
wqo auth logout    # drop the cached session
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

Authentication may require a Persona identity check. When that happens the command
exits with code 2 and prints a URL. This is not an error to work around:

1. Give the user the URL and ask them to complete it in a browser.
2. Wait for them to say they're done.
3. Run `wqo auth persona`.

Never attempt to bypass, automate, or solve this check.

## Exit codes

| Code | Meaning | Action |
|---|---|---|
| 0 | fine | continue |
| 2 | auth required or biometric pending | read stderr, follow the biometric flow above |
| 3 | daily budget exhausted | stop; tell the user, don't raise the cap without asking |

Companion skill names above are optional guidance. If none are installed, use
the equivalent `wqo` command through this skill's bundled runner.
