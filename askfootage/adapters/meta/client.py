"""Live HTTP transport for the Meta Model API.

MetaHttpClient POSTs a MetaRequest to `settings.api_base_url + request.path` with the API
key as a Bearer token, and returns the reply unparsed as a RawResponse.

Retries are deliberately narrow, because a failed paid call may still be billed. Only two
failures are retried, as neither can have done paid work:
- HTTP 429, where the server refused the request, and
- failures before the request left this machine: no connection, or no free one in the pool.
Each is retried up to MAX_RETRIES times, waiting 1, 2 then 4 seconds, or what a numeric
Retry-After header asks for (at most 30 s). Every other error status, and any failure once
the request may have reached the server (a read timeout, say), is raised at once.

The key is read from Settings at send time and never stored here. It is scrubbed from reply
bodies and error messages, and no httpx exception (whose request still carries the
Authorization header) is attached to an error raised here.
"""

import math
import time
from collections.abc import Callable

import httpx

from askfootage.adapters.meta.transport import (
    MetaApiError,
    MetaConnectionError,
    MetaRequest,
    RawResponse,
)
from askfootage.settings import Settings

CONNECT_TIMEOUT_S = 10.0
"""Seconds allowed to open a connection to the Meta API."""
WRITE_TIMEOUT_S = 60.0
"""Seconds allowed for each chunk of the request body, uploads included, to be sent."""
READ_TIMEOUT_S = 300.0
"""Seconds allowed between chunks of the reply; a long model run answers slowly."""
POOL_TIMEOUT_S = 10.0
"""Seconds allowed to wait for a free connection from the pool."""

RETRY_WAITS_S = (1.0, 2.0, 4.0)
"""Seconds to wait before each retry, unless a numeric Retry-After header says otherwise."""
MAX_RETRIES = len(RETRY_WAITS_S)
"""Retries after the first attempt, for HTTP 429 and failures before the request left."""
RETRY_AFTER_CAP_S = 30.0
"""Longest wait honoured from a Retry-After header."""

_TIMEOUT = httpx.Timeout(
    connect=CONNECT_TIMEOUT_S, write=WRITE_TIMEOUT_S, read=READ_TIMEOUT_S, pool=POOL_TIMEOUT_S
)
# Failures before the request left this machine, so a retry cannot be billed twice.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_REDACTED = "[REDACTED]"


class MetaHttpClient:
    """Sends MetaRequests to the live Meta API over HTTPS; implements the Transport protocol.

    Pass `http` to supply your own httpx.Client (tests pass one built on
    httpx.MockTransport) and `sleep` to control the waits between retries. The default
    httpx.Client ignores proxy and certificate variables in the environment, because only
    askfootage.settings reads the environment.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._http = http if http is not None else httpx.Client(timeout=_TIMEOUT, trust_env=False)
        self._sleep = sleep

    def send(self, request: MetaRequest) -> RawResponse:
        """POST `request` and return the reply as raw text, retrying only what cannot double-bill.

        Raises MissingApiKeyError, before anything is sent, when no key is configured;
        MetaApiError for an error status, including a 429 that outlasts every retry; and
        MetaConnectionError when the API cannot be reached.
        """
        url = self._settings.api_base_url + request.path
        for wait in RETRY_WAITS_S:
            reply = self._attempt(url, request)
            if reply is not None and reply.status_code != 429:
                return self._raw_or_raise(reply)
            self._sleep(wait if reply is None else _retry_after(reply, default=wait))
        reply = self._attempt(url, request)
        if reply is None:
            raise MetaConnectionError(
                f"could not connect to the Meta API in {MAX_RETRIES + 1} tries"
            )
        return self._raw_or_raise(reply)

    def _attempt(self, url: str, request: MetaRequest) -> httpx.Response | None:
        """Make one POST. None means it failed before the request left, so a retry is safe."""
        try:
            return self._post(url, request)
        except _NOT_SENT:
            return None
        except httpx.HTTPError as error:
            failure = type(error).__name__
        # Raised outside the except block, so the httpx exception is not attached as context.
        raise MetaConnectionError(
            f"Meta API call failed ({failure}) after the request may have reached the server; "
            "not retried, so it cannot be billed twice"
        ) from None

    def _post(self, url: str, request: MetaRequest) -> httpx.Response:
        # The header is built inline, so no local variable in these frames holds the key.
        if request.upload is None:
            return self._http.post(
                url, json=request.json_body, headers=self._auth_header(), timeout=_TIMEOUT
            )
        with request.upload.path.open("rb") as file:  # reopened for every attempt
            return self._http.post(
                url,
                files={"file": (request.upload.path.name, file)},
                data={"purpose": request.upload.purpose},
                headers=self._auth_header(),
                timeout=_TIMEOUT,
            )

    def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._settings.require_api_key()}"}

    def _raw_or_raise(self, reply: httpx.Response) -> RawResponse:
        body = reply.text.replace(self._settings.require_api_key(), _REDACTED)
        if reply.is_success:
            return RawResponse(reply.status_code, body)
        raise MetaApiError(reply.status_code, body)


def _retry_after(reply: httpx.Response, *, default: float) -> float:
    """Seconds a 429 asks us to wait: a numeric Retry-After, at most 30 s, else `default`."""
    try:
        seconds = float(reply.headers.get("Retry-After", ""))
    except ValueError:
        return default
    if not math.isfinite(seconds) or seconds < 0:
        return default
    return min(seconds, RETRY_AFTER_CAP_S)
