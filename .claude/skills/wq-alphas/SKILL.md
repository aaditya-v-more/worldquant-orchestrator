---
name: wq-alphas
description: List, filter, and organize alphas in a WorldQuant BRAIN account — search by Sharpe, region, status, colour or tag, and set names, tags, colours, categories and descriptions. Use when the user asks what alphas they have, wants to find their best unsubmitted alphas, or wants to label/organize their alpha library.
---

# WorldQuant BRAIN — alpha library

## Before running anything

```bash
cd /path/to/worldquant-orchestrator   # the repo root
```

All commands below use `.venv/bin/python -m wqo`. If `.venv` is missing, or you
have not read the hard rules (never submit without explicit confirmation, never
bypass the Persona biometric check, never touch the credentials file), read
[`AGENTS.md`](../../../AGENTS.md) in the repo root first.

Exit codes: `0` ok · `1` error or gate blocked · `2` auth/biometric · `3` budget
exhausted · `4` submission refused.

## Finding alphas

```bash
.venv/bin/python -m wqo alpha list --status UNSUBMITTED --min-sharpe 1.25 --limit 50
.venv/bin/python -m wqo alpha list --region USA --universe TOP3000 --order -is.sharpe
.venv/bin/python -m wqo alpha list --tag candidate --color GREEN
```

Filters: `--status` (`UNSUBMITTED`, `ACTIVE`, ...), `--region`, `--universe`,
`--delay`, `--min-sharpe`, `--min-fitness`, `--color`, `--tag`, `--grade`,
`--order`, `--limit`. `--order` takes any API field, prefix `-` for descending.

The workhorse query for "what should I look at next" is:

```bash
.venv/bin/python -m wqo alpha list --status UNSUBMITTED --min-sharpe 1.25 --order -is.fitness
```

## Grade

Every record carries a `grade` BRAIN computed itself — `INFERIOR`, `AVERAGE`,
`GOOD`, `EXCELLENT`, `SPECTACULAR`. It is read-only; nothing here or on the
platform lets you set it.

```bash
.venv/bin/python -m wqo alpha list --status UNSUBMITTED --grade EXCELLENT
```

Unlike the other filters this one is matched locally against records already
fetched, so combine it with `--limit` generously — a page that yields no matches
still counts against the pages read, not against `--limit`.

Use grade to triage, never to decide. An `EXCELLENT` alpha can still fail
`SELF_CORRELATION` or `MATCHES_COMPETITION`; run `wq-analyze` before treating
anything as submittable.

## Organizing

```bash
.venv/bin/python -m wqo alpha tag <alpha_id> \
  --name "revenue momentum, subindustry neutral" \
  --color GREEN --tags "fundamental,momentum" \
  --description "ts_rank of backfilled revenue, neutralized by subindustry"
```

Colours: `RED`, `GREEN`, `BLUE`, `YELLOW`, `PURPLE`. Only the flags you pass are
changed; everything else is left alone.

Tagging is genuinely useful, not decoration — the mining loop produces a lot of
alphas, and `--tag` plus `alpha list --tag` is how a shortlist stays findable
across sessions.

Suggested convention:

- `--color GREEN` — passed the gate, awaiting the user's submission decision
- `--color YELLOW` — promising but one check short
- `--color RED` — kept for reference, not viable

## Scale

A few mining runs put this account past 120 alphas. `alpha list` defaults to 50
and pages the API for you; always pass filters rather than pulling everything and
sorting locally.

Next step for anything that looks good: `wq-analyze` for the gate report, then
`wq-submit` — which will show the report and wait for the user before submitting.
