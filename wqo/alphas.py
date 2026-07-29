"""Alpha inspection and management.

Covers everything the web UI's alpha pages expose: the record itself, IS
statistics, PnL and yearly breakdowns, self/production correlation, plus the
editable properties (name, colour, tags, category, description).

Several of these endpoints are computed asynchronously and answer with an
empty body plus a ``Retry-After`` header until the result is ready.
:func:`await_payload` implements that wait.
"""

from __future__ import annotations

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
