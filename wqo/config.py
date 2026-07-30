"""Configuration: filesystem paths, pacing defaults, and quality gate thresholds.

Every value can be overridden with a ``WQO_``-prefixed environment variable, so
you can tighten pacing or thresholds without editing code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_DIR = PACKAGE_DIR.parent


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

#: You create this file yourself: {"email": "...", "password": "..."}
CREDENTIALS_PATH = Path(
    _env_str("WQO_CREDENTIALS", str(Path.home() / ".brain_credentials.json"))
).expanduser()

#: Cached session cookie, written with mode 0600.
SESSION_PATH = Path(
    _env_str("WQO_SESSION", str(Path.home() / ".brain_session.json"))
).expanduser()

#: Per-user account snapshot: level, score, slots, which endpoints 403 today.
#: Gitignored on purpose — several people share this repo and none of them have
#: the same account, so these values belong nowhere near the committed docs.
#: Regenerate with ``wqo account snapshot``.
ACCOUNT_SNAPSHOT_PATH = Path(
    _env_str("WQO_ACCOUNT_SNAPSHOT", str(REPO_DIR / "ACCOUNT.local.md"))
).expanduser()

DATA_DIR = Path(_env_str("WQO_DATA_DIR", str(REPO_DIR / "data"))).expanduser()
LEDGER_PATH = DATA_DIR / "wqo.sqlite"
CATALOG_PATH = DATA_DIR / "catalog.sqlite"
PENDING_PERSONA_PATH = DATA_DIR / "pending_persona.json"
LOG_PATH = DATA_DIR / "wqo.log"


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


# --------------------------------------------------------------------------
# Pacing / good API citizenship
# --------------------------------------------------------------------------


@dataclass
class Pacing:
    """Request pacing knobs.

    The defaults are deliberately gentle. The single most important rule is
    that we honor the server's own ``Retry-After`` header rather than polling
    on a fixed interval of our choosing.
    """

    #: Minimum seconds between any two HTTP requests from this process.
    min_interval: float = field(
        default_factory=lambda: _env_float("WQO_MIN_INTERVAL", 0.40)
    )
    #: Uniform jitter (seconds) added on top of ``min_interval``.
    jitter: float = field(default_factory=lambda: _env_float("WQO_JITTER", 0.35))
    #: Base for exponential backoff after a 429/5xx.
    backoff_base: float = field(
        default_factory=lambda: _env_float("WQO_BACKOFF_BASE", 2.0)
    )
    #: Ceiling for any single backoff sleep.
    backoff_max: float = field(
        default_factory=lambda: _env_float("WQO_BACKOFF_MAX", 120.0)
    )
    #: How many times to retry a retryable failure before giving up.
    max_retries: int = field(default_factory=lambda: _env_int("WQO_MAX_RETRIES", 8))
    #: Fallback poll interval when the server sends no ``Retry-After``.
    default_retry_after: float = field(
        default_factory=lambda: _env_float("WQO_DEFAULT_RETRY_AFTER", 5.0)
    )
    #: Hard ceiling on how long a single simulation may be polled, in seconds.
    poll_timeout: float = field(
        default_factory=lambda: _env_float("WQO_POLL_TIMEOUT", 1800.0)
    )
    #: HTTP socket timeout.
    http_timeout: float = field(
        default_factory=lambda: _env_float("WQO_HTTP_TIMEOUT", 60.0)
    )


@dataclass
class Budget:
    """Local per-day caps, enforced against the ledger before acting.

    "Day" means BRAIN's day — midnight US Eastern, see ``store._brain_day_start``.
    These count only work done through this tool; the server's own counters at
    ``/users/self/activities/*`` are authoritative. Separately, the Challenge
    score caps at 2,000 points/day on a *different* boundary (03:00 Eastern);
    ``docs/scoring.md`` has the detail.
    """

    simulations_per_day: int = field(
        default_factory=lambda: _env_int("WQO_SIM_BUDGET", 300)
    )
    submissions_per_day: int = field(
        default_factory=lambda: _env_int("WQO_SUBMIT_BUDGET", 3)
    )


#: Starting concurrency before the account's real slot count is known.
#: A brand-new account gets the most conservative setting.
DEFAULT_CONCURRENCY = _env_int("WQO_CONCURRENCY", 1)
MAX_CONCURRENCY = _env_int("WQO_MAX_CONCURRENCY", 10)

USER_AGENT = _env_str(
    "WQO_USER_AGENT",
    "worldquant-orchestrator/0.1 (+https://api.worldquantbrain.com; python-requests)",
)


# --------------------------------------------------------------------------
# Simulation defaults
# --------------------------------------------------------------------------

DEFAULT_SETTINGS: dict = {
    "instrumentType": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 6,
    "neutralization": "SUBINDUSTRY",
    "truncation": 0.08,
    "pasteurization": "ON",
    "unitHandling": "VERIFY",
    "nanHandling": "OFF",
    "language": "FASTEXPR",
    "visualization": False,
    "testPeriod": "P0Y0M",
}


#: Settings tuned per strategy family, following *151 Trading Strategies*
#: (Kakushadze & Serur, 2018). A template declares which family it belongs to
#: and the generator simulates it under that family's settings only — one job
#: per expression. Sweeping every expression across every regime would multiply
#: job count without adding expressions, which on a one-slot account trades
#: search breadth for redundancy.
#:
#: decay — momentum (§3.1, §10.4) wants 8-12: smoothing cuts turnover, which
#: lifts fitness. Mean reversion (§3.9, §10.3) wants 3-5: the signal is
#: short-lived and over-smoothing destroys it. Fundamentals (§3.3) update
#: quarterly, so 6-10 costs nothing.
#:
#: neutralization — SUBINDUSTRY is tightest and isolates stock-specific alpha,
#: which is what reversion and pairs-style signals trade (§3.8, §3.9). MARKET
#: is loosest and lets sector rotation through, which is where trend-following
#: earns (§3.1, §4.1). INDUSTRY sits between, for multifactor and value (§3.6).
#:
#: truncation — 0.05 is conservative and reduces CONCENTRATED_WEIGHT failures
#: on high-turnover or sparse signals; 0.10 allows stronger bets and suits
#: slow-moving fundamentals with good coverage.
REGIMES: dict[str, dict] = {
    "balanced": {"neutralization": "SUBINDUSTRY", "decay": 6, "truncation": 0.08},
    "momentum": {"neutralization": "MARKET", "decay": 10, "truncation": 0.05},
    "reversion": {"neutralization": "SUBINDUSTRY", "decay": 4, "truncation": 0.08},
    "value": {"neutralization": "INDUSTRY", "decay": 8, "truncation": 0.10},
}


# --------------------------------------------------------------------------
# Quality gate
# --------------------------------------------------------------------------


@dataclass
class GateThresholds:
    """Local thresholds applied on top of BRAIN's own IS checks.

    BRAIN's ``/alphas/{id}/check`` is authoritative for submission. These
    thresholds are our own pre-filter so we do not waste check calls or daily
    submission quota on alphas that obviously will not clear.
    """

    min_sharpe: float = field(default_factory=lambda: _env_float("WQO_MIN_SHARPE", 1.25))
    min_fitness: float = field(
        default_factory=lambda: _env_float("WQO_MIN_FITNESS", 1.0)
    )
    min_turnover: float = field(
        default_factory=lambda: _env_float("WQO_MIN_TURNOVER", 0.01)
    )
    max_turnover: float = field(
        default_factory=lambda: _env_float("WQO_MAX_TURNOVER", 0.70)
    )
    max_self_correlation: float = field(
        default_factory=lambda: _env_float("WQO_MAX_SELF_CORR", 0.70)
    )
    max_prod_correlation: float = field(
        default_factory=lambda: _env_float("WQO_MAX_PROD_CORR", 0.70)
    )
    #: Peak-to-trough decline in cumulative PnL.
    max_drawdown: float = field(
        default_factory=lambda: _env_float("WQO_MAX_DRAWDOWN", 0.10)
    )
    #: Sub-universe Sharpe must be at least this fraction of the main Sharpe.
    min_subuniverse_ratio: float = field(
        default_factory=lambda: _env_float("WQO_MIN_SUBUNIVERSE_RATIO", 0.75)
    )
    #: An alpha over the self-correlation limit is still eligible if its Sharpe
    #: beats the alpha it correlates with by this margin.
    self_correlation_sharpe_exemption: float = field(
        default_factory=lambda: _env_float("WQO_SELF_CORR_EXEMPTION", 0.10)
    )


PACING = Pacing()
BUDGET = Budget()
GATE = GateThresholds()
