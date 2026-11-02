"""The camera routes: list with counts, add, change status, and the password never shown."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from api_support import FAKE_KEY, assert_error
from fastapi.testclient import TestClient

PASSWORD = "pw-Zx9-never-shown"


def _body(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Yard",
        "ip": "10.0.0.7",
        "username": "viewer",
        "password": PASSWORD,
        "acknowledgeCost": True,
    }
    body.update(changes)
    return body


def test_list_cameras_gives_zone_and_recording_counts(client: TestClient) -> None:
    cameras = client.get("/api/cameras").json()
    assert [c["id"] for c in cameras] == ["CAM-001", "CAM-002", "CAM-003"]
    by_id = {c["id"]: c for c in cameras}
    assert (by_id["CAM-001"]["recordingCount"], by_id["CAM-001"]["zoneCount"]) == (18, 2)
    assert (by_id["CAM-002"]["recordingCount"], by_id["CAM-002"]["zoneCount"]) == (3, 1)
    assert (by_id["CAM-003"]["recordingCount"], by_id["CAM-003"]["zoneCount"]) == (2, 0)


def test_add_camera_returns_201_online_with_a_masked_url(client: TestClient) -> None:
    response = client.post("/api/cameras", json=_body())
    assert response.status_code == 201
    camera = response.json()
    assert camera["id"] == "CAM-004"
    assert camera["status"] == "online"
    assert (camera["recordingCount"], camera["zoneCount"]) == (0, 0)
    assert camera["rtspUrlMasked"].startswith("rtsp://viewer:****@10.0.0.7:554/")


@pytest.mark.parametrize("value", [False, None, "true", 1])
def test_add_camera_rejects_acknowledge_cost_that_is_not_true(
    client: TestClient, value: object
) -> None:
    response = client.post("/api/cameras", json=_body(acknowledgeCost=value))
    message = assert_error(response, 422, "validation_error")
    assert "acknowledgeCost" in message
    assert PASSWORD not in message
    assert len(client.get("/api/cameras").json()) == 3


def test_add_camera_without_acknowledge_cost_is_422(client: TestClient) -> None:
    body = _body()
    del body["acknowledgeCost"]
    assert_error(client.post("/api/cameras", json=body), 422, "validation_error")


@pytest.mark.parametrize("name", ["Yard", "yard", "  YARD  "])
def test_a_duplicate_name_is_409_camera_name_taken_ignoring_case(
    client: TestClient, name: str
) -> None:
    assert client.post("/api/cameras", json=_body()).status_code == 201
    response = client.post("/api/cameras", json=_body(name=name))
    message = assert_error(response, 409, "camera_name_taken")
    assert PASSWORD not in message


@pytest.mark.parametrize("status", ["online", "standby", "offline"])
def test_patch_changes_the_status(client: TestClient, status: str) -> None:
    response = client.patch("/api/cameras/CAM-002", json={"status": status})
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert client.get("/api/cameras/CAM-002").json()["status"] == status


@pytest.mark.parametrize("body", [{"status": "broken"}, {"status": ""}, {}, {"name": "x"}])
def test_patch_with_a_bad_body_is_422(client: TestClient, body: dict[str, Any]) -> None:
    assert_error(client.patch("/api/cameras/CAM-002", json=body), 422, "validation_error")


def test_patch_unknown_camera_is_404_and_bad_id_is_422(client: TestClient) -> None:
    assert_error(client.patch("/api/cameras/CAM-777", json={"status": "offline"}), 404, "not_found")
    assert_error(
        client.patch("/api/cameras/a.b", json={"status": "offline"}), 422, "validation_error"
    )


def test_the_password_is_in_no_response_and_no_log(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    texts = [
        client.post("/api/cameras", json=_body()).text,
        client.post("/api/cameras", json=_body()).text,
        client.post("/api/cameras", json=_body(name="Other", acknowledgeCost=False)).text,
        client.post("/api/cameras", json=_body(name="Other", username="")).text,
        client.get("/api/cameras").text,
        client.get("/api/cameras/CAM-004").text,
        client.patch("/api/cameras/CAM-004", json={"status": "standby"}).text,
        client.delete("/api/cameras/CAM-004").text,
        client.get("/api/openapi.json").text,
    ]
    for text in texts:
        assert PASSWORD not in text
        assert FAKE_KEY not in text
    assert PASSWORD not in caplog.text
