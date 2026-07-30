"""Candidate generation: turn a dataset's fields into simulation jobs."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable, Optional

from .. import config
from ..catalog import Catalog
from ..simulate import SimJob, build_settings
from . import templates as tpl


@dataclass
class GenerationSpec:
    region: str = "USA"
    delay: int = 1
    universe: str = "TOP3000"
    dataset_id: Optional[str] = None
    field_search: Optional[str] = None
    #: Settings variants swept per candidate expression. Each entry is a dict of
    #: setting overrides merged onto the defaults.
    #:
    #: Derived from *151 Trading Strategies* (Kakushadze & Serur):
    #: - Trend/momentum strategies (§3.1, §10.4): higher decay (10) smooths
    #:   turnover; MARKET neutralization captures broad trends.
    #: - Mean-reversion strategies (§3.9, §10.3): low decay (4) keeps the
    #:   signal reactive; SUBINDUSTRY neutralization isolates stock-specific.
    #: - Multifactor/value (§3.3, §3.6): moderate decay (6), INDUSTRY neut.
    #: - Lower truncation (0.05) for high-turnover signals to reduce weight
    #:   concentration; higher (0.10) for slow-moving fundamentals.
    variants: tuple[dict, ...] = (
        # Default balanced (existing behaviour)
        {"neutralization": "SUBINDUSTRY", "decay": 6, "truncation": 0.08},
        # Momentum / trend-following regime (§3.1, §10.4)
        {"neutralization": "MARKET", "decay": 10, "truncation": 0.05},
        # Fast mean-reversion regime (§3.9, §10.3)
        {"neutralization": "SUBINDUSTRY", "decay": 4, "truncation": 0.08},
        # Fundamental / value regime (§3.3, §3.6)
        {"neutralization": "INDUSTRY", "decay": 8, "truncation": 0.10},
    )
    template_names: Optional[tuple[str, ...]] = None
    max_fields: int = 40
    budget: int = 40
    seed: Optional[int] = None


def _usable_fields(catalog: Catalog, spec: GenerationSpec) -> list[dict]:
    fields = catalog.fields(
        dataset_id=spec.dataset_id,
        region=spec.region,
        delay=spec.delay,
        universe=spec.universe,
        search=spec.field_search,
    )
    # Prefer well-covered fields; thin coverage produces unstable backtests.
    def coverage(f: dict) -> float:
        value = f.get("coverage")
        return float(value) if isinstance(value, (int, float)) else 0.0

    fields.sort(key=coverage, reverse=True)
    return fields[: spec.max_fields]


def generate(
    catalog: Catalog,
    spec: GenerationSpec,
    *,
    seen_codes: Optional[Iterable[str]] = None,
) -> list[SimJob]:
    """Build a de-duplicated, budget-capped list of simulation jobs."""
    rng = random.Random(spec.seed)
    operators = {op.get("name") for op in catalog.operators() if op.get("name")}
    fields = _usable_fields(catalog, spec)
    already = set(seen_codes or ())

    jobs: list[SimJob] = []
    codes: set[str] = set()

    for datafield in fields:
        field_id = datafield.get("id")
        if not field_id:
            continue
        kind = str(datafield.get("type") or "MATRIX").upper()
        candidates = tpl.templates_for(kind, operators)
        if spec.template_names:
            wanted = set(spec.template_names)
            candidates = [t for t in candidates if t.name in wanted]

        for template in candidates:
            for expr in template.expand(field_id):
                if expr in codes or expr in already:
                    continue
                codes.add(expr)
                for variant in spec.variants:
                    settings = build_settings(
                        region=spec.region,
                        delay=spec.delay,
                        universe=spec.universe,
                        **variant,
                    )
                    jobs.append(
                        SimJob(
                            code=expr,
                            settings=settings,
                            label=f"{template.name}:{field_id}",
                        )
                    )

    # Shuffle before truncating so a budget cut samples across all fields and
    # templates instead of exhausting the first field alphabetically.
    rng.shuffle(jobs)
    return jobs[: spec.budget]
