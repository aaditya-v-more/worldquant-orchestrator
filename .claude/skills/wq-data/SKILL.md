---
name: wq-data
description: Browse WorldQuant BRAIN datasets, datafields, and operators. Use when the user asks what data or operators are available, wants to explore a dataset, needs field IDs for building an alpha expression, or asks which fields exist for a region/universe/delay combination.
---

# WorldQuant BRAIN — data discovery

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
