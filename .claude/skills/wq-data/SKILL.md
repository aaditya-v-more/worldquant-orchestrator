---
name: wq-data
description: Browse WorldQuant BRAIN datasets, datafields, and operators. Use when the user asks what data or operators are available, wants to explore a dataset, needs field IDs for building an alpha expression, or asks which fields exist for a region/universe/delay combination.
---

# WorldQuant BRAIN — data discovery

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

Everything here is cached locally in `data/catalog.sqlite` for 7 days, so repeated
lookups cost zero API requests. Pass `--refresh` only when the user asks for fresh
data or a dataset was just released.

## Datasets

```bash
.venv/bin/python -m wqo data datasets --region USA --delay 1 --universe TOP3000
```

Add `--search "analyst"` to filter. Output includes `id`, `name`, `fieldCount`,
`alphaCount`, and `valueScore`. Low `alphaCount` with decent `valueScore` is the
interesting quadrant — less crowded.

## Datafields

```bash
.venv/bin/python -m wqo data fields --dataset fundamental6 --region USA --delay 1
.venv/bin/python -m wqo data fields --search revenue --limit 30
```

`--type MATRIX` for ordinary time-series fields, `--type VECTOR` for vector fields
(these need `vec_avg`/`vec_sum` wrappers). `coverage` matters: below ~0.5 the field
is sparse and backtests on it are unstable.

## Operators

```bash
.venv/bin/python -m wqo data operators
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

Next step after picking one: `wq-mine` to sweep it, or `wq-simulate` for a
single hand-written expression. Expression syntax rules are in
[`docs/fastexpr.md`](../../../docs/fastexpr.md).
