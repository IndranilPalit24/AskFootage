"""Behaviour of MetaHttpClient, the live HTTP transport, tested fully offline.

Every test routes the client through httpx.MockTransport, so nothing reaches the network,
and injects a fake `sleep` that records each wait instead of waiting. The only key used is
the fake "test-key-not-real". Simulated network failures quote it back on purpose, to
prove it is scrubbed from everything the client returns or raises.
"""

import json
import logging
import traceback
from pathlib import Path
from typing import Any

import httpx
import pytest

from askfootage.adapters.meta.client import MetaHttpClient
from askfootage.adapters.meta.transport import (
    FileUpload,
    MetaApiError,
    MetaConnectionError,
    MetaError,
    MetaRequest,
    RawResponse,
)
from askfootage.settings import MissingApiKeyError, Settings, load_settings

FAKE_KEY = "test-key-not-real"
BASE_URL = "https://api.example.test/v1"
ENV_NAMES = (
    "META_API_KEY",
    "META_API_BASE_URL",
    "MAX_RUN_COST_USD",
    "DATA_DIR",
    "ASKFOOTAGE_DEMO",
)
REQUEST = MetaRequest("/responses", json_body={"model": "muse-test", "input": "hello"})
ECHOED_KEY_BODY = f'{{"error": "invalid token Bearer {FAKE_KEY}"}}'

Reply = httpx.Response | type[httpx.TransportError]


class FakeMeta:
    """Plays the Meta API from a script of replies and failures, and keeps every request."""

    def __init__(self, *script: Reply) -> None:
        self._script = list(script)
        self.requests: list[httpx.Request] = []
        self.waits: list[float] = []

    def client(self, settings: Settings) -> MetaHttpClient:
        """A MetaHttpClient wired to this fake, with a sleep that only records the wait."""
        http = httpx.Client(transport=httpx.MockTransport(self._handle))
        return MetaHttpClient(settings, http=http, sleep=self.waits.append)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self._script.pop(0)
        if isinstance(reply, httpx.Response):
            return reply
        # A hostile failure: its message quotes the Authorization header back.
        raise reply(f"simulated failure, {request.headers['Authorization']}", request=request)


@pytest.fixture(autouse=True)
def _no_askfootage_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("META_API_KEY", FAKE_KEY)
    monkeypatch.setenv("META_API_BASE_URL", BASE_URL)
    return load_settings(env_file=None)


@pytest.fixture
def keyless_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("META_API_BASE_URL", BASE_URL)
    return load_settings(env_file=None)


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake video bytes")
    return clip


def _failure(meta: FakeMeta, settings: Settings, request: MetaRequest = REQUEST) -> MetaError:
    with pytest.raises(MetaError) as excinfo:
        meta.client(settings).send(request)
    return excinfo.value


# --- Requests ---------------------------------------------------------------------------------


def test_sends_the_key_as_a_bearer_token(settings: Settings) -> None:
    meta = FakeMeta(httpx.Response(200))
    meta.client(settings).send(REQUEST)
    assert meta.requests[0].headers["Authorization"] == f"Bearer {FAKE_KEY}"


def test_posts_to_the_base_url_joined_with_the_request_path(settings: Settings) -> None:
    meta = FakeMeta(httpx.Response(200))
    meta.client(settings).send(REQUEST)
    assert meta.requests[0].method == "POST"
    assert str(meta.requests[0].url) == "https://api.example.test/v1/responses"


def test_sends_the_json_body_as_given(settings: Settings) -> None:
    meta = FakeMeta(httpx.Response(200))
    meta.client(settings).send(REQUEST)
    assert meta.requests[0].headers["Content-Type"] == "application/json"
    assert json.loads(meta.requests[0].content) == {"model": "muse-test", "input": "hello"}


def test_uploads_a_file_as_multipart_with_its_purpose(settings: Settings, clip: Path) -> None:
    meta = FakeMeta(httpx.Response(200))
    meta.client(settings).send(MetaRequest("/files", upload=FileUpload(clip, "user_data")))
    request = meta.requests[0]
    assert str(request.url) == "https://api.example.test/v1/files"
    assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="purpose"\r\n\r\nuser_data\r\n' in request.content
    assert b'name="file"; filename="clip.mp4"' in request.content
    assert b"fake video bytes" in request.content


