"""DELETE /api/cameras/{id}: a camera with recordings is only deleted when asked.

Without ?deleteRecordings=true the answer is 409 camera_has_recordings and nothing changes.
Both entry points (the demo app and the real-clips app) must behave the same way.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from api_fakes import FAKE_MP4, InMemoryLibrary, load_example
from api_support import FAKE_KEY, assert_error
from fastapi.testclient import TestClient

from askfootage.interfaces import real_clips
from askfootage.interfaces.api import app as app_module
from askfootage.interfaces.api.schemas import Error
from askfootage.settings import Settings

CODE = "camera_has_recordings"
SAVED_CLIP_ON_CAM_2 = "clip-1029-cam2-071230"
MESSAGE_2_RECORDINGS_1_SAVED = (
    "This camera has 3 recordings and 1 saved clip. Deleting it would delete them too; "
    "confirm to delete the camera together with its recordings."
)


def _camera_ids(client: TestClient) -> list[str]:
    return [camera["id"] for camera in client.get("/api/cameras").json()]


def _camera(client: TestClient, camera_id: str) -> dict[str, object]:
    return next(c for c in client.get("/api/cameras").json() if c["id"] == camera_id)


# --- On the in-memory app ---------------------------------------------------------------------


def test_a_camera_with_recordings_is_refused_with_409_and_nothing_is_deleted(
    client: TestClient, store: InMemoryLibrary
) -> None:
    assert client.post("/api/saved-clips", json={"clipId": SAVED_CLIP_ON_CAM_2}).status_code == 201
    before = (
        dict(store.cameras),
        dict(store.recordings),
        dict(store.clips),
        dict(store.zones),
        dict(store.saved),
    )

    message = assert_error(client.delete("/api/cameras/CAM-002"), 409, CODE)

    assert message == MESSAGE_2_RECORDINGS_1_SAVED
    assert (
        dict(store.cameras),
        dict(store.recordings),
        dict(store.clips),
        dict(store.zones),
        dict(store.saved),
    ) == before
    camera = _camera(client, "CAM-002")
    assert camera["recordingCount"] == 3
    assert camera["zoneCount"] == 1


def test_an_explicit_false_is_the_same_as_leaving_the_flag_out(client: TestClient) -> None:
    assert_error(
        client.delete("/api/cameras/CAM-003", params={"deleteRecordings": "false"}), 409, CODE
    )
    assert "CAM-003" in _camera_ids(client)


def test_the_message_uses_singular_and_plural_and_zero_saved_clips(
    client: TestClient, store: InMemoryLibrary
) -> None:
    message = assert_error(client.delete("/api/cameras/CAM-003"), 409, CODE)
    assert message.startswith("This camera has 2 recordings and 0 saved clips. ")
    for recording_id in [r.id for r in store.recordings.values() if r.camera == "CAM-003"][1:]:
        del store.recordings[recording_id]
    message = assert_error(client.delete("/api/cameras/CAM-003"), 409, CODE)
    assert message.startswith("This camera has 1 recording and 0 saved clips. ")


def test_the_message_names_no_other_camera_no_path_and_no_secret(client: TestClient) -> None:
    message = assert_error(client.delete("/api/cameras/CAM-002"), 409, CODE)
    assert "CAM-" not in message
    assert FAKE_KEY not in message
    for fragment in ("\\", "/", ".mp4", ".sqlite", "Traceback"):
        assert fragment not in message


def test_the_error_body_is_the_standard_shape_and_matches_the_example() -> None:
    example = load_example("camera-has-recordings.json")
    assert Error.model_validate(example).model_dump(mode="json") == example
    assert example["error"]["code"] == CODE


def test_delete_recordings_true_deletes_the_camera_and_everything_on_it(
    client: TestClient, store: InMemoryLibrary
) -> None:
    assert client.post("/api/saved-clips", json={"clipId": SAVED_CLIP_ON_CAM_2}).status_code == 201
    other_recordings = {r.id for r in store.recordings.values() if r.camera != "CAM-002"}

    response = client.delete("/api/cameras/CAM-002", params={"deleteRecordings": "true"})

    assert response.status_code == 204
    assert response.content == b""
    assert "CAM-002" not in _camera_ids(client)
    assert {r.id for r in store.recordings.values()} == other_recordings
    assert not [c for c in store.clips.values() if c.id == SAVED_CLIP_ON_CAM_2]
    assert not [z for z in store.zones.values() if z.camera == "CAM-002"]
    assert client.get("/api/saved-clips").json() == []
    assert_error(client.delete("/api/cameras/CAM-002"), 404, "not_found")


def test_a_camera_without_recordings_is_deleted_at_once_whatever_the_flag_says(
    client: TestClient,
) -> None:
    for flag in (None, "false", "true"):
        added = client.post(
            "/api/cameras",
            json={
                "name": f"Spare {flag}",
                "ip": "10.0.0.9",
                "username": "viewer",
                "password": "pw-1234",
                "acknowledgeCost": True,
            },
        )
        assert added.status_code == 201
        camera_id = added.json()["id"]
        params = {} if flag is None else {"deleteRecordings": flag}
        assert client.delete(f"/api/cameras/{camera_id}", params=params).status_code == 204
        assert camera_id not in _camera_ids(client)


def test_a_second_delete_is_404_and_an_unknown_camera_is_404_even_with_the_flag(
    client: TestClient,
) -> None:
    assert (
        client.delete("/api/cameras/CAM-003", params={"deleteRecordings": "true"}).status_code
        == 204
    )
    assert_error(client.delete("/api/cameras/CAM-003"), 404, "not_found")
    assert_error(
        client.delete("/api/cameras/CAM-003", params={"deleteRecordings": "true"}), 404, "not_found"
    )
    assert_error(client.delete("/api/cameras/CAM-777"), 404, "not_found")


def test_a_bad_id_is_422(client: TestClient) -> None:
    assert_error(client.delete("/api/cameras/a.b"), 422, "validation_error")
    assert_error(client.delete("/api/cameras/bad id"), 422, "validation_error")


@pytest.mark.parametrize("value", ["yes", "1", "0", "on", "TRUE", "", "maybe", "True"])
def test_a_flag_other_than_true_or_false_is_422_and_deletes_nothing(
    client: TestClient, value: str
) -> None:
    message = assert_error(
        client.delete("/api/cameras/CAM-003", params={"deleteRecordings": value}),
        422,
        "validation_error",
    )
    assert message == "deleteRecordings: must be true or false"
    assert "CAM-003" in _camera_ids(client)


def test_the_flag_is_not_read_from_a_wrong_spelling(client: TestClient) -> None:
    response = client.delete("/api/cameras/CAM-003", params={"delete_recordings": "true"})
    assert_error(response, 409, CODE)


def test_a_server_failure_while_counting_is_a_500_without_details(
    client: TestClient, store: InMemoryLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> object:
        raise RuntimeError(f"disk C:\\secret\\library.sqlite {FAKE_KEY}")

    monkeypatch.setattr(store, "camera_counts", boom)
    message = assert_error(client.delete("/api/cameras/CAM-003"), 500, "internal_error")
    assert message == "Something went wrong."


def test_the_delete_operation_is_documented_with_the_flag_and_the_409(client: TestClient) -> None:
    operation = client.get("/api/openapi.json").json()["paths"]["/api/cameras/{id}"]["delete"]
    flag = next(p for p in operation["parameters"] if p["name"] == "deleteRecordings")
    assert flag["in"] == "query"
    assert flag.get("required", False) is False
    assert flag["schema"]["type"] == "boolean"
    assert flag["schema"]["default"] is False
    assert set(operation["responses"]) == {"204", "404", "409", "422", "500"}
    assert "camera_has_recordings" in operation["responses"]["409"]["description"]


# --- Both entry points on a real SQLite store -------------------------------------------------


@pytest.fixture
def demo_client(fake_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The demo entry point (create_app with no arguments) on a temp data folder."""
    monkeypatch.setattr(app_module, "load_settings", lambda: fake_settings)
    with TestClient(app_module.create_app()) as client:
        yield client


