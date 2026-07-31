"""Strip tool attribution from alpha metadata on BRAIN, keep it locally.

The labeller on `feat/parallel-agents-and-alpha-labels` wrote a `wqo` tag, a
`tpl-<template>` tag and a trailing "Labelled by wqo from mining label ..."
line onto every alpha it touched. That provenance belongs in this repo, not on
the server. This script moves it: full backup to JSON, a readable index to
Markdown, then a PATCH per alpha that removes the markers.

    .venv/bin/python scripts/scrub_attribution.py --dry-run
    .venv/bin/python scripts/scrub_attribution.py --apply
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from wqo import alphas as alpha_api
from wqo.session import open_session

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "provenance"

TOOL_TAG = "wqo"
TPL_PREFIX = "tpl-"
PROVENANCE = re.compile(r"^Labelled by wqo.*$\n?", re.MULTILINE)
#: "USA/TOP3000 D1 · alpha04v2:decay20_INDUSTRY · Sh1.90 Fit1.57"
NAME_PARTS = re.compile(r"^(?P<head>[^·]+·\s*)(?P<signal>[^·]+?)(?P<tail>\s*·.*)$")


def fetch_all(session) -> list[dict]:
    out: list[dict] = []
    offset, limit = 0, 100
    while True:
        page = session.json(
            "GET", f"/users/self/alphas?limit={limit}&offset={offset}"
        )
        out.extend(page["results"])
        if not page.get("next"):
            return out
        offset += limit


def clean_signal(signal: str) -> str:
    """Drop the mining template id, keep the descriptive half of the label."""
    if ":" in signal:
        signal = signal.split(":", 1)[1]
    return signal.strip()


def scrub(alpha: dict) -> dict | None:
    """Return the PATCH body for one alpha, or None when already clean."""
    body: dict = {}

    tags = alpha.get("tags") or []
    kept = [t for t in tags if t != TOOL_TAG and not t.startswith(TPL_PREFIX)]
    if kept != tags:
        body["tags"] = kept

    description = (alpha.get("regular") or {}).get("description") or ""
    stripped = PROVENANCE.sub("", description).rstrip()
    if stripped != description:
        body["description"] = stripped

    name = alpha.get("name") or ""
    match = NAME_PARTS.match(name)
    if match:
        signal = clean_signal(match["signal"])
        rebuilt = f"{match['head']}{signal}{match['tail']}"
        if rebuilt != name:
            body["name"] = rebuilt

    return body or None


def record(alpha: dict, body: dict) -> dict:
    """What is being removed, so it survives locally."""
    tags = alpha.get("tags") or []
    return {
        "id": alpha["id"],
        "mining_label": next(
            (t[len(TPL_PREFIX):] for t in tags if t.startswith(TPL_PREFIX)), None
        ),
        "name_before": alpha.get("name"),
        "name_after": body.get("name", alpha.get("name")),
        "tags_before": tags,
        "tags_after": body.get("tags", tags),
        "description_before": (alpha.get("regular") or {}).get("description"),
        "code": (alpha.get("regular") or {}).get("code"),
        "status": alpha.get("status"),
        "sharpe": (alpha.get("is") or {}).get("sharpe"),
        "fitness": (alpha.get("is") or {}).get("fitness"),
    }


def write_local(all_alphas: list[dict], records: list[dict]) -> None:
    OUT.mkdir(exist_ok=True)
    stamp = date.today().isoformat()

    (OUT / f"alphas-raw-{stamp}.json").write_text(
        json.dumps(all_alphas, indent=2), encoding="utf-8"
    )
    (OUT / "attribution.json").write_text(
        json.dumps(records, indent=2), encoding="utf-8"
    )

    lines = [
        "# Alpha provenance",
        "",
        "Mining labels and generated metadata, kept here instead of on BRAIN.",
        f"Captured {stamp} from {len(all_alphas)} alphas; "
        f"{len(records)} carried tool attribution.",
        "",
        "| id | mining label | Sharpe | fitness | status | expression |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(records, key=lambda r: -(r["sharpe"] or 0)):
        code = (r["code"] or "").replace("|", "\\|").replace("\n", " ")[:90]
        lines.append(
            f"| `{r['id']}` | {r['mining_label'] or '—'} | {r['sharpe']} | "
            f"{r['fitness']} | {r['status']} | `{code}` |"
        )
    (OUT / "attribution.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    session = open_session()
    all_alphas = fetch_all(session)

    pending = [(a, scrub(a)) for a in all_alphas]
    pending = [(a, b) for a, b in pending if b]
    records = [record(a, b) for a, b in pending]

    write_local(all_alphas, records)

    print(json.dumps({
        "total": len(all_alphas),
        "needing_scrub": len(pending),
        "local_dir": str(OUT.relative_to(ROOT)),
        "preview": [
            {
                "id": a["id"],
                "name": f"{a.get('name')}  ->  {b.get('name', '(unchanged)')}",
                "tags_removed": sorted(
                    set(a.get("tags") or []) - set(b.get("tags", a.get("tags") or []))
                ),
                "description_line_removed": "description" in b,
            }
            for a, b in pending[:3]
        ],
    }, indent=2))

    if args.dry_run:
        return 0

    failed = []
    for index, (alpha, body) in enumerate(pending, 1):
        try:
            alpha_api.patch(session, alpha["id"], **body)
        except Exception as exc:  # keep going, report at the end
            failed.append({"id": alpha["id"], "error": str(exc)})
        if index % 25 == 0:
            print(f"  patched {index}/{len(pending)}", flush=True)

    print(json.dumps({
        "patched": len(pending) - len(failed), "failed": failed
    }, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
