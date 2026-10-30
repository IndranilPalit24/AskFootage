"""Zones over HTTP: list, create (201 / 404 / 409), replace, delete, and point rules."""

from __future__ import annotations

from typing import Any

import pytest
from api_fakes import InMemoryLibrary, load_example
from api_support import assert_error, build_app
from fastapi.testclient import TestClient

from askfootage.settings import Settings

TRIANGLE = [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]]


def new_zone(**changes: Any) -> dict[str, Any]:
    """A valid ZoneCreate body, with any field changed."""
    return {"camera": "loading-dock", "name": "Bay 3", "points": TRIANGLE, **changes}


# --- GET /api/zones -----------------------------------------------------------------------


def test_zones_come_ordered_by_name(client: TestClient) -> None:
    response = client.get("/api/zones")
    assert response.status_code == 200
    assert response.json() == load_example("zones.json")


def test_zones_can_be_filtered_by_camera(client: TestClient) -> None:
    assert client.get("/api/zones", params={"camera": "loading-dock"}).json() == load_example(
        "zones.json"
    )
    assert client.get("/api/zones", params={"camera": "garage"}).json() == []


def test_a_bad_camera_filter_is_422(client: TestClient) -> None:
    message = assert_error(client.get("/api/zones?camera=a%20b"), 422, "validation_error")
    assert message.startswith("camera:")


# --- POST /api/zones ----------------------------------------------------------------------


def test_creating_a_zone_returns_201_with_a_server_made_id(
    client: TestClient, store: InMemoryLibrary
) -> None:
    response = client.post("/api/zones", json=new_zone(name="  Bay 3  "))
    assert response.status_code == 201
    zone = response.json()
    assert zone["id"].startswith("zone-") and len(zone["id"]) == len("zone-") + 12
    assert zone == {"id": zone["id"], "camera": "loading-dock", "name": "Bay 3", "points": TRIANGLE}
    assert zone["id"] in store.zones
    assert [z["name"] for z in client.get("/api/zones").json()] == [
        "Bay 3",
        "Exit lane",
        "Loading door",
    ]


def test_each_new_zone_gets_its_own_id(client: TestClient) -> None:
    first = client.post("/api/zones", json=new_zone(name="Bay 1")).json()["id"]
    second = client.post("/api/zones", json=new_zone(name="Bay 2")).json()["id"]
    assert first != second


def test_whole_numbers_are_valid_coordinates(client: TestClient) -> None:
    response = client.post("/api/zones", json=new_zone(points=[[0, 0], [1, 0], [1, 1]]))
    assert response.status_code == 201
    assert response.json()["points"] == [[0, 0], [1, 0], [1, 1]]


def test_a_zone_name_already_on_the_camera_is_409(client: TestClient) -> None:
    for name in ("Loading door", "loading DOOR", "  Exit lane "):
        response = client.post("/api/zones", json=new_zone(name=name))
        assert_error(response, 409, "zone_name_taken")


def test_a_zone_on_an_unknown_camera_is_404(client: TestClient) -> None:
    response = client.post("/api/zones", json=new_zone(camera="garage"))
    assert assert_error(response, 404, "not_found") == "Camera not found."


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (new_zone(name=""), "name: must be at least 1 character"),
        (new_zone(name="   "), "name: must not be blank"),
        (new_zone(name="n" * 61), "name: must be at most 60 characters"),
        (new_zone(points=TRIANGLE[:2]), "points: must have at least 3 items"),
        (new_zone(points=[[0.5, 0.5]] * 51), "points: must have at most 50 items"),
        (new_zone(points=[[0.1], [0.2, 0.2], [0.3, 0.3]]), "points[0][1]: is required"),
        (new_zone(points=[[0.1, 0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]), "points[0]: "),
        (new_zone(points=[[1.5, 0.1], [0.2, 0.2], [0.3, 0.3]]), "points[0][0]: must be at most 1"),
        (new_zone(points=[[0.1, -0.1], [0.2, 0.2], [0.3, 0.3]]), "points[0][1]: must be at least"),
        (new_zone(points=[["0.1", 0.1], [0.2, 0.2], [0.3, 0.3]]), "points[0][0]: must be a num"),
        (new_zone(points=[[True, 0.1], [0.2, 0.2], [0.3, 0.3]]), "points[0][0]: must be a num"),
        (new_zone(points=[[None, 0.1], [0.2, 0.2], [0.3, 0.3]]), "points[0][0]: must be a num"),
        (new_zone(points="0.1,0.1"), "points: "),
        (new_zone(camera="../x"), "camera: must be 1 to 64"),
        ({"name": "Bay 3", "points": TRIANGLE}, "camera: is required"),
        ({"camera": "loading-dock", "points": TRIANGLE}, "name: is required"),
        ({"camera": "loading-dock", "name": "Bay 3"}, "points: is required"),
        (new_zone(id="zone-mine"), "id: is not an accepted field"),
    ],
)
def test_bad_zones_are_422_naming_the_field(
    client: TestClient, body: dict[str, Any], message: str
) -> None:
    got = assert_error(client.post("/api/zones", json=body), 422, "validation_error")
    assert got.startswith(message)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_points_that_are_not_finite_are_422(client: TestClient, value: str) -> None:
    body = (
        '{"camera": "loading-dock", "name": "Bay 3", '
        f'"points": [[{value}, 0.1], [0.2, 0.2], [0.3, 0.3]]}}'
    )
    response = client.post(
        "/api/zones", content=body.encode(), headers={"content-type": "application/json"}
    )
    assert assert_error(response, 422, "validation_error").startswith("points[0][0]:")


