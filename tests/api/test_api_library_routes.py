"""Status, days, recordings and clips over HTTP, plus the error body on unknown routes.

The app runs on in-memory stores seeded from contract/examples/demo-seed.json, so the
contract's example responses are the expected answers.
"""

from __future__ import annotations

import pytest
from api_fakes import load_example
from api_support import assert_error
from fastapi.testclient import TestClient

TOO_LONG_ID = "x" * 65


# --- GET /api/status ----------------------------------------------------------------------


def test_status_is_demo_mode_on_the_loading_dock(client: TestClient) -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == load_example("status.json")


# --- GET /api/days ------------------------------------------------------------------------


def test_days_are_the_seven_days_ending_today_zero_filled(client: TestClient) -> None:
    response = client.get("/api/days", params={"camera": "loading-dock"})
    assert response.status_code == 200
    days = response.json()
    assert days == load_example("days.json")
    assert len(days) == 7
    assert days[-1]["day"] == "2026-10-30"
    assert days[1] == {"day": "2026-10-25", "recordings": 0, "ready": 0}


def test_days_for_an_unknown_camera_is_404(client: TestClient) -> None:
    response = client.get("/api/days", params={"camera": "back-door"})
    assert assert_error(response, 404, "not_found") == "Camera not found."


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({}, "camera"),
        ({"camera": ""}, "camera"),
        ({"camera": "loading dock"}, "camera"),
        ({"camera": TOO_LONG_ID}, "camera"),
        ({"camera": "../etc"}, "camera"),
    ],
)
def test_days_with_a_bad_camera_is_422_naming_the_field(
    client: TestClient, params: dict[str, str], field: str
) -> None:
    message = assert_error(client.get("/api/days", params=params), 422, "validation_error")
    assert message.startswith(f"{field}:")
    for value in params.values():
        if value:
            assert value not in message


# --- GET /api/recordings ------------------------------------------------------------------


def test_recordings_of_a_day_come_ordered_by_start_time(client: TestClient) -> None:
    response = client.get("/api/recordings", params={"day": "2026-10-29", "camera": "loading-dock"})
    assert response.status_code == 200
    recordings = response.json()
    assert recordings == load_example("recordings.json")
    assert [r["startTime"] for r in recordings] == sorted(r["startTime"] for r in recordings)
    assert len(recordings) == 6


def test_recordings_of_a_day_without_footage_is_an_empty_list(client: TestClient) -> None:
    response = client.get("/api/recordings", params={"day": "2026-10-25", "camera": "loading-dock"})
    assert response.status_code == 200
    assert response.json() == []


def test_recordings_for_an_unknown_camera_is_404(client: TestClient) -> None:
    response = client.get("/api/recordings", params={"day": "2026-10-29", "camera": "nowhere"})
    assert assert_error(response, 404, "not_found") == "Camera not found."


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"camera": "loading-dock"}, "day"),
        ({"day": "2026-10-29"}, "camera"),
        ({"day": "29/10/2026", "camera": "loading-dock"}, "day"),
        ({"day": "2026-02-30", "camera": "loading-dock"}, "day"),
        ({"day": "1761696000", "camera": "loading-dock"}, "day"),
        ({"day": "2026-10-29T10:00:00", "camera": "loading-dock"}, "day"),
        ({"day": "2026-10-29", "camera": "loading_dock!"}, "camera"),
    ],
)
def test_recordings_with_bad_parameters_is_422_naming_the_field(
    client: TestClient, params: dict[str, str], field: str
) -> None:
    response = client.get("/api/recordings", params=params)
    message = assert_error(response, 422, "validation_error")
    assert message.startswith(f"{field}:")
    assert params.get(field, "\0") not in message


# --- GET /api/clips/{id} ------------------------------------------------------------------


def test_a_clip_comes_with_its_evidence(client: TestClient) -> None:
    response = client.get("/api/clips/clip-1029-104215")
    assert response.status_code == 200
    assert response.json() == load_example("clip-detail.json")


def test_an_unknown_clip_is_404(client: TestClient) -> None:
    response = client.get("/api/clips/clip-0000-000000")
    assert response.json() == load_example("error.json")
    assert_error(response, 404, "not_found")


@pytest.mark.parametrize("clip_id", ["bad id", "clip.1029", TOO_LONG_ID, "%00"])
def test_a_clip_id_breaking_the_pattern_is_422(client: TestClient, clip_id: str) -> None:
    message = assert_error(client.get(f"/api/clips/{clip_id}"), 422, "validation_error")
    assert message == "id: must be 1 to 64 letters, digits, '-' or '_'"


# --- Unknown routes and methods -----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/api/nothing-here", "/", "/api", "/api/clips", "/api/clips/a/b", "/api/recordings/x/y"],
)
def test_unknown_routes_are_404_with_the_error_body(client: TestClient, path: str) -> None:
    assert assert_error(client.get(path), 404, "not_found") == "Not found."


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/api/status"),
        ("DELETE", "/api/days"),
        ("PATCH", "/api/recordings"),
        ("POST", "/api/clips/clip-1029-104215"),
        ("GET", "/api/search"),
        ("PATCH", "/api/zones/zone-exit-lane"),
        ("PUT", "/api/saved-clips/saved-1"),
        ("POST", "/api/recordings/rec-1029-0600/video"),
    ],
)
def test_wrong_methods_are_405_with_the_error_body(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path)
    assert assert_error(response, 405, "method_not_allowed") == "Method not allowed."
    assert "allow" in response.headers


def test_the_api_docs_are_served_under_api(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 200
    assert_error(client.get("/docs"), 404, "not_found")
    assert_error(client.get("/openapi.json"), 404, "not_found")
