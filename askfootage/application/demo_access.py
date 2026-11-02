"""Demo access code check: the code is verified elsewhere; this limits wrong guesses.

This is a demo gate for the UI only. It does not protect footage; the rest of the API is not
authenticated. The limiter keeps its counts in memory, keyed by an opaque client string, and
never sees or keeps a submitted code.

Assumptions: one server process (counts are not shared between processes or restarts) and no
reverse proxy: the client is the socket address, and X-Forwarded-For is deliberately ignored
because a client could forge it. Behind a shared proxy all users would share one address; the
global cap (MAX_TOTAL_FAILED_ATTEMPTS a window) bounds guessing across all sources either way.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

CodeVerifier = Callable[[str], bool]
"""Says whether a 6-digit code is a valid, unrevoked demo access code."""

MAX_FAILED_ATTEMPTS = 5
"""Wrong codes one client may send per window before it is refused."""
WINDOW_SECONDS = 60.0
"""The length of the sliding window."""
MAX_TOTAL_FAILED_ATTEMPTS = 50
"""Wrong codes all clients together may send per window before everyone is refused."""
_MAX_CLIENTS = 10_000


def no_valid_codes(code: str) -> bool:
    """The verifier used when no code store is configured: every code is refused."""
    return False


class FailedAttemptLimiter:
    """Caps wrong codes: per client and across all clients, in any WINDOW_SECONDS. Thread-safe.

    An attempt is reserved (counted as a failure) in the same locked step that decides whether
    the client is locked out, before the code is looked at; a valid code then releases its
    reservation. So parallel guesses cannot all slip past the check.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        max_failures: int = MAX_FAILED_ATTEMPTS,
        window: float = WINDOW_SECONDS,
        max_total_failures: int = MAX_TOTAL_FAILED_ATTEMPTS,
    ) -> None:
        """Count attempts with `clock` (seconds, monotonic)."""
        self._clock = clock
        self._max = max_failures
        self._max_total = max_total_failures
        self._window = window
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._total: deque[float] = deque()
        self._lock = threading.Lock()

    def reserve(self, client: str) -> float:
        """Count an attempt for `client` now and return its token.

        Raises TooManyAttemptsError (counting nothing) when the client or everyone together
        is at the cap. Lockout decision and reservation are one locked step.
        """
        with self._lock:
            now = self._clock()
            if len(self._failures) >= _MAX_CLIENTS and client not in self._failures:
                self._forget_expired(now)
            recent = self._trim(client, now)
            while self._total and self._total[0] <= now - self._window:
                self._total.popleft()
            waits = []
            if len(recent) >= self._max:
                waits.append(recent[0])
            if len(self._total) >= self._max_total:
                waits.append(self._total[0])
            if waits:
                raise TooManyAttemptsError(max(1, math.ceil(max(waits) + self._window - now)))
            recent.append(now)
            self._total.append(now)
            return now

    def release(self, client: str, token: float) -> None:
        """Give back the attempt reserved with `token` (the code turned out valid)."""
        with self._lock:
            for attempts in (self._failures.get(client), self._total):
                if attempts is not None and token in attempts:
                    attempts.remove(token)

    def _trim(self, client: str, now: float) -> deque[float]:
        recent = self._failures[client]
        while recent and recent[0] <= now - self._window:
            recent.popleft()
        return recent

    def _forget_expired(self, now: float) -> None:
        for client in list(self._failures):
            if not self._trim(client, now):
                del self._failures[client]


class TooManyAttemptsError(Exception):
    """The client sent too many wrong codes; try again in `retry_after` seconds."""

    def __init__(self, retry_after: int) -> None:
        """Remember how long to wait."""
        super().__init__("too many attempts")
        self.retry_after = retry_after


def check_demo_code(
    verify: CodeVerifier, limiter: FailedAttemptLimiter, client: str, code: str
) -> bool:
    """Whether `code` is valid for `client`. Raises TooManyAttemptsError when locked out.

    The attempt is reserved first, so a locked-out client or a busy server is refused before
    the code is looked at. A valid code (or a verifier that fails) gives the attempt back, so
    only wrong codes count.
    """
    token = limiter.reserve(client)
    try:
        valid = verify(code)
    except BaseException:
        limiter.release(client, token)
        raise
    if valid:
        limiter.release(client, token)
    return valid
