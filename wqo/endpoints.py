"""URL constants for the WorldQuant BRAIN REST API.

All paths are relative to :data:`API_ROOT`. The client accepts either a full
URL or a leading-slash path anywhere a URL is expected, so callers can write
``session.get("/users/self")``.
"""

from __future__ import annotations

API_ROOT = "https://api.worldquantbrain.com"
PLATFORM_ROOT = "https://platform.worldquantbrain.com"

AUTHENTICATION = "/authentication"
AUTHENTICATION_PERSONA = "/authentication/persona"

USERS_SELF = "/users/self"
USERS_SELF_ALPHAS = "/users/self/alphas"
USERS_SELF_ACTIVITIES = "/users/self/activities"

DATA_SETS = "/data-sets"
DATA_FIELDS = "/data-fields"
DATA_CATEGORIES = "/data-categories"
OPERATORS = "/operators"

SIMULATIONS = "/simulations"

ALPHAS = "/alphas"
COMPETITIONS = "/competitions"


def dataset(dataset_id: str) -> str:
    return f"{DATA_SETS}/{dataset_id}"


def data_field(field_id: str) -> str:
    return f"{DATA_FIELDS}/{field_id}"


def alpha(alpha_id: str) -> str:
    return f"{ALPHAS}/{alpha_id}"


def alpha_check(alpha_id: str) -> str:
    return f"{ALPHAS}/{alpha_id}/check"


def alpha_submit(alpha_id: str) -> str:
    return f"{ALPHAS}/{alpha_id}/submit"


def alpha_recordset(alpha_id: str, name: str) -> str:
    """``name`` is one of ``pnl``, ``yearly-stats``, ``daily-pnl``, ..."""
    return f"{ALPHAS}/{alpha_id}/recordsets/{name}"


def alpha_correlation(alpha_id: str, kind: str) -> str:
    """``kind`` is ``self`` or ``prod``."""
    return f"{ALPHAS}/{alpha_id}/correlations/{kind}"


def alpha_url(alpha_id: str) -> str:
    """Human-clickable link into the web UI."""
    return f"{PLATFORM_ROOT}/alpha/{alpha_id}"


def absolute(url: str) -> str:
    """Expand a leading-slash path into a full API URL; pass full URLs through."""
    if url.startswith(("http://", "https://")):
        return url
    if not url.startswith("/"):
        url = "/" + url
    return API_ROOT + url
