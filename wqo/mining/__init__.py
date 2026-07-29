"""Autonomous alpha mining: generate candidates, backtest, rank, shortlist."""

from __future__ import annotations

from typing import Callable, Optional

from ..catalog import Catalog
from ..session import BrainSession
from ..simulate import SimResult, SlotManager, simulate_many
from ..store import Ledger
from .generator import GenerationSpec, generate
from .rank import Scored, score, shortlist

__all__ = [
    "GenerationSpec",
    "Scored",
    "generate",
    "run",
    "score",
    "shortlist",
]


def run(
    session: BrainSession,
    spec: GenerationSpec,
    *,
    ledger: Optional[Ledger] = None,
    catalog: Optional[Catalog] = None,
    shortlist_size: int = 10,
    on_result: Optional[Callable[[SimResult], None]] = None,
) -> dict:
    """One full mining pass: generate -> simulate -> rank.

    Returns a summary dict. Nothing here submits anything; the shortlist is
    handed back for a human to review.
    """
    owns_catalog = catalog is None
    catalog = catalog or Catalog(session)
    try:
        seen = set()
        if ledger:
            seen = {
                row["code"]
                for row in ledger.conn.execute(
                    "SELECT DISTINCT code FROM simulations WHERE status = 'COMPLETE'"
                )
            }
        jobs = generate(catalog, spec, seen_codes=seen)
        if not jobs:
            return {"generated": 0, "simulated": 0, "shortlist": [], "results": []}

        results = simulate_many(
            session,
            jobs,
            ledger=ledger,
            slots=SlotManager(ledger),
            source="mine",
            on_result=on_result,
        )
        best = shortlist(results, limit=shortlist_size)
        return {
            "generated": len(jobs),
            "simulated": len(results),
            "succeeded": sum(1 for r in results if r.ok),
            "failed": sum(1 for r in results if not r.ok),
            "shortlist": [
                dict(s.result.summary(), score=round(s.score, 4), notes=s.reasons)
                for s in best
            ],
            "results": [r.summary() for r in results],
        }
    finally:
        if owns_catalog:
            catalog.close()
