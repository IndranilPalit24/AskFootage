"""Evidence snapshots over the API: search makes them, the clip points at them, a route serves them.

The renderer is a fake that writes a few bytes, so no ffmpeg and no footage are needed.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from api_fakes import InMemoryLibrary, InMemoryTrackStore
from api_support import assert_error, build_app
from fastapi.testclient import TestClient

from askfootage.application.snapshots import SnapshotStore
from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint
from askfootage.ports.snapshots import SnapshotBox
from askfootage.settings import Settings

REC = "rec-1029-0600"
JPEG = b"\xff\xd8fake-jpeg\xff\xd9"
QUESTION = {"question": "someone carrying a box", "day": "2026-10-29", "camera": "CAM-001"}


class Renderer:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, int, tuple[SnapshotBox, ...]]] = []

    def render(
        self, recording_id: str, frame: int, boxes: Sequence[SnapshotBox], destination: Path
    ) -> None:
        if self.fail:
            raise OSError("ffmpeg exploded")
        self.calls.append((recording_id, frame, tuple(boxes)))
        destination.write_bytes(JPEG)


def _track(track_id: int, label: str, left: float, top: float, w: float, h: float) -> Track:
    points = tuple(
        TrackPoint(f, BoundingBox(left + 10 * f, top, left + w + 10 * f, top + h))
        for f in range(25)
    )
    return Track(track_id, label, points)


@pytest.fixture
def tracks(store: InMemoryLibrary) -> InMemoryTrackStore:
    found = InMemoryTrackStore(store)
    found.save_tracks(REC, "person", [_track(1, "person", 100, 500, 100, 300)])
    found.save_tracks(REC, "cardboard box", [_track(7, "cardboard box", 130, 600, 40, 40)])
    return found


@pytest.fixture
def renderer() -> Renderer:
    return Renderer()


def make_client(
    store: InMemoryLibrary,
    settings: Settings,
    videos_dir: Path,
    tracks: InMemoryTrackStore,
    snapshots: SnapshotStore | None,
) -> Iterator[TestClient]:
    app = build_app(store, settings, videos_dir, tracks=tracks, snapshots=snapshots)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(
    store: InMemoryLibrary,
    fake_settings: Settings,
    videos_dir: Path,
    tracks: InMemoryTrackStore,
    renderer: Renderer,
    tmp_path: Path,
) -> Iterator[TestClient]:
    yield from make_client(
        store, fake_settings, videos_dir, tracks, SnapshotStore(tmp_path / "snaps", renderer)
    )


def _rel_clip(client: TestClient) -> dict[str, Any]:
    clips = client.post("/api/search", json=QUESTION).json()["clips"]
    (mine,) = [c for c in clips if c["id"].startswith("rel-")]
    return mine  # type: ignore[no-any-return]


def test_a_clip_found_from_tracks_points_at_its_snapshot(client: TestClient) -> None:
    clip = _rel_clip(client)
    assert clip["snapshotUrl"] == f"/api/clips/{clip['id']}/snapshot"


def test_the_snapshot_is_served_as_a_jpeg(client: TestClient) -> None:
    clip = _rel_clip(client)
    response = client.get(clip["snapshotUrl"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == JPEG


def test_the_snapshot_is_made_at_the_first_frame_with_both_boxes(
    client: TestClient, renderer: Renderer
) -> None:
    _rel_clip(client)
    ((recording, frame, boxes),) = renderer.calls
    assert (recording, frame) == (REC, 0)
    assert {b.role for b in boxes} == {"object", "person"}


def test_asking_again_does_not_render_again(client: TestClient, renderer: Renderer) -> None:
    _rel_clip(client)
    _rel_clip(client)
    assert len(renderer.calls) == 1


def test_the_clip_detail_carries_the_snapshot_url(client: TestClient) -> None:
    clip = _rel_clip(client)
    detail = client.get(f"/api/clips/{clip['id']}").json()
    assert detail["snapshotUrl"] == clip["snapshotUrl"]


def test_a_saved_clip_keeps_its_snapshot_url(client: TestClient) -> None:
    clip = _rel_clip(client)
    saved = client.post("/api/saved-clips", json={"clipId": clip["id"], "note": ""}).json()
    assert saved["clip"]["snapshotUrl"] == clip["snapshotUrl"]


def test_a_demo_clip_has_no_snapshot(client: TestClient) -> None:
    clips = client.post("/api/search", json={**QUESTION, "question": "someone waiting"}).json()
    assert clips["clips"] and all(c["snapshotUrl"] is None for c in clips["clips"])


def test_a_clip_without_a_snapshot_is_a_404(client: TestClient) -> None:
    demo_id = client.post("/api/search", json={**QUESTION, "question": "someone waiting"}).json()[
        "clips"
    ][0]["id"]
    assert_error(client.get(f"/api/clips/{demo_id}/snapshot"), 404, "not_found")


def test_an_unknown_clip_is_a_404(client: TestClient) -> None:
    assert_error(client.get("/api/clips/nope/snapshot"), 404, "not_found")


def test_a_bad_id_is_a_422(client: TestClient) -> None:
    assert_error(client.get("/api/clips/" + "x" * 65 + "/snapshot"), 422, "validation_error")


def test_a_failing_renderer_does_not_break_the_search(
    store: InMemoryLibrary,
    fake_settings: Settings,
    videos_dir: Path,
    tracks: InMemoryTrackStore,
    tmp_path: Path,
) -> None:
    broken = SnapshotStore(tmp_path / "snaps", Renderer(fail=True))
    for client in make_client(store, fake_settings, videos_dir, tracks, broken):
        clip = _rel_clip(client)
        assert clip["snapshotUrl"] is None
        assert_error(client.get(f"/api/clips/{clip['id']}/snapshot"), 404, "not_found")


def test_without_a_snapshot_store_every_url_is_null(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path, tracks: InMemoryTrackStore
) -> None:
    for client in make_client(store, fake_settings, videos_dir, tracks, None):
        assert _rel_clip(client)["snapshotUrl"] is None


def test_the_error_never_shows_a_path_or_the_renderer_message(
    store: InMemoryLibrary,
    fake_settings: Settings,
    videos_dir: Path,
    tracks: InMemoryTrackStore,
    tmp_path: Path,
) -> None:
    broken = SnapshotStore(tmp_path / "snaps", Renderer(fail=True))
    for client in make_client(store, fake_settings, videos_dir, tracks, broken):
        clip = _rel_clip(client)
        body = client.get(f"/api/clips/{clip['id']}/snapshot").text
        assert "exploded" not in body and str(tmp_path) not in body
