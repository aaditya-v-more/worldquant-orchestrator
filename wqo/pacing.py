"""Request pacing: interval throttling, Retry-After handling, and backoff.

The goal is to be a well-behaved API client. Two rules do most of the work:

1. Never issue two requests closer together than ``min_interval`` (+ jitter).
2. When the server sends ``Retry-After``, sleep exactly that long. The server
   is telling us its cadence; guessing a shorter one is how you earn a 429.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Optional

from .config import Pacing

#: HTTP statuses worth retrying. 429 is rate limiting; 5xx are transient.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class RateGovernor:
    """Thread-safe pacer shared by every request in a process."""

    def __init__(self, pacing: Pacing, *, sleep=time.sleep, clock=time.monotonic):
        self.pacing = pacing
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait_turn(self) -> float:
        """Block until this caller is allowed to issue a request.

        Returns the number of seconds actually slept, which is useful in tests
        and in the debug log.
        """
        with self._lock:
            now = self._clock()
            delay = max(0.0, self._next_allowed - now)
            gap = self.pacing.min_interval + random.uniform(0.0, self.pacing.jitter)
            self._next_allowed = max(now, self._next_allowed) + gap
        if delay > 0:
            self._sleep(delay)
        return delay

    def backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with full jitter.

        ``attempt`` is 1-based. Full jitter (a uniform draw over the whole
        window rather than a fixed exponential) is what keeps concurrent
        workers from retrying in lockstep after a shared failure.
        """
        window = self.pacing.backoff_base ** max(0, attempt - 1)
        window = min(window, self.pacing.backoff_max)
        return random.uniform(0.0, window)

    def sleep_backoff(self, attempt: int) -> float:
        delay = self.backoff_delay(attempt)
        self._sleep(delay)
        return delay

    def retry_after_seconds(self, response, default: Optional[float] = None) -> float:
        """Read ``Retry-After`` off a response, falling back to a default."""
        if default is None:
            default = self.pacing.default_retry_after
        raw = response.headers.get("Retry-After")
        if raw is None:
            return default
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return default
        # A zero/negative Retry-After means "done, stop polling"; callers check
        # the body for completion, so surface it verbatim rather than clamping
        # it up to the default.
        return max(0.0, value)

    def sleep_retry_after(self, response, default: Optional[float] = None) -> float:
        delay = self.retry_after_seconds(response, default)
        if delay > 0:
            self._sleep(delay)
        return delay


def is_retryable(response) -> bool:
    return response.status_code in RETRYABLE_STATUSES
