"""Alpha inspection and management.

Covers everything the web UI's alpha pages expose: the record itself, IS
statistics, PnL and yearly breakdowns, self/production correlation, plus the
editable properties (name, colour, tags, category, description).

Several of these endpoints are computed asynchronously and answer with an
empty body plus a ``Retry-After`` header until the result is ready.
:func:`await_payload` implements that wait.
"""

from __future__ import annotations

import re
import time
from typing import Any, Iterator, Optional

from . import config, endpoints
from .session import ApiError, BrainSession

PAGE_SIZE = 100


def await_payload(
    session: BrainSession, url: str, *, timeout: Optional[float] = None
) -> Any:
    """GET a lazily-computed endpoint, waiting out its ``Retry-After`` cycle."""
    deadline = time.monotonic() + (timeout or config.PACING.poll_timeout)
    while True:
        response = session.request("GET", url)
        if response.status_code >= 400:
            raise ApiError(
                f"GET {url} -> {response.status_code}: {response.text[:300]}", response
            )
        retry_after = response.headers.get("Retry-After")
        has_body = bool(response.content and response.content.strip())
        if retry_after is None and has_body:
            return response.json()
        if retry_after is None and not has_body:
            return None
        if time.monotonic() > deadline:
            raise ApiError(f"timed out waiting for {url}")
        session.governor.sleep_retry_after(response)


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def get(session: BrainSession, alpha_id: str) -> dict:
    return session.json("GET", endpoints.alpha(alpha_id))


def pnl(session: BrainSession, alpha_id: str) -> Any:
    return await_payload(session, endpoints.alpha_recordset(alpha_id, "pnl"))


def yearly_stats(session: BrainSession, alpha_id: str) -> Any:
    return await_payload(session, endpoints.alpha_recordset(alpha_id, "yearly-stats"))


def correlation(session: BrainSession, alpha_id: str, kind: str = "self") -> Any:
    if kind not in {"self", "prod"}:
        raise ValueError("correlation kind must be 'self' or 'prod'")
    return await_payload(session, endpoints.alpha_correlation(alpha_id, kind))


def max_correlation(payload: Any) -> Optional[float]:
    """Pull the peak correlation out of a correlation recordset.

    The payload is a ``{schema: {properties: [...]}, records: [[...]]}`` table;
    the correlation column is whichever property is named ``correlation``, and
    older responses use ``max`` at the top level. Both are handled.
    """
    if payload is None:
        return None
    if isinstance(payload, dict):
        if isinstance(payload.get("max"), (int, float)):
            return float(payload["max"])
        records = payload.get("records") or []
        schema = (payload.get("schema") or {}).get("properties") or []
        names = [p.get("name") for p in schema]
        index = names.index("correlation") if "correlation" in names else None
        values = []
        for record in records:
            if index is not None and index < len(record):
                value = record[index]
            elif isinstance(record, (list, tuple)) and record:
                value = record[-1]
            else:
                continue
            if isinstance(value, (int, float)):
                values.append(float(value))
        return max(values) if values else None
    return None


def search(
    session: BrainSession,
    *,
    status: Optional[str] = None,
    region: Optional[str] = None,
    universe: Optional[str] = None,
    delay: Optional[int] = None,
    min_sharpe: Optional[float] = None,
    min_fitness: Optional[float] = None,
    color: Optional[str] = None,
    tag: Optional[str] = None,
    hidden: Optional[bool] = None,
    order: str = "-dateCreated",
    limit: int = 100,
) -> Iterator[dict]:
    """Iterate your own alphas, applying BRAIN-side filters.

    BRAIN encodes range filters as ``is.sharpe>1.25``. ``requests`` would
    percent-encode the ``>``, so range filters are appended to the raw query
    string instead of going through ``params``.
    """
    base: dict[str, Any] = {"order": order, "limit": min(limit, PAGE_SIZE)}
    if status:
        base["status"] = status
    if region:
        base["settings.region"] = region
    if universe:
        base["settings.universe"] = universe
    if delay is not None:
        base["settings.delay"] = delay
    if color:
        base["color"] = color
    if tag:
        base["tag"] = tag
    if hidden is not None:
        base["hidden"] = "true" if hidden else "false"

    raw_filters = []
    if min_sharpe is not None:
        raw_filters.append(f"is.sharpe>{min_sharpe}")
    if min_fitness is not None:
        raw_filters.append(f"is.fitness>{min_fitness}")
    suffix = ("&" + "&".join(raw_filters)) if raw_filters else ""

    offset = 0
    yielded = 0
    while True:
        params = dict(base, offset=offset)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        payload = session.json(
            "GET", f"{endpoints.USERS_SELF_ALPHAS}?{query}{suffix}"
        )
        results = payload.get("results") or []
        for item in results:
            yield item
            yielded += 1
            if yielded >= limit:
                return
        count = payload.get("count")
        offset += base["limit"]
        if not results or count is None or offset >= count:
            return


# --------------------------------------------------------------------------
# Naming convention
# --------------------------------------------------------------------------
#
# A freshly simulated alpha has name=null, no tags, no colour and no
# description, so the BRAIN dashboard shows a wall of "anonymous" rows that no
# one — human or agent — can tell apart. Everything below derives those fields
# from the alpha record itself, so the convention is reproducible: run it twice
# on the same alpha and you get the same labels.
#
# `category` is deliberately left alone: BRAIN exposes no endpoint listing the
# valid category vocabulary (every plausible path 404s), and guessing a value
# risks a rejected PATCH.

#: Colour convention, matching the wq-alphas skill: green means the local gate
#: is clean, yellow means one short, red means not viable.
COLOR_PASS = "GREEN"
COLOR_BORDERLINE = "YELLOW"
COLOR_FAIL = "RED"

