---
name: wqo-submit
description: Review and submit a specific WorldQuant BRAIN alpha with WQO only after explicit per-alpha approval. Use for submission requests or a submission readiness report.
---

# WorldQuant BRAIN — submission

## Setup

Read [setup and operational boundaries](references/runtime.md) before running
commands. Use the bundled `scripts/wqo.sh` runner for every `wqo` command below;
it installs the CLI locally when missing. This skill works without other skills
or a source checkout.

## Step 1 — report (read-only, always do this first)

```bash
wqo submit <alpha_id>
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
wqo submit <alpha_id> --confirm
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

State the outcome plainly. If the submission was rejected by BRAIN, report the sanitized diagnostic, and don't retry automatically — a rejection
usually means a check flipped between the report and the submission.

Companion skill names above are optional guidance. If none are installed, use
the equivalent `wqo` command through this skill's bundled runner.
