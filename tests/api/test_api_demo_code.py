"""POST /api/auth/demo-code: the demo access code gate, with codes made inside each test.

No code is hard-coded: every valid code comes from SqliteAccessCodeStore.create_code() on a
temporary database. Wrong codes are chosen to differ from the valid one.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from api_fakes import InMemoryLibrary
from api_support import FAKE_KEY, assert_error, build_app
from fastapi.testclient import TestClient

from askfootage.adapters.sqlite.access_codes import SqliteAccessCodeStore
from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.application.demo_access import (
    FailedAttemptLimiter,
    TooManyAttemptsError,
    check_demo_code,
)
from askfootage.interfaces.api.app import code_verifier_of, create_app
from askfootage.interfaces.real_clips import create_app as create_real_app
from askfootage.settings import Settings

URL = "/api/auth/demo-code"
INVALID = "That code is not valid."


def wrong_for(code: str) -> str:
    """A 6-digit code that is not `code`."""
    return f"{(int(code) + 1) % 10**6:06d}"


class Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def library(tmp_path: Path) -> SqliteLibraryStore:
    return SqliteLibraryStore(tmp_path / "codes.sqlite")


@pytest.fixture
def code(library: SqliteLibraryStore) -> str:
    return SqliteAccessCodeStore(library).create_code("tests").code


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def gated_client(
    store: InMemoryLibrary,
    fake_settings: Settings,
    videos_dir: Path,
    library: SqliteLibraryStore,
    code: str,
    clock: Clock,
) -> TestClient:
    app = build_app(
        store,
        fake_settings,
        videos_dir,
        verify_demo_code=code_verifier_of(library),
        code_limiter=FailedAttemptLimiter(clock=clock),
    )
    return TestClient(app)


def test_a_valid_code_is_accepted_without_a_token(gated_client: TestClient, code: str) -> None:
    response = gated_client.post(URL, json={"code": code})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "set-cookie" not in response.headers
    assert "authorization" not in response.headers


def test_a_wrong_code_is_401_with_the_generic_message(gated_client: TestClient, code: str) -> None:
    response = gated_client.post(URL, json={"code": wrong_for(code)})
    assert assert_error(response, 401, "invalid_demo_code") == INVALID


def test_a_revoked_code_gets_the_same_401(
    gated_client: TestClient, library: SqliteLibraryStore, code: str
) -> None:
    store = SqliteAccessCodeStore(library)
    store.revoke_code(store.list_codes()[0].id)
    revoked = gated_client.post(URL, json={"code": code})
    never_existed = gated_client.post(URL, json={"code": wrong_for(code)})
    assert assert_error(revoked, 401, "invalid_demo_code") == INVALID
    assert revoked.json() == never_existed.json()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"code": ""},
        {"code": "12345"},
        {"code": "1234567"},
        {"code": "12345a"},
        {"code": " 12345"},
        {"code": "１２３４５６"},  # fullwidth digits
        {"code": 123456},
        {"code": None},
        {"code": "123456", "extra": 1},
        [],
    ],
)
def test_a_bad_format_is_422_and_does_not_echo_the_input(
    gated_client: TestClient, body: object
) -> None:
    response = gated_client.post(URL, json=body)
    message = assert_error(response, 422, "validation_error")
    assert "123456" not in response.text and "12345a" not in response.text
    assert message


def test_bad_format_does_not_count_as_a_failed_attempt(gated_client: TestClient, code: str) -> None:
    for _ in range(10):
        assert gated_client.post(URL, json={"code": "12"}).status_code == 422
    assert gated_client.post(URL, json={"code": code}).status_code == 200


def test_a_body_that_is_not_json_is_422(gated_client: TestClient) -> None:
    response = gated_client.post(URL, content=b"code=123456")
    assert_error(response, 422, "validation_error")


def test_the_sixth_attempt_in_a_minute_is_429_even_with_the_right_code(
    gated_client: TestClient, code: str
) -> None:
    wrong = wrong_for(code)
    for _ in range(5):
        assert gated_client.post(URL, json={"code": wrong}).status_code == 401
    refused = gated_client.post(URL, json={"code": code})
    assert_error(refused, 429, "too_many_attempts")
    assert 1 <= int(refused.headers["retry-after"]) <= 60


def test_the_lock_lifts_after_the_minute(gated_client: TestClient, code: str, clock: Clock) -> None:
    for _ in range(5):
        gated_client.post(URL, json={"code": wrong_for(code)})
    assert gated_client.post(URL, json={"code": code}).status_code == 429
    clock.now += 61
    assert gated_client.post(URL, json={"code": code}).status_code == 200


def test_successes_do_not_count_toward_the_limit(gated_client: TestClient, code: str) -> None:
    for _ in range(12):
        assert gated_client.post(URL, json={"code": code}).status_code == 200


def test_failures_are_counted_per_client(
    store: InMemoryLibrary,
    fake_settings: Settings,
    videos_dir: Path,
    library: SqliteLibraryStore,
    code: str,
) -> None:
    app = build_app(store, fake_settings, videos_dir, verify_demo_code=code_verifier_of(library))
    with TestClient(app, client=("10.0.0.1", 1)) as first:
        for _ in range(5):
            first.post(URL, json={"code": wrong_for(code)})
        assert first.post(URL, json={"code": code}).status_code == 429
    with TestClient(app, client=("10.0.0.2", 1)) as second:
        assert second.post(URL, json={"code": code}).status_code == 200


def test_a_forwarded_header_cannot_dodge_the_limit(gated_client: TestClient, code: str) -> None:
    for number in range(5):
        gated_client.post(
            URL, json={"code": wrong_for(code)}, headers={"X-Forwarded-For": f"1.2.3.{number}"}
        )
    refused = gated_client.post(URL, json={"code": code}, headers={"X-Forwarded-For": "9.9.9.9"})
    assert refused.status_code == 429


def test_without_a_code_store_no_code_is_valid(client: TestClient) -> None:
    assert_error(client.post(URL, json={"code": "123456"}), 401, "invalid_demo_code")


def test_the_code_and_the_key_never_reach_a_response_or_the_log(
    gated_client: TestClient, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    wrong = wrong_for(code)
    responses = [
        gated_client.post(URL, json={"code": code}),
        gated_client.post(URL, json={"code": wrong}),
        gated_client.post(URL, json={"code": "12"}),
    ]
    for _ in range(5):
        responses.append(gated_client.post(URL, json={"code": wrong}))
    for response in responses:
        text = response.text + str(dict(response.headers))
        assert code not in text and wrong not in text and FAKE_KEY not in text
    assert code not in caplog.text and wrong not in caplog.text


def test_a_failing_verifier_is_a_500_without_details(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    def broken(_code: str) -> bool:
        raise RuntimeError("secret detail D:\\server\\path")

    app = build_app(store, fake_settings, videos_dir, verify_demo_code=broken)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(URL, json={"code": "123456"})
    assert_error(response, 500, "internal_error")
    assert "secret detail" not in response.text and "server" not in response.text


def test_the_route_allows_only_post_and_cors_only_the_ui_origin(gated_client: TestClient) -> None:
    assert_error(gated_client.get(URL), 405, "method_not_allowed")
    other = gated_client.post(URL, json={"code": "000000"}, headers={"Origin": "https://x.example"})
    assert "access-control-allow-origin" not in other.headers


def test_parallel_guesses_verify_at_most_five_wrong_codes_per_client() -> None:
    verified = 0
    count_lock = threading.Lock()

    def verify(_code: str) -> bool:
        nonlocal verified
        with count_lock:
            verified += 1
        return False

    limiter = FailedAttemptLimiter(clock=lambda: 1000.0)
    start = threading.Barrier(40)
    refused: list[int] = []

    def guess() -> None:
        start.wait()
        try:
            check_demo_code(verify, limiter, "one-client", "000000")
        except TooManyAttemptsError:
            with count_lock:
                refused.append(1)

    threads = [threading.Thread(target=guess) for _ in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert verified == 5
    assert len(refused) == 35


def test_a_valid_code_gives_its_attempt_back() -> None:
    limiter = FailedAttemptLimiter(clock=lambda: 1000.0)
    for _ in range(20):
        assert check_demo_code(lambda _c: True, limiter, "c", "000000") is True
    assert check_demo_code(lambda _c: False, limiter, "c", "000000") is False


def test_a_crashing_verifier_does_not_use_up_attempts() -> None:
    limiter = FailedAttemptLimiter(clock=lambda: 1000.0)

    def broken(_code: str) -> bool:
        raise RuntimeError("boom")

    for _ in range(10):
        with pytest.raises(RuntimeError):
            check_demo_code(broken, limiter, "c", "000000")
    assert check_demo_code(lambda _c: False, limiter, "c", "000000") is False


def test_all_clients_together_are_capped_at_fifty_wrong_codes_a_minute() -> None:
    clock = Clock()
    limiter = FailedAttemptLimiter(clock=clock)
    for number in range(50):
        assert check_demo_code(lambda _c: False, limiter, f"client-{number}", "000000") is False
    with pytest.raises(TooManyAttemptsError) as refused:
        check_demo_code(lambda _c: True, limiter, "client-new", "000000")
    assert 1 <= refused.value.retry_after <= 60
    clock.now += 61
    assert check_demo_code(lambda _c: True, limiter, "client-new", "000000") is True


def test_the_global_cap_answers_429_over_http(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    limiter = FailedAttemptLimiter(clock=Clock(), max_failures=100, max_total_failures=3)
    app = build_app(
        store, fake_settings, videos_dir, verify_demo_code=lambda _c: False, code_limiter=limiter
    )
    with TestClient(app) as client:
        for _ in range(3):
            assert client.post(URL, json={"code": "123456"}).status_code == 401
        refused = client.post(URL, json={"code": "123456"})
    assert_error(refused, 429, "too_many_attempts")
    assert int(refused.headers["retry-after"]) >= 1


# --- The two real app factories ---------------------------------------------------------------


def test_default_demo_app_checks_codes_in_demo_sqlite(
    fake_settings: Settings, videos_dir: Path
) -> None:
    data_dir = fake_settings.data_dir
    data_dir.mkdir(parents=True)
    created = SqliteAccessCodeStore(SqliteLibraryStore(data_dir / "demo.sqlite")).create_code("t")
    app = create_app(fake_settings, videos_dir=videos_dir)
    with TestClient(app) as client:
        assert client.post(URL, json={"code": created.code}).json() == {"ok": True}
        assert_error(
            client.post(URL, json={"code": wrong_for(created.code)}), 401, "invalid_demo_code"
        )


def test_default_demo_app_with_no_codes_answers_401(
    fake_settings: Settings, videos_dir: Path
) -> None:
    app = create_app(fake_settings, videos_dir=videos_dir)
    with TestClient(app) as client:
        assert_error(client.post(URL, json={"code": "123456"}), 401, "invalid_demo_code")


def test_real_clips_app_checks_codes_in_the_real_library(tmp_path: Path) -> None:
    data_dir = tmp_path / "real"
    data_dir.mkdir()
    library = SqliteLibraryStore(data_dir / "library.sqlite")
    created = SqliteAccessCodeStore(library).create_code("t")
    app = create_real_app(data_dir, tmp_path / "videos")
    with TestClient(app) as client:
        assert client.post(URL, json={"code": created.code}).json() == {"ok": True}
        assert_error(
            client.post(URL, json={"code": wrong_for(created.code)}), 401, "invalid_demo_code"
        )


def test_a_missing_table_means_no_valid_code_not_a_crash(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "old.sqlite"
    library = SqliteLibraryStore(path)
    created = SqliteAccessCodeStore(library).create_code("t")
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE demo_access_codes")
    verify: Callable[[str], bool] = code_verifier_of(library)
    with caplog.at_level(logging.ERROR):
        assert verify(created.code) is False
    assert created.code not in caplog.text