#: Tag applied to everything this tool labels, so `--tag wqo` finds them all.
TOOL_TAG = "wqo"

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGNED = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)")

#: Bare words in a FASTEXPR expression that are arguments, not datafields.
_NOT_DATAFIELDS = {
    "subindustry", "industry", "sector", "market", "true", "false",
}


def datafields_in(code: str) -> list[str]:
    """Best-effort list of the datafields an expression reads.

    An identifier followed by ``(`` is an operator call; one that is assigned
    to is a local variable. What is left over is a datafield or a group name,
    and group names are filtered out explicitly.
    """
    assigned = set(_ASSIGNED.findall(code))
    out: list[str] = []
    for match in _IDENT.finditer(code):
        name = match.group()
        rest = code[match.end():].lstrip()
        if rest.startswith("("):  # operator call
            continue
        if name in assigned or name in _NOT_DATAFIELDS or name in out:
            continue
        out.append(name)
    return out


def _fmt(value: Any, digits: int = 2) -> str:
    return f"{value:.{digits}f}" if isinstance(value, (int, float)) else "?"


def describe(alpha: dict, *, label: Optional[str] = None) -> dict:
    """Derive name, tags, colour and description for one alpha record.

    ``label`` is the mining label (``template:datafield``) when the alpha came
    from a batch this tool ran; it makes a far better name than anything
    recoverable from the expression, so it wins when present.
    """
    settings = alpha.get("settings") or {}
    stats = alpha.get("is") or {}
    code = (alpha.get("regular") or {}).get("code") or ""
    region = settings.get("region") or "?"
    universe = settings.get("universe") or "?"
    delay = settings.get("delay")

    fields = datafields_in(code)
    signal = label or (fields[0] if fields else "expr")
    sharpe, fitness = stats.get("sharpe"), stats.get("fitness")

    name = (
        f"{region}/{universe} D{delay} · {signal} · "
        f"Sh{_fmt(sharpe)} Fit{_fmt(fitness)}"
    )[:120]

    checks = stats.get("checks") or []
    failed = [c.get("name") for c in checks if c.get("result") == "FAIL"]
    if not checks:
        color = COLOR_BORDERLINE
    elif not failed:
        color = COLOR_PASS
    elif len(failed) == 1:
        color = COLOR_BORDERLINE
    else:
        color = COLOR_FAIL

    tags = [TOOL_TAG, region, universe]
    if delay is not None:
        tags.append(f"delay-{delay}")
    neutralization = settings.get("neutralization")
    if neutralization:
        tags.append(f"neut-{str(neutralization).lower()}")
    if label and ":" in label:
        tags.append(f"tpl-{label.split(':', 1)[0]}")
    tags.extend(fields[:2])
    # Duplicates are possible (a datafield named like a region is unlikely but
    # cheap to guard); BRAIN keeps whatever list it is given.
    tags = list(dict.fromkeys(t for t in tags if t))[:8]

    description = "\n".join(
        [
            f"{code}",
            "",
            f"Sharpe {_fmt(sharpe)} · fitness {_fmt(fitness)} · "
            f"turnover {_fmt(stats.get('turnover'), 4)} · "
            f"returns {_fmt(stats.get('returns'), 4)} · "
            f"drawdown {_fmt(stats.get('drawdown'), 4)}",
            f"{region} {universe} delay {delay}, neutralization {neutralization}, "
            f"decay {settings.get('decay')}, truncation {settings.get('truncation')}",
            f"Failing checks: {', '.join(failed) if failed else 'none'}",
            f"Labelled by wqo{f' from mining label {label}' if label else ''}.",
        ]
    )

    return {"name": name, "tags": tags, "color": color, "description": description}


def needs_labels(alpha: dict) -> bool:
    """True when the dashboard would show this alpha as anonymous."""
    return not (alpha.get("name") or "").strip()


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------


def patch(
    session: BrainSession,
    alpha_id: str,
    *,
    name: Optional[str] = None,
    color: Optional[str] = None,
    tags: Optional[list[str]] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    favorite: Optional[bool] = None,
    hidden: Optional[bool] = None,
) -> dict:
    """Update an alpha's editable properties. Only supplied fields are sent."""
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if color is not None:
        body["color"] = color
    if tags is not None:
        body["tags"] = tags
    if category is not None:
        body["category"] = category
    if favorite is not None:
        body["favorite"] = favorite
    if hidden is not None:
        body["hidden"] = hidden
    if description is not None:
        body["regular"] = {"description": description}
    if not body:
        raise ValueError("nothing to update")
    return session.json("PATCH", endpoints.alpha(alpha_id), json=body)


def label_all(
    session: BrainSession,
    *,
    labels: Optional[dict[str, str]] = None,
    limit: int = 100,
    only_anonymous: bool = True,
    dry_run: bool = False,
    status: Optional[str] = None,
    on_result=None,
) -> list[dict]:
    """Apply :func:`describe` to every alpha that is still anonymous.

    ``labels`` maps alpha id -> mining label, normally taken from the local
    ledger. Alphas simulated elsewhere simply fall back to a datafield-derived
    name.
    """
    labels = labels or {}
    out: list[dict] = []
    for alpha in search(session, limit=limit, status=status):
        if only_anonymous and not needs_labels(alpha):
            continue
        alpha_id = alpha.get("id")
        proposed = describe(alpha, label=labels.get(alpha_id))
        row = {"alpha_id": alpha_id, **proposed, "applied": False}
        if not dry_run:
            patch(
                session,
                alpha_id,
                name=proposed["name"],
                tags=proposed["tags"],
                color=proposed["color"],
                description=proposed["description"],
            )
            row["applied"] = True
        out.append(row)
        if on_result:
            on_result(row)
    return out