# --- PUT /api/zones/{id} ------------------------------------------------------------------


def test_replacing_a_zone_renames_and_redraws_it(client: TestClient) -> None:
    response = client.put(
        "/api/zones/zone-exit-lane", json={"name": " Exit lane north ", "points": TRIANGLE}
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": "zone-exit-lane",
        "camera": "loading-dock",
        "name": "Exit lane north",
        "points": TRIANGLE,
    }
    zones = {zone["id"]: zone for zone in client.get("/api/zones").json()}
    assert zones["zone-exit-lane"]["name"] == "Exit lane north"


def test_a_zone_may_keep_its_own_name_in_another_case(client: TestClient) -> None:
    response = client.put(
        "/api/zones/zone-exit-lane", json={"name": "EXIT LANE", "points": TRIANGLE}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "EXIT LANE"


def test_renaming_a_zone_to_another_zones_name_is_409(client: TestClient) -> None:
    response = client.put(
        "/api/zones/zone-exit-lane", json={"name": "loading door", "points": TRIANGLE}
    )
    assert_error(response, 409, "zone_name_taken")


def test_replacing_an_unknown_zone_is_404(client: TestClient) -> None:
    response = client.put("/api/zones/zone-nope", json={"name": "Bay", "points": TRIANGLE})
    assert assert_error(response, 404, "not_found") == "Zone not found."


@pytest.mark.parametrize(
    ("path", "body", "message"),
    [
        ("/api/zones/zone-exit-lane", {"name": "Bay"}, "points: is required"),
        ("/api/zones/zone-exit-lane", {"points": TRIANGLE}, "name: is required"),
        (
            "/api/zones/zone-exit-lane",
            {"name": "Bay", "points": TRIANGLE, "camera": "garage"},
            "camera: is not an accepted field",
        ),
        ("/api/zones/bad%20id", {"name": "Bay", "points": TRIANGLE}, "id: must be 1 to 64"),
    ],
)
def test_bad_zone_replacements_are_422(
    client: TestClient, path: str, body: dict[str, Any], message: str
) -> None:
    got = assert_error(client.put(path, json=body), 422, "validation_error")
    assert got.startswith(message)


# --- DELETE /api/zones/{id} ---------------------------------------------------------------


def test_deleting_a_zone_is_204_then_404(client: TestClient) -> None:
    response = client.delete("/api/zones/zone-exit-lane")
    assert response.status_code == 204
    assert response.content == b""
    assert [zone["id"] for zone in client.get("/api/zones").json()] == ["zone-loading-door"]
    assert_error(client.delete("/api/zones/zone-exit-lane"), 404, "not_found")


def test_deleting_with_a_bad_id_is_422(client: TestClient) -> None:
    assert_error(client.delete("/api/zones/bad.id"), 422, "validation_error")


def test_ids_come_from_the_injected_factory(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Any
) -> None:
    app = build_app(store, fake_settings, videos_dir, make_id=lambda prefix: f"{prefix}-fixed")
    with TestClient(app) as client:
        assert client.post("/api/zones", json=new_zone()).json()["id"] == "zone-fixed"