def test_every_request_carries_the_four_timeouts(settings: Settings) -> None:
    meta = FakeMeta(httpx.Response(200))
    meta.client(settings).send(REQUEST)
    timeouts = meta.requests[0].extensions["timeout"]
    assert timeouts == {"connect": 10.0, "write": 60.0, "read": 300.0, "pool": 10.0}


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({}, id="neither"),
        pytest.param(
            {"json_body": {}, "upload": FileUpload(Path("x.mp4"), "user_data")}, id="both"
        ),
    ],
)
def test_a_request_needs_exactly_one_of_json_body_or_upload(fields: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        MetaRequest("/responses", **fields)


@pytest.mark.parametrize("path", ["responses", "", ".evil.example/responses"])
def test_a_request_path_must_start_with_a_slash(path: str) -> None:
    # Without the slash the path would run into the base URL's host name.
    with pytest.raises(ValueError, match="must start with '/'"):
        MetaRequest(path, json_body={})


# --- Replies ----------------------------------------------------------------------------------


def test_a_success_returns_the_status_and_the_raw_body(settings: Settings) -> None:
    meta = FakeMeta(httpx.Response(201, text='{"id": "resp_1"}'))
    assert meta.client(settings).send(REQUEST) == RawResponse(201, '{"id": "resp_1"}')


def test_a_streamed_reply_comes_back_whole_as_raw_text(settings: Settings) -> None:
    chunks = [b'event: delta\ndata: {"text": "hel"}\n\n', b'event: delta\ndata: {"text": "lo"}\n\n']
    streamed = httpx.Response(
        200, headers={"Content-Type": "text/event-stream"}, content=iter(chunks)
    )
    meta = FakeMeta(streamed)
    assert meta.client(settings).send(REQUEST).body == b"".join(chunks).decode()


# --- The key ----------------------------------------------------------------------------------


def test_the_key_is_read_when_sending_not_when_the_client_is_built(
    keyless_settings: Settings,
) -> None:
    meta = FakeMeta(httpx.Response(200))
    client = meta.client(keyless_settings)  # building a client without a key works

    with pytest.raises(MissingApiKeyError):
        client.send(REQUEST)
    assert meta.requests == []  # and nothing was sent


@pytest.mark.parametrize(
    "script",
    [
        pytest.param([httpx.Response(400, text=ECHOED_KEY_BODY)], id="400-echo"),
        pytest.param([httpx.Response(500, text=ECHOED_KEY_BODY)], id="500-echo"),
        pytest.param([httpx.Response(429, text=ECHOED_KEY_BODY) for _ in range(4)], id="429-echo"),
        pytest.param([httpx.ConnectError] * 4, id="connect-error"),
        pytest.param([httpx.ReadTimeout], id="read-timeout"),
    ],
)
def test_the_key_never_appears_in_a_raised_error(settings: Settings, script: list[Reply]) -> None:
    error = _failure(FakeMeta(*script), settings)
    full_report = "".join(traceback.format_exception(error))
    for text in (str(error), repr(error), full_report, getattr(error, "body_excerpt", "")):
        assert FAKE_KEY not in text


def test_a_success_body_that_echoes_the_key_comes_back_scrubbed(settings: Settings) -> None:
    meta = FakeMeta(httpx.Response(200, text=f'{{"debug": "{FAKE_KEY}"}}'))
    assert meta.client(settings).send(REQUEST).body == '{"debug": "[REDACTED]"}'


def test_a_key_cut_by_the_excerpt_limit_leaves_no_fragment(settings: Settings) -> None:
    # Scrub first, then cut: cutting first would leave the key's opening characters.
    meta = FakeMeta(httpx.Response(400, text="x" * 295 + FAKE_KEY + "y" * 50))
    error = _failure(meta, settings)
    assert isinstance(error, MetaApiError)
    assert FAKE_KEY[:5] not in error.body_excerpt


def test_a_connection_error_does_not_carry_the_httpx_exception(settings: Settings) -> None:
    # An httpx exception keeps its request, and the request keeps the Authorization header.
    error = _failure(FakeMeta(httpx.ReadTimeout), settings)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_the_key_never_reaches_the_logs(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    meta = FakeMeta(httpx.Response(429), httpx.Response(500, text=ECHOED_KEY_BODY))
    _failure(meta, settings)
    assert caplog.records  # httpx did log the calls, so this check is not vacuous
    assert FAKE_KEY not in caplog.text


def test_the_key_never_appears_in_the_client_repr(settings: Settings) -> None:
    assert FAKE_KEY not in repr(FakeMeta().client(settings))


def test_the_default_http_client_ignores_proxy_and_certificate_variables(
    settings: Settings,
) -> None:
    # Only askfootage.settings may read the environment; httpx would read HTTPS_PROXY & co.
    client = MetaHttpClient(settings)
    assert client._http.trust_env is False


# --- Error statuses ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [307, 400, 401, 404, 500, 502, 503])
def test_other_error_statuses_raise_at_once_without_a_retry(
    settings: Settings, status: int
) -> None:
    # A failed paid call may still be billed, so it is never repeated automatically.
    meta = FakeMeta(httpx.Response(status, text="nope"), httpx.Response(200))
    error = _failure(meta, settings)
    assert isinstance(error, MetaApiError)
    assert error.status == status
    assert len(meta.requests) == 1
    assert meta.waits == []


def test_an_api_error_carries_a_body_excerpt_of_at_most_300_characters(
    settings: Settings,
) -> None:
    error = _failure(FakeMeta(httpx.Response(400, text="e" * 1000)), settings)
    assert isinstance(error, MetaApiError)
    assert error.body_excerpt == "e" * 300
    assert "e" * 301 not in str(error)


# --- Retries: HTTP 429 ------------------------------------------------------------------------


def test_a_429_is_retried_once_after_one_second(settings: Settings) -> None:
    meta = FakeMeta(httpx.Response(429), httpx.Response(200, text="ok"))
    assert meta.client(settings).send(REQUEST).body == "ok"
    assert len(meta.requests) == 2
    assert meta.waits == [1.0]


def test_three_429s_then_a_success_waits_one_two_then_four_seconds(settings: Settings) -> None:
    meta = FakeMeta(*(httpx.Response(429) for _ in range(3)), httpx.Response(200, text="ok"))
    assert meta.client(settings).send(REQUEST).body == "ok"
    assert len(meta.requests) == 4
    assert meta.waits == [1.0, 2.0, 4.0]


def test_a_fourth_429_raises_an_api_error(settings: Settings) -> None:
    meta = FakeMeta(*(httpx.Response(429) for _ in range(4)), httpx.Response(200))
    error = _failure(meta, settings)
    assert isinstance(error, MetaApiError)
    assert error.status == 429
    assert len(meta.requests) == 4
    assert meta.waits == [1.0, 2.0, 4.0]


@pytest.mark.parametrize(("retry_after", "wait"), [("7", 7.0), ("0.5", 0.5), ("120", 30.0)])
def test_a_numeric_retry_after_is_honoured_up_to_thirty_seconds(
    settings: Settings, retry_after: str, wait: float
) -> None:
    meta = FakeMeta(httpx.Response(429, headers={"Retry-After": retry_after}), httpx.Response(200))
    meta.client(settings).send(REQUEST)
    assert meta.waits == [wait]


@pytest.mark.parametrize("retry_after", ["Tue, 27 Oct 2026 12:00:00 GMT", "-3", "nan", "inf"])
def test_an_unusable_retry_after_falls_back_to_the_normal_wait(
    settings: Settings, retry_after: str
) -> None:
    meta = FakeMeta(httpx.Response(429, headers={"Retry-After": retry_after}), httpx.Response(200))
    meta.client(settings).send(REQUEST)
    assert meta.waits == [1.0]


# --- Retries: connection failures -------------------------------------------------------------


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
def test_a_failure_before_the_request_left_is_retried(
    settings: Settings, failure: type[httpx.TransportError]
) -> None:
    meta = FakeMeta(failure, httpx.Response(200, text="ok"))
    assert meta.client(settings).send(REQUEST).body == "ok"
    assert meta.waits == [1.0]


def test_a_connection_failure_that_persists_raises_a_connection_error(settings: Settings) -> None:
    meta = FakeMeta(*[httpx.ConnectError] * 4, httpx.Response(200))
    assert isinstance(_failure(meta, settings), MetaConnectionError)
    assert len(meta.requests) == 4
    assert meta.waits == [1.0, 2.0, 4.0]


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.ReadError,
        httpx.WriteError,
        httpx.RemoteProtocolError,
    ],
)
def test_a_failure_after_the_request_may_have_been_sent_is_not_retried(
    settings: Settings, failure: type[httpx.TransportError]
) -> None:
    # The server may already be running (and billing) the call, so it is not sent again.
    meta = FakeMeta(failure, httpx.Response(200))
    assert isinstance(_failure(meta, settings), MetaConnectionError)
    assert len(meta.requests) == 1
    assert meta.waits == []


def test_a_retried_upload_sends_the_whole_file_again(settings: Settings, clip: Path) -> None:
    meta = FakeMeta(httpx.ConnectError, httpx.Response(200))
    meta.client(settings).send(MetaRequest("/files", upload=FileUpload(clip, "user_data")))
    assert b"fake video bytes" in meta.requests[1].content
