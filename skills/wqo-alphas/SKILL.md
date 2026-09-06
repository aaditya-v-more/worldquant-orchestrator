---
name: wqo-alphas
description: Find and organize the user's WorldQuant BRAIN alphas with WQO. Use to filter the alpha library or apply requested names, colors, tags and descriptions.
---

# WorldQuant BRAIN — alpha library

## Setup

Read [setup and operational boundaries](references/runtime.md) before running
commands. Use the bundled `scripts/wqo.sh` runner for every `wqo` command below;
it installs the CLI locally when missing. This skill works without other skills
or a source checkout.

## Finding alphas

```bash
wqo alpha list --status UNSUBMITTED --min-sharpe 1.25 --limit 50
wqo alpha list --region USA --universe TOP3000 --order=-is.sharpe
wqo alpha list --tag candidate --color GREEN
```

Filters: `--status` (`UNSUBMITTED`, `ACTIVE`, ...), `--region`, `--universe`,
`--delay`, `--min-sharpe`, `--min-fitness`, `--color`, `--tag`, `--grade`,
`--order`, `--limit`. `--order` takes any API field, prefix `-` for descending.

The workhorse query for "what should I look at next" is:

```bash
wqo alpha list --status UNSUBMITTED --min-sharpe 1.25 --order=-is.fitness
```

## Grade

Every record carries a `grade` BRAIN computed itself — `INFERIOR`, `AVERAGE`,
`GOOD`, `EXCELLENT`, `SPECTACULAR`. It is read-only; nothing here or on the
platform lets you set it.

```bash
wqo alpha list --status UNSUBMITTED --grade EXCELLENT
```

Unlike the other filters this one is matched locally against records already
fetched, so combine it with `--limit` generously — a page that yields no matches
still counts against the pages read, not against `--limit`.

Use grade to triage, never to decide. An `EXCELLENT` alpha can still fail
`SELF_CORRELATION` or `MATCHES_COMPETITION`; run `wqo-analyze` before treating
anything as submittable.

## Organizing

```bash
wqo alpha tag <alpha_id> \
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

`alpha list` defaults to 50
and pages the API for you; always pass filters rather than pulling everything and
sorting locally.

Next step for anything that looks good: `wqo-analyze` for the gate report, then
`wqo-submit` — which will show the report and wait for the user before submitting.

Companion skill names above are optional guidance. If none are installed, use
the equivalent `wqo` command through this skill's bundled runner.
