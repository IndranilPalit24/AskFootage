"""Saved clips over HTTP: save (201 / 404 / 409), list newest first, edit the note, remove."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from api_fakes import InMemoryLibrary, load_example
from api_support import assert_error, build_app
from fastapi.testclient import TestClient

from askfootage.settings import Settings


def save(client: TestClient, clip_id: str, **extra: Any) -> Any:
    """POST /api/saved-clips for one clip."""
    return client.post("/api/saved-clips", json={"clipId": clip_id, **extra})


@pytest.fixture
def ticking_client(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> Iterator[TestClient]:
    """A client whose clock moves on a minute per save and whose ids count up."""
    moments = (datetime(2026, 10, 30, 9, 0, tzinfo=UTC) + timedelta(minutes=n) for n in range(99))
    numbers = iter(range(1, 99))
    app = build_app(
        store,
        fake_settings,
        videos_dir,
        utc_now=lambda: next(moments),
        make_id=lambda prefix: f"{prefix}-{next(numbers)}",
    )
    with TestClient(app) as client:
        yield client


def test_there_are_no_saved_clips_at_first(client: TestClient) -> None:
    response = client.get("/api/saved-clips")
    assert response.status_code == 200
    assert response.json() == []


def test_saving_a_clip_returns_201_like_the_contract_example(client: TestClient) -> None:
    response = save(client, "clip-1029-104215", note="Check this delivery against the paperwork")
    assert response.status_code == 201
    saved = response.json()
    expected = load_example("saved-clips.json")[0]
    assert saved["id"].startswith("saved-")
    assert saved == {**expected, "id": saved["id"]}
    assert saved["savedAt"] == "2026-10-30T09:12:44Z"
    assert client.get("/api/saved-clips").json() == [saved]


def test_the_note_defaults_to_empty(client: TestClient) -> None:
    response = save(client, "clip-1029-104215")
    assert response.status_code == 201
    assert response.json()["note"] == ""


def test_a_note_of_500_characters_is_accepted(client: TestClient) -> None:
    assert save(client, "clip-1029-104215", note="n" * 500).status_code == 201


def test_saving_the_same_clip_twice_is_409(client: TestClient) -> None:
    assert save(client, "clip-1029-104215").status_code == 201
    response = save(client, "clip-1029-104215", note="again")
    assert assert_error(response, 409, "already_saved") == "This clip is already saved."
    assert len(client.get("/api/saved-clips").json()) == 1


def test_saving_an_unknown_clip_is_404(client: TestClient) -> None:
    assert assert_error(save(client, "clip-nope"), 404, "not_found") == "Clip not found."


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({}, "clipId: is required"),
        ({"clipId": "clip 1"}, "clipId: must be 1 to 64"),
        ({"clipId": 7}, "clipId: must be text"),
        ({"clip_id": "clip-1029-104215"}, "clipId: is required; clip_id: is not an accepted"),
        ({"clipId": "clip-1029-104215", "note": "n" * 501}, "note: must be at most 500"),
        ({"clipId": "clip-1029-104215", "note": None}, "note: must be text"),
        ({"clipId": "clip-1029-104215", "savedAt": "2020-01-01T00:00:00Z"}, "savedAt: is not"),
    ],
)
def test_bad_saves_are_422_naming_the_field(
    client: TestClient, body: dict[str, Any], message: str
) -> None:
    got = assert_error(client.post("/api/saved-clips", json=body), 422, "validation_error")
    assert got.startswith(message)


def test_saved_clips_come_newest_first_and_filter_by_day(ticking_client: TestClient) -> None:
    for clip_id in ("clip-1028-064712", "clip-1029-104215", "clip-1029-061405"):
        assert save(ticking_client, clip_id).status_code == 201
    listed = ticking_client.get("/api/saved-clips").json()
    assert [s["clip"]["id"] for s in listed] == [
        "clip-1029-061405",
        "clip-1029-104215",
        "clip-1028-064712",
    ]
    assert [s["savedAt"] for s in listed] == [
        "2026-10-30T09:02:00Z",
        "2026-10-30T09:01:00Z",
        "2026-10-30T09:00:00Z",
    ]
    on_thursday = ticking_client.get("/api/saved-clips", params={"day": "2026-10-29"}).json()
    assert [s["clip"]["id"] for s in on_thursday] == ["clip-1029-061405", "clip-1029-104215"]
    assert ticking_client.get("/api/saved-clips", params={"day": "2026-10-25"}).json() == []


def test_a_bad_day_filter_is_422(client: TestClient) -> None:
    response = client.get("/api/saved-clips", params={"day": "Thursday"})
    assert assert_error(response, 422, "validation_error").startswith("day:")


def test_changing_the_note(ticking_client: TestClient) -> None:
    saved = save(ticking_client, "clip-1029-104215", note="first").json()
    response = ticking_client.patch(f"/api/saved-clips/{saved['id']}", json={"note": "second"})
    assert response.status_code == 200
    assert response.json() == {**saved, "note": "second"}
    assert ticking_client.get("/api/saved-clips").json()[0]["note"] == "second"


def test_changing_the_note_of_an_unknown_saved_clip_is_404(client: TestClient) -> None:
    response = client.patch("/api/saved-clips/saved-nope", json={"note": "x"})
    assert assert_error(response, 404, "not_found") == "Saved clip not found."


@pytest.mark.parametrize(
    ("path", "body", "message"),
    [
        ("/api/saved-clips/saved-1", {}, "note: is required"),
        ("/api/saved-clips/saved-1", {"note": "n" * 501}, "note: must be at most 500"),
        ("/api/saved-clips/saved-1", {"note": "x", "clipId": "c"}, "clipId: is not an accepted"),
        ("/api/saved-clips/%20", {"note": "x"}, "id: must be 1 to 64"),
    ],
)
def test_bad_note_changes_are_422(
    ticking_client: TestClient, path: str, body: dict[str, Any], message: str
) -> None:
    assert save(ticking_client, "clip-1029-104215").json()["id"] == "saved-1"
    got = assert_error(ticking_client.patch(path, json=body), 422, "validation_error")
    assert got.startswith(message)


def test_removing_a_saved_clip_is_204_then_404(ticking_client: TestClient) -> None:
    saved_id = save(ticking_client, "clip-1029-104215").json()["id"]
    response = ticking_client.delete(f"/api/saved-clips/{saved_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert ticking_client.get("/api/saved-clips").json() == []
    assert ticking_client.get("/api/clips/clip-1029-104215").status_code == 200
    assert_error(ticking_client.delete(f"/api/saved-clips/{saved_id}"), 404, "not_found")
    # Removed, it can be saved again.
    assert save(ticking_client, "clip-1029-104215").status_code == 201


def test_removing_with_a_bad_id_is_422(client: TestClient) -> None:
    assert_error(client.delete("/api/saved-clips/a.b"), 422, "validation_error")