@pytest.fixture
def real_client(tmp_path: Path) -> TestClient:
    """The real-clips entry point over an empty temp data folder, with one camera and clip."""
    app = real_clips.create_app(tmp_path / "real", tmp_path / "videos")
    with TestClient(app) as client:
        added = client.post(
            "/api/cameras",
            json={
                "name": "Yard",
                "ip": "10.0.0.7",
                "username": "viewer",
                "password": "pw-1234",
                "acknowledgeCost": True,
            },
        )
        assert added.status_code == 201
        uploaded = client.post(
            "/api/recordings",
            data={"day": "2026-10-30", "camera": added.json()["id"]},
            files={"file": ("yard.mp4", FAKE_MP4, "video/mp4")},
        )
        assert uploaded.status_code == 202, uploaded.text
        yield client


def test_the_demo_entry_point_applies_the_rule(demo_client: TestClient) -> None:
    assert (
        demo_client.post("/api/saved-clips", json={"clipId": SAVED_CLIP_ON_CAM_2}).status_code
        == 201
    )
    message = assert_error(demo_client.delete("/api/cameras/CAM-002"), 409, CODE)
    assert message == MESSAGE_2_RECORDINGS_1_SAVED
    assert _camera(demo_client, "CAM-002")["recordingCount"] == 3
    assert len(demo_client.get("/api/zones", params={"camera": "CAM-002"}).json()) == 1
    assert demo_client.get(f"/api/clips/{SAVED_CLIP_ON_CAM_2}").status_code == 200

    assert_error(
        demo_client.delete("/api/cameras/CAM-002", params={"deleteRecordings": "maybe"}),
        422,
        "validation_error",
    )

    gone = demo_client.delete("/api/cameras/CAM-002", params={"deleteRecordings": "true"})
    assert gone.status_code == 204
    assert "CAM-002" not in _camera_ids(demo_client)
    assert demo_client.get(f"/api/clips/{SAVED_CLIP_ON_CAM_2}").status_code == 404
    assert demo_client.get("/api/zones", params={"camera": "CAM-001"}).status_code == 200
    assert demo_client.get("/api/saved-clips").json() == []
    assert_error(demo_client.delete("/api/cameras/CAM-002"), 404, "not_found")


