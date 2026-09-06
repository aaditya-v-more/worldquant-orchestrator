---
name: wqo-data
description: Discover WorldQuant BRAIN datasets, fields and available operators with WQO. Use to select inputs for an alpha or inspect data coverage for specific simulation settings.
---

# WorldQuant BRAIN — data discovery

## Setup

Read [setup and operational boundaries](references/runtime.md) before running
commands. Use the bundled `scripts/wqo.sh` runner for every `wqo` command below;
it installs the CLI locally when missing. This skill works without other skills
or a source checkout.

## Datasets

```bash
wqo data datasets --region USA --delay 1 --universe TOP3000
```

Add `--search "analyst"` to filter. Output includes `id`, `name`, `fieldCount`,
`alphaCount`, and `valueScore`. Low `alphaCount` with decent `valueScore` is the
interesting quadrant — less crowded.

## Datafields

```bash
wqo data fields --dataset fundamental6 --region USA --delay 1
wqo data fields --search revenue --limit 30
```

`--type MATRIX` for ordinary time-series fields, `--type VECTOR` for vector fields
(these need `vec_avg`/`vec_sum` wrappers). `coverage` matters: below ~0.5 the field
is sparse and backtests on it are unstable.

## Operators

```bash
wqo data operators
```

The available operator set depends on the account's level. Check here before
suggesting an expression — an operator the account doesn't have fails the
simulation and wastes a slot.

## Notes

- Datafields are scoped by region + delay + universe. A field that exists for
  USA/TOP3000 may not exist for EUR/TOP2500, so always pass the settings the alpha
  will actually be simulated with.
- Add `--raw` to see the full API record when a summarized field isn't enough.
- **`--search` is capped at 100 results** by the API (`offset + limit > 100`
  returns `400 Invalid query`). The client stops at that ceiling rather than
  erroring. Narrow the term or filter by `--dataset` if you need more.
- The `pv1` dataset is the price/volume core and worth knowing by heart:
  `open high low close vwap volume adv20 cap returns sharesout dividend split
  adjfactor sector industry subindustry market country exchange currency`.

## Picking a dataset to mine

`alphaCount` is how many alphas the community has already built on it. High
`valueScore` with low `alphaCount` is the interesting quadrant — signal that is
not yet crowded, which matters because self-correlation and
`MATCHES_COMPETITION` are what kill otherwise-good alphas.

Next step after picking one: `wqo-mine` to sweep it, or `wqo-simulate` for a
single hand-written expression. Expression syntax rules are in
[expression notes](references/fastexpr.md).

Companion skill names above are optional guidance. If none are installed, use
the equivalent `wqo` command through this skill's bundled runner.
