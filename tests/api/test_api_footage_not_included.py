"""Contract 1.9.0: recordings without footage (hasFootage false).

A generated recording is listed and counted so the library looks populated, but it has no
video: its video, poster and clip snapshot answer 404 footage_not_included (never a stock
clip), its posterUrl is null, and search never returns it. Recordings with real footage keep
working, with Range support. Fake stores, fake renderers, no network.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, time
from pathlib import Path
from typing import Any

import pytest
from api_fakes import (
    FAKE_MP4,
    InMemoryLibrary,
    InMemoryTrackStore,
    clip_from_json,
    load_example,
    make_track,
)
from api_support import FAKE_KEY, assert_error, build_app
from fastapi.testclient import TestClient

from askfootage.application.posters import PosterStore
from askfootage.application.snapshots import SnapshotStore
from askfootage.interfaces.api.footage import DemoFootageSource
from askfootage.ports.library_store import Recording
from askfootage.settings import Settings

GEN = "gen-1029-0001"
GEN_CLIP = "clip-gen-1029-0001"
REAL = "rec-1029-0600"
DAY = "2026-10-29"
MESSAGE = "Footage is not included for this recording."
JPEG = b"\xff\xd8fake\xff\xd9"
RECORDING_KEYS = {
    "id",
    "camera",
    "day",
    "startTime",
    "lengthSeconds",
    "status",
    "posterUrl",
    "hasFootage",
}


def without_footage(recording: Recording) -> Recording:
    """The same recording marked as having no footage (a generated row)."""
    return replace(recording, has_footage=False)


class FakePosterRenderer:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def render(self, video: Path, at_seconds: int, destination: Path) -> None:
        self.calls.append(video)
        destination.write_bytes(JPEG)


class FakeSnapshotRenderer:
    def render(self, recording_id: str, frame: int, boxes: Any, destination: Path) -> None:
        destination.write_bytes(JPEG)


def _generated(recording_id: str, start: time, status: str = "ready", day: str = DAY) -> Recording:
    base = Recording(recording_id, "CAM-001", date.fromisoformat(day), start, 600, status)  # type: ignore[arg-type]
    return without_footage(base)


def _carrying_clip(recording_id: str, clip_id: str) -> Any:
    """A stored demo clip with carrying evidence, as the keyword search would match."""
    data = copy.deepcopy(load_example("clip-detail.json"))
    data.update(
        id=clip_id,
        recordingId=recording_id,
        day=DAY,
        startTime="08:00:05",
        startSeconds=5,
        endSeconds=25,
    )
    return clip_from_json(data)


@pytest.fixture
def library(store: InMemoryLibrary) -> InMemoryLibrary:
    """The demo dataset plus generated recordings (one ready, one waiting) with a clip."""
    store.add_recording(_generated(GEN, time(8, 0)))
    store.add_recording(_generated("gen-1029-0002", time(8, 30), "waiting"))
    store.add_clip(_carrying_clip(GEN, GEN_CLIP))
    return store


@pytest.fixture
def tracks(library: InMemoryLibrary) -> InMemoryTrackStore:
    """Stored tracks for the generated recording too: it must still never match."""
    found = InMemoryTrackStore(library)
    found.save_tracks(GEN, "person", [make_track(1, "person", range(30))])
    found.save_tracks(GEN, "cardboard box", [make_track(2, "cardboard box", range(30))])
    return found


@pytest.fixture
def poster_renderer() -> FakePosterRenderer:
    return FakePosterRenderer()


@pytest.fixture
def client(
    library: InMemoryLibrary,
    tracks: InMemoryTrackStore,
    fake_settings: Settings,
    videos_dir: Path,
    poster_renderer: FakePosterRenderer,
    tmp_path: Path,
) -> Iterator[TestClient]:
    app = build_app(
        library,
        fake_settings,
        videos_dir,
        tracks=tracks,
        posters=PosterStore(tmp_path / "posters", poster_renderer),
        snapshots=SnapshotStore(tmp_path / "snaps", FakeSnapshotRenderer()),  # type: ignore[arg-type]
    )
    with TestClient(app) as test_client:
        yield test_client


def _search(client: TestClient, question: str, camera: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"question": question, "day": DAY}
    if camera:
        body["camera"] = camera
    response = client.post("/api/search", json=body)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


# --- The three routes ---------------------------------------------------------------------------


def test_the_video_of_a_recording_without_footage_is_404_footage_not_included(
    client: TestClient, tmp_path: Path
) -> None:
    response = client.get(f"/api/recordings/{GEN}/video")
    assert assert_error(response, 404, "footage_not_included") == MESSAGE
    assert FAKE_MP4 not in response.content
    assert str(tmp_path) not in response.text and "clip1" not in response.text


def test_a_range_request_for_it_is_still_404_not_a_stock_clip(client: TestClient) -> None:
    response = client.get(f"/api/recordings/{GEN}/video", headers={"Range": "bytes=0-7"})
    assert_error(response, 404, "footage_not_included")


def test_the_poster_of_a_recording_without_footage_is_404_and_renders_nothing(
    client: TestClient, poster_renderer: FakePosterRenderer, tmp_path: Path
) -> None:
    for params in ({}, {"t": 5}):
        response = client.get(f"/api/recordings/{GEN}/poster", params=params)
        assert assert_error(response, 404, "footage_not_included") == MESSAGE
        assert str(tmp_path) not in response.text
    assert poster_renderer.calls == []


def test_the_snapshot_of_a_clip_without_footage_is_404_footage_not_included(
    client: TestClient, tmp_path: Path
) -> None:
    response = client.get(f"/api/clips/{GEN_CLIP}/snapshot")
    assert assert_error(response, 404, "footage_not_included") == MESSAGE
    assert str(tmp_path) not in response.text


def test_an_unknown_recording_or_clip_is_still_plain_not_found(client: TestClient) -> None:
    assert_error(client.get("/api/recordings/rec-nope/video"), 404, "not_found")
    assert_error(client.get("/api/recordings/rec-nope/poster"), 404, "not_found")
    assert_error(client.get("/api/clips/clip-nope/snapshot"), 404, "not_found")


def test_a_clip_of_a_recording_with_footage_but_no_snapshot_is_still_not_found(
    client: TestClient,
) -> None:
    assert_error(client.get("/api/clips/clip-1029-104215/snapshot"), 404, "not_found")


# --- Recordings with real footage keep working --------------------------------------------------


def test_real_footage_still_streams_with_range_support(client: TestClient) -> None:
    whole = client.get(f"/api/recordings/{REAL}/video")
    assert whole.status_code == 200 and whole.content == FAKE_MP4
    assert whole.headers["accept-ranges"] == "bytes"
    part = client.get(f"/api/recordings/{REAL}/video", headers={"Range": "bytes=0-7"})
    assert part.status_code == 206
    assert part.headers["content-range"] == f"bytes 0-7/{len(FAKE_MP4)}"
    assert part.content == FAKE_MP4[:8]


def test_real_footage_still_has_a_poster(
    client: TestClient, poster_renderer: FakePosterRenderer
) -> None:
    response = client.get(f"/api/recordings/{REAL}/poster")
    assert response.status_code == 200 and response.content == JPEG
    assert len(poster_renderer.calls) == 1


def test_the_demo_source_never_maps_a_recording_without_footage_to_the_stock_clip(
    videos_dir: Path,
) -> None:
    source = DemoFootageSource(videos_dir)
    assert source.footage_for(_generated(GEN, time(8, 0))) is None
    real = Recording(REAL, "CAM-001", date.fromisoformat(DAY), time(6, 0), 60, "ready")
    assert source.footage_for(real) == videos_dir / "clip1.mp4"


# --- hasFootage and posterUrl on Recording ------------------------------------------------------


def test_recordings_carry_has_footage_and_no_other_new_field(client: TestClient) -> None:
    listed = client.get("/api/recordings", params={"day": DAY, "camera": "CAM-001"}).json()
    assert all(set(item) == RECORDING_KEYS for item in listed)
    by_id = {item["id"]: item for item in listed}
    assert by_id[REAL]["hasFootage"] is True
    assert by_id[REAL]["posterUrl"] == f"/api/recordings/{REAL}/poster"
    for generated in (GEN, "gen-1029-0002"):
        assert by_id[generated]["hasFootage"] is False
        assert by_id[generated]["posterUrl"] is None


def test_the_word_demo_never_names_the_origin(client: TestClient) -> None:
    text = client.get("/api/recordings", params={"day": DAY}).text.lower()
    assert "demo" not in text and "origin" not in text and "generated" not in text


def test_the_clip_of_a_recording_without_footage_has_no_poster(client: TestClient) -> None:
    detail = client.get(f"/api/clips/{GEN_CLIP}")
    assert detail.status_code == 200
    assert detail.json()["posterUrl"] is None
    assert detail.json()["snapshotUrl"] is None


def test_counts_and_day_lists_include_generated_recordings(
    client: TestClient, library: InMemoryLibrary
) -> None:
    listed = client.get("/api/recordings", params={"day": DAY}).json()
    assert {GEN, "gen-1029-0002"} <= {item["id"] for item in listed}
    days = {d["day"]: d for d in client.get("/api/days").json()}
    assert days[DAY] == {"day": DAY, "recordings": 10, "ready": 8}
    camera = client.get("/api/cameras/CAM-001").json()
    assert camera["recordingCount"] == sum(
        1 for r in library.recordings.values() if r.camera == "CAM-001"
    )


# --- Search never returns a generated recording -------------------------------------------------


@pytest.mark.parametrize(
    "question",
    ["someone carrying a box", "person carrying a box", "someone waiting", "any person", "people"],
)
def test_search_never_returns_a_recording_without_footage(
    client: TestClient, question: str
) -> None:
    answer = _search(client, question)
    assert GEN not in {clip["recordingId"] for clip in answer["clips"]}
    assert GEN_CLIP not in {clip["id"] for clip in answer["clips"]}
    assert all(not proof["clipId"].startswith("rel-" + GEN) for proof in answer["proofs"])


def test_search_without_tracks_does_not_return_it_either(
    library: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    with TestClient(build_app(library, fake_settings, videos_dir)) as plain:
        answer = _search(plain, "someone carrying a box")
    assert answer["clips"]
    assert GEN not in {clip["recordingId"] for clip in answer["clips"]}


def test_generated_recordings_do_not_change_the_search_answer_or_its_note(
    client: TestClient, fake_settings: Settings, videos_dir: Path
) -> None:
    baseline_library = InMemoryLibrary.from_seed()
    with TestClient(build_app(baseline_library, fake_settings, videos_dir)) as baseline:
        expected = _search(baseline, "someone carrying a box")
    got = _search(client, "someone carrying a box")
    assert [c["id"] for c in got["clips"]] == [c["id"] for c in expected["clips"]]
    assert got["note"] == expected["note"]  # a generated row is not "still being indexed"


def test_a_day_of_only_generated_recordings_finds_nothing_and_adds_no_false_note(
    library: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    library.add_recording(_generated("gen-1101-0001", time(9, 0), day="2026-11-01"))
    with TestClient(build_app(library, fake_settings, videos_dir)) as client:
        response = client.post(
            "/api/search", json={"question": "someone waiting", "day": "2026-11-01"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["clips"] == []
    assert "still being indexed" not in (body["note"] or "")


# --- Nothing leaks ------------------------------------------------------------------------------


def test_no_response_about_a_recording_without_footage_leaks_a_key_or_path(
    client: TestClient, tmp_path: Path, videos_dir: Path
) -> None:
    urls = [
        f"/api/recordings/{GEN}/video",
        f"/api/recordings/{GEN}/poster",
        f"/api/clips/{GEN_CLIP}/snapshot",
        f"/api/clips/{GEN_CLIP}",
        f"/api/recordings?day={DAY}",
    ]
    for url in urls:
        text = client.get(url).text
        for secret in (FAKE_KEY, str(tmp_path), str(videos_dir), "Traceback", "C:\\"):
            assert secret not in text


# --- Contract -----------------------------------------------------------------------------------


def test_the_error_example_matches_the_fixed_message() -> None:
    assert load_example("footage-not-included.json") == {
        "error": {"code": "footage_not_included", "message": MESSAGE}
    }


def test_the_recordings_example_has_has_footage_on_every_row() -> None:
    rows = load_example("recordings.json")
    assert rows and all(set(row) == RECORDING_KEYS for row in rows)
    assert all(isinstance(row["hasFootage"], bool) for row in rows)
