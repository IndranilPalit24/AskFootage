"""No secret, path or traceback ever leaves the API; CORS lets in the UI's dev origin only."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from api_fakes import FAKE_MP4, ExplodingLibrary, InMemoryLibrary
from api_support import FAKE_KEY, UI_ORIGIN, assert_error, build_app
from fastapi.testclient import TestClient

from askfootage.interfaces.api.body_limit import MAX_JSON_BODY_BYTES, BodyLimitMiddleware
from askfootage.settings import Settings

TRIANGLE = [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]]
# A camera stream password: checked when a camera is added, then dropped. Never sent back.
STREAM_PASSWORD = "pw-" + "never-shown-" * 2


def new_camera(**changes: Any) -> dict[str, Any]:
    """A valid CameraCreate body carrying STREAM_PASSWORD, with any field changed."""
    return {
        "name": "Side yard",
        "ip": "192.168.1.50",
        "username": "viewer",
        "password": STREAM_PASSWORD,
        "acknowledgeCost": True,
        **changes,
    }


# One request per operation, plus failing variants: (method, path, keyword arguments).
REQUESTS: list[tuple[str, str, dict[str, Any]]] = [
    ("GET", "/api/status", {}),
    ("GET", "/api/cameras", {}),
    ("POST", "/api/cameras", {"json": new_camera()}),
    ("POST", "/api/cameras", {"json": new_camera(name="LOADING dock")}),
    ("POST", "/api/cameras", {"json": new_camera(name="Bad ip", ip="not a host")}),
    ("POST", "/api/cameras", {"json": new_camera(name="Long", password=STREAM_PASSWORD * 5)}),
    ("GET", "/api/cameras/CAM-001", {}),
    ("GET", "/api/cameras/CAM-999", {}),
    ("PATCH", "/api/cameras/CAM-002", {"json": {"status": "standby"}}),
    ("DELETE", "/api/cameras/CAM-003", {}),
    ("GET", "/api/days?camera=CAM-001", {}),
    ("GET", "/api/days?camera=nope", {}),
    ("GET", "/api/days", {}),
    ("GET", "/api/recordings?day=2026-10-29&camera=CAM-001", {}),
    ("GET", "/api/recordings?day=bad&camera=CAM-001", {}),
    (
        "POST",
        "/api/recordings",
        {
            "files": {"file": ("c.mp4", FAKE_MP4, "video/mp4")},
            "data": {"day": "2026-10-30", "camera": "CAM-001"},
        },
    ),
    (
        "POST",
        "/api/recordings",
        {
            "files": {"file": ("c.mov", FAKE_MP4, "video/mp4")},
            "data": {"day": "2026-10-30", "camera": "CAM-001"},
        },
    ),
    ("GET", "/api/recordings/rec-1029-0600/video", {}),
    ("GET", "/api/recordings/rec-1029-0600/video", {"headers": {"Range": "bytes=0-3"}}),
    ("GET", "/api/recordings/rec-nope/video", {}),
    (
        "POST",
        "/api/search",
        {
            "json": {
                "question": "someone carrying a box",
                "day": "2026-10-29",
                "camera": "CAM-001",
            }
        },
    ),
    ("POST", "/api/search", {"json": {"question": " ", "day": "2026-10-29", "camera": "x"}}),
    ("GET", "/api/clips/clip-1029-104215", {}),
    ("GET", "/api/clips/clip-nope", {}),
    ("GET", "/api/zones", {}),
    ("POST", "/api/zones", {"json": {"camera": "CAM-001", "name": "Bay", "points": TRIANGLE}}),
    (
        "POST",
        "/api/zones",
        {"json": {"camera": "CAM-001", "name": "Exit lane", "points": TRIANGLE}},
    ),
    ("PUT", "/api/zones/zone-exit-lane", {"json": {"name": "Lane", "points": TRIANGLE}}),
    ("DELETE", "/api/zones/zone-loading-door", {}),
    ("GET", "/api/saved-clips", {}),
    ("POST", "/api/saved-clips", {"json": {"clipId": "clip-1029-104215", "note": "n"}}),
    ("POST", "/api/saved-clips", {"json": {"clipId": "clip-1029-104215"}}),
    ("PATCH", "/api/saved-clips/saved-nope", {"json": {"note": "n"}}),
    ("DELETE", "/api/saved-clips/saved-nope", {}),
    ("POST", "/api/recordings/rec-1030-1200/index", {}),
    ("POST", "/api/recordings/rec-nope/index", {}),
    ("GET", "/api/nowhere", {}),
    ("PUT", "/api/status", {}),
    ("GET", "/api/openapi.json", {}),
]


def _leaks(response: httpx.Response) -> list[str]:
    """Anything in the response that must never be sent: the key, a camera password, a path
    or a traceback."""
    head = "\n".join(f"{name}: {value}" for name, value in response.headers.items())
    texts = [head, response.content.decode("utf-8", errors="replace")]
    found = []
    needles = (
        FAKE_KEY,
        "sk-test",
        STREAM_PASSWORD,
        "Traceback",
        "demo.sqlite",
        "C:\\Users",
        "site-packages",
    )
    for needle in needles:
        if any(needle in text for text in texts):
            found.append(needle)
    return found


@pytest.fixture
def exploding_client(fake_settings: Settings, videos_dir: Path) -> Iterator[TestClient]:
    """A client whose stores raise an exception holding a path and the fake key."""
    store = ExplodingLibrary(FAKE_KEY)
    with TestClient(build_app(store, fake_settings, videos_dir)) as client:
        yield client


def test_the_fake_key_really_is_in_the_settings(fake_settings: Settings) -> None:
    assert fake_settings.require_api_key() == FAKE_KEY


def test_no_response_ever_holds_the_key_a_path_or_a_traceback(client: TestClient) -> None:
    statuses = set()
    for method, path, options in REQUESTS:
        response = client.request(method, path, **options)
        statuses.add(response.status_code)
        assert _leaks(response) == [], (method, path)
    assert {200, 201, 202, 204, 206, 404, 405, 409, 415, 422} <= statuses


def test_a_store_failure_is_a_bare_500_on_every_route(exploding_client: TestClient) -> None:
    failing = [
        (method, path, options)
        for method, path, options in REQUESTS
        if path not in ("/api/nowhere", "/api/openapi.json")
        and not (method == "PUT" and path == "/api/status")
    ]
    statuses = set()
    for method, path, options in failing:
        response = exploding_client.request(method, path, **options)
        statuses.add(response.status_code)
        assert _leaks(response) == [], (method, path)
        if path.endswith("/index"):
            # This build has no indexing backend: 503 before the store is ever asked.
            assert response.json() == {
                "error": {
                    "code": "indexing_not_configured",
                    "message": "Indexing is not configured in this build",
                }
            }
            assert response.status_code == 503
        elif response.status_code >= 500:
            assert response.status_code == 500
            assert response.json() == {
                "error": {"code": "internal_error", "message": "Something went wrong."}
            }
    assert 500 in statuses


def test_a_500_is_logged_with_the_key_redacted(
    exploding_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="askfootage.api"):
        response = exploding_client.get("/api/zones")
    assert_error(response, 500, "internal_error")
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "RuntimeError" in logged and "database locked" in logged
    assert FAKE_KEY not in logged
    assert "[redacted]" in logged


def test_an_unexpected_error_inside_a_use_case_is_500(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    def broken_ids(prefix: str) -> str:
        raise ZeroDivisionError(f"/srv/askfootage/{FAKE_KEY}")

    app = build_app(store, fake_settings, videos_dir, make_id=broken_ids)
    with TestClient(app) as client:
        response = client.post(
            "/api/zones", json={"camera": "CAM-001", "name": "Bay", "points": TRIANGLE}
        )
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Something went wrong."}
    }
    assert response.status_code == 500
    assert _leaks(response) == []


def test_status_never_shows_settings(client: TestClient) -> None:
    assert set(client.get("/api/status").json()) == {"demoMode"}


def test_status_does_not_depend_on_the_store(exploding_client: TestClient) -> None:
    assert exploding_client.get("/api/status").json() == {"demoMode": True}


# --- Camera passwords --------------------------------------------------------------------------


def test_a_camera_password_is_never_returned_stored_or_logged(
    client: TestClient,
    exploding_client: TestClient,
    store: InMemoryLibrary,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        responses = [
            client.post("/api/cameras", json=new_camera()),
            client.get("/api/cameras"),
            client.post("/api/cameras", json=new_camera(name="side YARD")),
            client.post("/api/cameras", json=new_camera(name="Other", ip="http://x/")),
            client.post("/api/cameras", json=new_camera(name="Long", password=STREAM_PASSWORD * 5)),
            exploding_client.post("/api/cameras", json=new_camera()),
        ]
    assert [response.status_code for response in responses] == [201, 200, 409, 422, 422, 500]
    added = responses[0].json()
    assert "password" not in added
    assert added["rtspUrlMasked"].startswith("rtsp://viewer:****@192.168.1.50:")
    for response in responses:
        assert _leaks(response) == [], response.request.url
    assert STREAM_PASSWORD not in repr(store.cameras)
    assert STREAM_PASSWORD not in caplog.text


# --- CORS -----------------------------------------------------------------------------------


def _preflight(client: TestClient, origin: str, method: str = "POST") -> httpx.Response:
    return client.options(
        "/api/search",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_a_preflight_from_the_ui_is_allowed(client: TestClient) -> None:
    response = _preflight(client, UI_ORIGIN)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == UI_ORIGIN
    allowed_methods = {
        m.strip() for m in response.headers["access-control-allow-methods"].split(",")
    }
    assert allowed_methods == {"GET", "POST", "PUT", "PATCH", "DELETE"}
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "content-type" in allowed_headers and "range" in allowed_headers
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "https://localhost:5173",
        "http://localhost:5173.evil.example",
        "null",
    ],
)
def test_a_preflight_from_another_origin_gets_no_cors_headers(
    client: TestClient, origin: str
) -> None:
    response = _preflight(client, origin)
    assert not any(name.startswith("access-control-") for name in response.headers)
    assert_error(response, 405, "method_not_allowed")


def test_a_preflight_for_a_method_not_allowed_gets_no_cors_headers(client: TestClient) -> None:
    response = _preflight(client, UI_ORIGIN, method="TRACE")
    assert "access-control-allow-origin" not in response.headers


def test_a_request_from_the_ui_carries_the_allow_origin_header(client: TestClient) -> None:
    response = client.get("/api/status", headers={"Origin": UI_ORIGIN})
    assert response.headers["access-control-allow-origin"] == UI_ORIGIN
    assert "access-control-allow-credentials" not in response.headers


def test_a_request_from_another_origin_gets_no_allow_origin_header(client: TestClient) -> None:
    response = client.get("/api/status", headers={"Origin": "http://evil.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_errors_and_500s_to_the_ui_carry_the_allow_origin_header(
    client: TestClient, exploding_client: TestClient
) -> None:
    not_found = client.get("/api/clips/clip-nope", headers={"Origin": UI_ORIGIN})
    assert not_found.headers["access-control-allow-origin"] == UI_ORIGIN
    failed = exploding_client.get("/api/zones", headers={"Origin": UI_ORIGIN})
    assert failed.status_code == 500
    assert failed.headers["access-control-allow-origin"] == UI_ORIGIN


# --- No identity features --------------------------------------------------------------------


def test_no_route_or_schema_mentions_faces_or_identities(client: TestClient) -> None:
    document = client.get("/api/openapi.json").text.lower()
    for word in ("face", "identity", "identify", "recogni", "person_id", "personid"):
        assert word not in document


# --- Request bodies are bounded (body_limit.py) ------------------------------------------------


def test_a_json_body_over_64_kib_is_refused_with_422(client: TestClient) -> None:
    question = "box " * (MAX_JSON_BODY_BYTES // 4)
    response = client.post(
        "/api/search", json={"question": question, "day": "2026-10-29", "camera": "CAM-001"}
    )
    assert assert_error(response, 422, "validation_error") == "body: is too large"


def test_a_chunked_json_body_over_the_limit_is_cut_off(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"note": "'
        for _ in range(MAX_JSON_BODY_BYTES // 1000 + 2):
            yield b"n" * 1000
        yield b'"}'

    response = client.patch(
        "/api/saved-clips/saved-1",
        content=chunks(),
        headers={"content-type": "application/json"},
    )
    assert assert_error(response, 422, "validation_error") == "body: is too large"


def test_a_declared_length_over_the_limit_is_refused_before_reading() -> None:
    calls = {"app": 0, "receive": 0}

    async def app(scope: Any, receive: Any, send: Any) -> None:
        calls["app"] += 1

    async def receive() -> dict[str, Any]:
        calls["receive"] += 1
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/zones",
        "query_string": b"",
        "headers": [(b"content-length", str(MAX_JSON_BODY_BYTES + 1).encode())],
    }
    asyncio.run(BodyLimitMiddleware(app)(scope, receive, send))
    assert calls == {"app": 0, "receive": 0}
    assert sent[0]["status"] == 422


def test_the_upload_is_not_held_to_the_json_limit(client: TestClient) -> None:
    video = FAKE_MP4[:8] + bytes(MAX_JSON_BODY_BYTES * 2)
    response = client.post(
        "/api/recordings",
        files={"file": ("clip.mp4", video, "video/mp4")},
        data={"day": "2026-10-30", "camera": "CAM-001"},
    )
    assert response.status_code == 202, response.text


@pytest.mark.parametrize("header_count", [1, 20])
def test_huge_or_many_part_headers_in_an_upload_are_422(
    client: TestClient, header_count: int
) -> None:
    boundary = "bound"
    if header_count == 1:
        headers = b'Content-Disposition: form-data; name="file"; filename="' + b"a" * 20_000
        headers += b'.mp4"\r\nContent-Type: video/mp4\r\n'
    else:
        headers = b"".join(b"X-Filler-%d: x\r\n" % n for n in range(header_count))
        headers += b'Content-Disposition: form-data; name="file"; filename="c.mp4"\r\n'
    body = (
        b"--bound\r\n" + headers + b"\r\n" + FAKE_MP4 + b"\r\n"
        b'--bound\r\nContent-Disposition: form-data; name="day"\r\n\r\n2026-10-30\r\n'
        b"--bound--\r\n"
    )
    response = client.post(
        "/api/recordings",
        content=body,
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )
    message = assert_error(response, 422, "validation_error")
    assert message == "body: is not valid multipart/form-data"
