---
name: wq-alphas
description: List, filter, and organize alphas in a WorldQuant BRAIN account — search by Sharpe, region, status, colour or tag, and set names, tags, colours, categories and descriptions. Use when the user asks what alphas they have, wants to find their best unsubmitted alphas, or wants to label/organize their alpha library.
---

# WorldQuant BRAIN — alpha library

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

## Finding alphas

```bash
.venv/bin/python -m wqo alpha list --status UNSUBMITTED --min-sharpe 1.25 --limit 50
.venv/bin/python -m wqo alpha list --region USA --universe TOP3000 --order -is.sharpe
.venv/bin/python -m wqo alpha list --tag candidate --color GREEN
```

Filters: `--status` (`UNSUBMITTED`, `ACTIVE`, ...), `--region`, `--universe`,
`--delay`, `--min-sharpe`, `--min-fitness`, `--color`, `--tag`, `--order`,
`--limit`. `--order` takes any API field, prefix `-` for descending.

The workhorse query for "what should I look at next" is:

```bash
.venv/bin/python -m wqo alpha list --status UNSUBMITTED --min-sharpe 1.25 --order -is.fitness
```

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

Convention, applied automatically by `alpha label` below:

- `--color GREEN` — no failing checks; awaiting the user's submission decision
- `--color YELLOW` — one failing check, or not yet scored
- `--color RED` — two or more failing checks; kept for reference, not viable

## Labelling anonymous alphas

A freshly simulated alpha has no name, so the BRAIN dashboard fills up with
"anonymous" rows nobody can tell apart. One command fixes the backlog:

```bash
.venv/bin/python -m wqo alpha label --dry-run     # show what it would write
.venv/bin/python -m wqo alpha label               # apply to every unnamed alpha
.venv/bin/python -m wqo alpha label --limit 20 --status UNSUBMITTED
```

It writes four fields per alpha, derived from the record itself so the result
is reproducible:

| Field | Convention |
|---|---|
| `name` | `USA/TOP3000 D1 · <signal> · Sh1.68 Fit1.30` |
| `tags` | `wqo`, region, universe, `delay-N`, `neut-*`, `tpl-<template>`, datafields |
| `color` | by failing-check count, per the table above |
| `description` | expression, full stats line, settings, failing checks, provenance |

`<signal>` is the mining label (`template:datafield`) when this tool ran the
simulation, otherwise the first datafield in the expression.

Only alphas with no name are touched. Pass `--relabel` to overwrite existing
names — ask the user first, it discards names they wrote by hand.

`category` is deliberately left empty: BRAIN publishes no endpoint listing the
valid category values, so any guess risks a rejected PATCH.

## Scale

A few mining runs put this account past 200 alphas. `alpha list` defaults to 50
and pages the API for you; always pass filters rather than pulling everything and
sorting locally. Run `alpha label` after a mining batch so the new rows are
identifiable in the dashboard.

Next step for anything that looks good: `wq-analyze` for the gate report, then
`wq-submit` — which will show the report and wait for the user before submitting.
