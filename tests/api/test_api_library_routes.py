"""Status, days, recordings and clips over HTTP, plus the error body on unknown routes.

The app runs on in-memory stores seeded from contract/examples/demo-seed.json, so the
contract's example responses are the expected answers. The examples are CAM-001's; the
seed also has CAM-002 (front gate) and CAM-003 (back door), which "all cameras" includes.
"""

from __future__ import annotations

from datetime import date, time

import pytest
from api_fakes import InMemoryLibrary, load_example
from api_support import assert_error
from fastapi.testclient import TestClient

from askfootage.ports.library_store import Recording

TOO_LONG_ID = "x" * 65
# Seven days ending 2026-10-30, for all three cameras together.
ALL_CAMERA_DAYS = [
    {"day": "2026-10-24", "recordings": 1, "ready": 1},
    {"day": "2026-10-25", "recordings": 0, "ready": 0},
    {"day": "2026-10-26", "recordings": 2, "ready": 2},
    {"day": "2026-10-27", "recordings": 3, "ready": 3},
    {"day": "2026-10-28", "recordings": 4, "ready": 4},
    {"day": "2026-10-29", "recordings": 8, "ready": 7},
    {"day": "2026-10-30", "recordings": 5, "ready": 2},
]


# --- GET /api/status ----------------------------------------------------------------------


def test_status_is_demo_mode_and_nothing_else(client: TestClient) -> None:
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == load_example("status.json") == {"demoMode": True}


# --- GET /api/days ------------------------------------------------------------------------


def test_days_are_the_seven_days_ending_today_zero_filled(client: TestClient) -> None:
    response = client.get("/api/days", params={"camera": "CAM-001"})
    assert response.status_code == 200
    days = response.json()
    assert days == load_example("days.json")
    assert len(days) == 7
    assert days[-1]["day"] == "2026-10-30"
    assert days[1] == {"day": "2026-10-25", "recordings": 0, "ready": 0}


def test_days_without_a_camera_count_every_camera(client: TestClient) -> None:
    response = client.get("/api/days")
    assert response.status_code == 200
    assert response.json() == ALL_CAMERA_DAYS


def test_days_of_another_camera_count_only_its_recordings(client: TestClient) -> None:
    days = client.get("/api/days", params={"camera": "CAM-002"}).json()
    assert [(d["recordings"], d["ready"]) for d in days] == [(0, 0)] * 5 + [(2, 2), (1, 0)]


@pytest.mark.parametrize("camera", ["CAM-999", "back-door", "loading-dock"])
def test_days_for_an_unknown_camera_is_404(client: TestClient, camera: str) -> None:
    response = client.get("/api/days", params={"camera": camera})
    assert assert_error(response, 404, "not_found") == "Camera not found."


@pytest.mark.parametrize(
    ("params", "field"),
    [
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
    response = client.get("/api/recordings", params={"day": "2026-10-29", "camera": "CAM-001"})
    assert response.status_code == 200
    recordings = response.json()
    assert recordings == load_example("recordings.json")
    assert [r["startTime"] for r in recordings] == sorted(r["startTime"] for r in recordings)
    assert len(recordings) == 6
    assert {r["camera"] for r in recordings} == {"CAM-001"}


def test_recordings_without_a_camera_list_every_camera_in_time_order(client: TestClient) -> None:
    response = client.get("/api/recordings", params={"day": "2026-10-29"})
    assert response.status_code == 200
    assert [(r["startTime"], r["camera"], r["id"]) for r in response.json()] == [
        ("06:00:00", "CAM-001", "rec-1029-0600"),
        ("07:00:00", "CAM-002", "rec-1029-cam2-0700"),
        ("07:05:00", "CAM-001", "rec-1029-0705"),
        ("09:12:00", "CAM-001", "rec-1029-0912"),
        ("10:30:00", "CAM-001", "rec-1029-1030"),
        ("12:00:00", "CAM-002", "rec-1029-cam2-1200"),
        ("13:00:00", "CAM-001", "rec-1029-1300"),
        ("16:10:00", "CAM-001", "rec-1029-1610"),
    ]


def test_recordings_at_the_same_time_are_ordered_by_camera_then_id(
    client: TestClient, store: InMemoryLibrary
) -> None:
    for recording_id, camera in [("rec-b", "CAM-003"), ("rec-a", "CAM-002"), ("rec-c", "CAM-002")]:
        store.add_recording(
            Recording(
                id=recording_id,
                camera=camera,
                day=date(2026, 10, 25),
                start_time=time(9, 0),
                length_seconds=60,
                status="ready",
            )
        )
    response = client.get("/api/recordings", params={"day": "2026-10-25"})
    assert [(r["camera"], r["id"]) for r in response.json()] == [
        ("CAM-002", "rec-a"),
        ("CAM-002", "rec-c"),
        ("CAM-003", "rec-b"),
    ]


def test_recordings_of_a_day_without_footage_is_an_empty_list(client: TestClient) -> None:
    response = client.get("/api/recordings", params={"day": "2026-10-25", "camera": "CAM-001"})
    assert response.status_code == 200
    assert response.json() == []
    assert client.get("/api/recordings", params={"day": "2026-10-25"}).json() == []


def test_recordings_for_an_unknown_camera_is_404(client: TestClient) -> None:
    response = client.get("/api/recordings", params={"day": "2026-10-29", "camera": "nowhere"})
    assert assert_error(response, 404, "not_found") == "Camera not found."


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"camera": "CAM-001"}, "day"),
        ({}, "day"),
        ({"day": "29/10/2026", "camera": "CAM-001"}, "day"),
        ({"day": "2026-02-30", "camera": "CAM-001"}, "day"),
        ({"day": "1761696000", "camera": "CAM-001"}, "day"),
        ({"day": "2026-10-29T10:00:00", "camera": "CAM-001"}, "day"),
        ({"day": "2026-10-29", "camera": "loading_dock!"}, "camera"),
        ({"day": "2026-10-29", "camera": ""}, "camera"),
    ],
)
def test_recordings_with_bad_parameters_is_422_naming_the_field(
    client: TestClient, params: dict[str, str], field: str
) -> None:
    response = client.get("/api/recordings", params=params)
    message = assert_error(response, 422, "validation_error")
    assert message.startswith(f"{field}:")
    rejected = params.get(field)
    if rejected:
        assert rejected not in message


# --- GET /api/clips/{id} ------------------------------------------------------------------


def test_a_clip_comes_with_its_evidence(client: TestClient) -> None:
    response = client.get("/api/clips/clip-1029-104215")
    assert response.status_code == 200
    assert response.json() == load_example("clip-detail.json")


def test_a_clips_camera_is_its_recordings_camera(client: TestClient) -> None:
    clip = client.get("/api/clips/clip-1029-cam2-071230").json()
    assert (clip["recordingId"], clip["camera"]) == ("rec-1029-cam2-0700", "CAM-002")


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
        ("PUT", "/api/cameras/CAM-001"),
        ("DELETE", "/api/cameras"),
        ("POST", "/api/cameras/CAM-001"),
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
