"""Account-level reads: competitions, standing, events, tutorials, messages.

These back the website tabs that are not about alphas or data — Competitions,
Team, Learn, Refer a friend, and the notification/agreement surfaces.

What is *not* here matters as much as what is. There is no public leaderboard
endpoint on BRAIN: ``/leaderboards``, ``/leaderboard``, ``/rankings`` and
``/competitions/{id}/leaderboard`` all 404, and ``GET /alphas`` returns 405.
You can read your own rank inside a competition, never anyone else's alphas.
See docs/api-map.md for the full probe results.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional

from . import endpoints
from .session import ApiError, BrainSession

PAGE_SIZE = 100


def _paged(session: BrainSession, path: str, limit: Optional[int] = None) -> list[dict]:
    """Collect a ``{count, results[]}`` endpoint into a list."""
    out: list[dict] = []
    offset = 0
    while True:
        payload = session.json(
            "GET", path, params={"limit": PAGE_SIZE, "offset": offset}
        )
        if isinstance(payload, list):  # some endpoints return a bare list
            return payload if limit is None else payload[:limit]
        results = payload.get("results") or []
        out.extend(results)
        offset += PAGE_SIZE
        count = payload.get("count")
        if limit is not None and len(out) >= limit:
            return out[:limit]
        if not results or count is None or offset >= count:
            return out


# --------------------------------------------------------------------------
# Competitions and standing
# --------------------------------------------------------------------------


def competitions(session: BrainSession, *, mine: bool = False) -> list[dict]:
    """All competitions, or only the ones this account is signed up for."""
    path = "/users/self/competitions" if mine else endpoints.COMPETITIONS
    return _paged(session, path)


def competition(session: BrainSession, competition_id: str) -> dict:
    return session.json("GET", f"{endpoints.COMPETITIONS}/{competition_id}")


def competition_alphas(session: BrainSession, competition_id: str) -> list[dict]:
    """Your alphas entered into a competition."""
    return _paged(session, f"{endpoints.COMPETITIONS}/{competition_id}/alphas")


def competition_agreement(session: BrainSession, competition_id: str) -> dict:
    return session.json("GET", f"{endpoints.COMPETITIONS}/{competition_id}/agreement")


def standing(session: BrainSession) -> dict:
    """Your rank, score, and level progress across the competitions you joined.

    The rank lives in a ``leaderboard`` object nested inside each of *your*
    competition records — it reports your position only. There is no endpoint
    that lists the users above you or what they submitted.
    """
    rows = []
    for entry in competitions(session, mine=True):
        board = entry.get("leaderboard") or {}
        progress = entry.get("progress") or {}
        score = progress.get("score") or {}
        rows.append(
            {
                "competition": entry.get("id"),
                "name": entry.get("name"),
                "status": entry.get("status"),
                "rank": board.get("rank"),
                "score": board.get("score"),
                "alphas": board.get("alphas"),
                "level": progress.get("level") or board.get("level"),
                "points_to_next_level": score.get("remaining"),
                "next_level_at": score.get("top"),
                "university": board.get("university"),
                "country": board.get("country"),
                "faq": entry.get("faq"),
            }
        )
    return {"competitions": rows}


# --------------------------------------------------------------------------
# Activity counters
# --------------------------------------------------------------------------


def activities(session: BrainSession) -> list[dict]:
    """The activity counters BRAIN tracks, e.g. simulations, submissions."""
    payload = session.json("GET", endpoints.USERS_SELF_ACTIVITIES)
    return payload.get("results") or []


def activity(session: BrainSession, name: str) -> Any:
    """One counter's detail — period buckets, or a list for referrals."""
    return session.json("GET", f"{endpoints.USERS_SELF_ACTIVITIES}/{name}")


def activity_summary(session: BrainSession) -> dict:
    """Every activity counter, resolved. This is the 'Refer a friend' tab too."""
    out: dict[str, Any] = {}
    for item in activities(session):
        name = item.get("name")
        if not name:
            continue
        try:
            out[name] = {"title": item.get("title"), "detail": activity(session, name)}
        except ApiError as exc:
            out[name] = {"title": item.get("title"), "error": str(exc)}
    return out


# --------------------------------------------------------------------------
# Team, Learn, notifications
# --------------------------------------------------------------------------


def teams(session: BrainSession) -> list[dict]:
    return _paged(session, "/users/self/teams")


def events(session: BrainSession) -> list[dict]:
    """Webinars and scheduled events."""
    return _paged(session, "/events")


def tutorials(session: BrainSession) -> list[dict]:
    """The Learn tab's course list, each with its page outline."""
    return _paged(session, "/tutorials")


def messages(session: BrainSession) -> list[dict]:
    return _paged(session, "/users/self/messages")


def agreements(session: BrainSession) -> list[dict]:
    return _paged(session, "/users/self/agreements")


# --------------------------------------------------------------------------
# Reachability probe
# --------------------------------------------------------------------------

#: Endpoints worth probing when checking what this account level can reach.
#: Paths known to 404 for everyone are listed in docs/api-map.md rather than
#: re-probed here every time.
PROBE_PATHS: tuple[str, ...] = (
    "/users/self",
    "/users/self/alphas?limit=1",
    "/users/self/competitions",
    "/competitions",
    "/users/self/teams",
    "/users/self/activities",
    "/users/self/messages",
    "/users/self/agreements",
    "/events",
    "/tutorials",
    "/data-sets?instrumentType=EQUITY&region=USA&delay=1&universe=TOP3000&limit=1",
    "/operators",
    "/users/self/consultant",
)


def probe(session: BrainSession, paths: Optional[tuple[str, ...]] = None) -> list[dict]:
    """Report which endpoints this account can actually reach.

    Useful after a level change: endpoints that 403 today (the consultant
    surface, production correlation) may open up later.
    """
    out = []
    for path in paths or PROBE_PATHS:
        try:
            response = session.request("GET", path)
        except ApiError as exc:
            out.append({"path": path, "status": None, "note": str(exc)[:120]})
            continue
        note = ""
        if response.status_code < 400:
            try:
                body = response.json()
                if isinstance(body, dict) and "count" in body:
                    note = f"count={body['count']}"
                elif isinstance(body, list):
                    note = f"list[{len(body)}]"
                elif isinstance(body, dict):
                    note = "object"
            except ValueError:
                note = "non-json"
        else:
            note = response.text[:100].replace("\n", " ")
        out.append({"path": path, "status": response.status_code, "note": note})
    return out
