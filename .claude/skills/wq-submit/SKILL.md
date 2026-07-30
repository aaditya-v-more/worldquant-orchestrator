---
name: wq-submit
description: Submit an alpha to WorldQuant BRAIN after running the full pre-submission check. Use when the user asks to submit an alpha, or asks whether an alpha is ready to submit. Submission is irreversible and consumes daily quota, so this skill always shows the check report and waits for explicit confirmation first.
---

# WorldQuant BRAIN — submission

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

**Submission is irreversible and consumes the account's daily quota. Never submit
without the user's explicit go-ahead in this conversation.**

## Step 1 — report (read-only, always do this first)

```bash
.venv/bin/python -m wqo submit <alpha_id>
```

Without `--confirm` this **cannot** submit. It runs BRAIN's `/check` plus local
thresholds, prints the per-criterion table, and exits with code 4.

Show the user that report. Include the alpha's expression, settings, Sharpe,
fitness, turnover, and any failing or pending checks.

## Step 2 — ask

Ask plainly whether to submit. Wait for a clear yes. A previous approval of a
different alpha is not approval for this one — confirm per alpha, every time.

## Step 3 — submit

```bash
.venv/bin/python -m wqo submit <alpha_id> --confirm
```

Returns `{"outcome": "SUBMITTED", "alpha_id": ..., "url": ...}` and records the
submission in the local ledger.

## Guard rails

- Without `--confirm`: refuses, exit 4.
- Gate not clean: refuses even with `--confirm`. `--force` overrides this, but
  only use it when the user has seen the failing checks and asked for it anyway.
- Daily submission budget (default 3, `WQO_SUBMIT_BUDGET`): exit 3. Stop and tell
  the user; do not raise the cap on your own.

## Reporting back

State the outcome plainly. If the submission was rejected by BRAIN, quote the
error rather than paraphrasing it, and don't retry automatically — a rejection
usually means a check flipped between the report and the submission.