def test_the_demo_entry_point_deletes_a_camera_without_recordings_at_once(
    demo_client: TestClient,
) -> None:
    demo_client.delete("/api/cameras/CAM-003", params={"deleteRecordings": "true"})
    added = demo_client.post(
        "/api/cameras",
        json={
            "name": "Spare",
            "ip": "10.0.0.9",
            "username": "viewer",
            "password": "pw-1234",
            "acknowledgeCost": True,
        },
    )
    camera_id = added.json()["id"]
    assert demo_client.delete(f"/api/cameras/{camera_id}").status_code == 204
    assert_error(demo_client.delete(f"/api/cameras/{camera_id}"), 404, "not_found")
    assert_error(demo_client.delete("/api/cameras/x.y"), 422, "validation_error")


def test_the_real_clips_entry_point_applies_the_rule(real_client: TestClient) -> None:
    camera_id = _camera_ids(real_client)[0]
    message = assert_error(real_client.delete(f"/api/cameras/{camera_id}"), 409, CODE)
    assert message.startswith("This camera has 1 recording and 0 saved clips. ")
    assert "CAM-" not in message
    assert _camera_ids(real_client) == [camera_id]
    assert _camera(real_client, camera_id)["recordingCount"] == 1

    assert_error(
        real_client.delete(f"/api/cameras/{camera_id}", params={"deleteRecordings": "1"}),
        422,
        "validation_error",
    )

    gone = real_client.delete(f"/api/cameras/{camera_id}", params={"deleteRecordings": "true"})
    assert gone.status_code == 204
    assert _camera_ids(real_client) == []
    assert_error(real_client.delete(f"/api/cameras/{camera_id}"), 404, "not_found")


def test_the_real_clips_entry_point_deletes_an_empty_camera_at_once(
    real_client: TestClient,
) -> None:
    added = real_client.post(
        "/api/cameras",
        json={
            "name": "Spare",
            "ip": "10.0.0.9",
            "username": "viewer",
            "password": "pw-1234",
            "acknowledgeCost": True,
        },
    )
    camera_id = added.json()["id"]
    assert real_client.delete(f"/api/cameras/{camera_id}").status_code == 204
    assert camera_id not in _camera_ids(real_client)
