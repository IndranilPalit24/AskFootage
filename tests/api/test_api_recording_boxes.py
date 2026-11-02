"""GET /api/recordings/{id}/boxes: the boxes of a recording's stored tracks."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from api_fakes import InMemoryLibrary, load_example
from api_support import FAKE_KEY, assert_error, build_app
from fastapi.testclient import TestClient

from askfootage.application.recording_boxes import MIN_BOX_RUN_SECONDS, long_runs
from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint
from askfootage.settings import Settings

REC = "rec-1029-0600"
REPO = Path(__file__).resolve().parents[2]
REAL_LIBRARY = REPO / "data" / "real" / "library.sqlite"


def track(label: str, track_id: int, frames: list[int]) -> Track:
    return Track(
        track_id=track_id,
        label=label,
        points=tuple(
            TrackPoint(frame=f, box=BoundingBox(f, f + 1.0, f + 2.0, f + 3.0))
            for f in sorted(frames)
        ),
    )


class FakeTracks:
    """A track store with labels_for, holding tracks for REC only."""

    def __init__(self, tracks: list[Track]) -> None:
        self._tracks = tracks

    def labels_for(self, video_id: str) -> list[str]:
        return sorted({t.label for t in self._tracks}) if video_id == REC else []

    def tracks_for(self, video_id: str, label: str) -> list[Track]:
        if video_id != REC:
            return []
        return sorted((t for t in self._tracks if t.label == label), key=lambda t: t.track_id)

    def save_tracks(self, video_id: str, concept: str, tracks: object) -> None:
        raise AssertionError

    def delete_video(self, video_id: str) -> int:
        raise AssertionError


def client_with(
    store: InMemoryLibrary, settings: Settings, videos: Path, tracks: object | None, **kw: object
) -> TestClient:
    return TestClient(build_app(store, settings, videos, tracks=tracks, **kw))


def long_frames() -> list[int]:
    return list(range(6, 24))


def test_unknown_recording_is_the_standard_404(client: TestClient) -> None:
    assert_error(client.get("/api/recordings/nope/boxes"), 404, "not_found")


def test_bad_id_is_422(client: TestClient) -> None:
    assert_error(client.get("/api/recordings/bad id!/boxes"), 422, "validation_error")


def test_app_without_a_track_store_gives_empty_tracks_and_the_demo_size(
    client: TestClient,
) -> None:
    response = client.get(f"/api/recordings/{REC}/boxes")
    assert response.status_code == 200
    assert response.json() == {
        "recordingId": REC,
        "frameWidth": 1920,
        "frameHeight": 1080,
        "fps": 5,
        "tracks": [],
    }


def test_known_recording_without_tracks_is_empty(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    with client_with(store, fake_settings, videos_dir, FakeTracks([])) as client:
        body = client.get(f"/api/recordings/{REC}/boxes").json()
    assert body["tracks"] == []


def test_hands_are_excluded_and_roles_set(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    tracks = FakeTracks(
        [
            track("hand", 0, long_frames()),
            track("cardboard box", 0, long_frames()),
            track("person", 0, long_frames()),
        ]
    )
    with client_with(
        store, fake_settings, videos_dir, tracks, frame_size=lambda _id: (1280.0, 720.0)
    ) as client:
        body = client.get(f"/api/recordings/{REC}/boxes").json()
    assert (body["frameWidth"], body["frameHeight"], body["fps"]) == (1280, 720, 5)
    assert [(t["label"], t["role"]) for t in body["tracks"]] == [
        ("person", "person"),
        ("cardboard box", "object"),
    ]


def test_points_are_ordered_by_frame_and_fields_are_camel_case(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    tracks = FakeTracks([track("person", 3, [9, 2, 5, 3, 4])])
    with client_with(
        store, fake_settings, videos_dir, tracks, frame_size=lambda _id: (100.0, 50.0)
    ) as client:
        body = client.get(f"/api/recordings/{REC}/boxes").json()
    assert set(body) == {"recordingId", "frameWidth", "frameHeight", "fps", "tracks"}
    (only,) = body["tracks"]
    assert set(only) == {"trackId", "label", "role", "points"}
    assert only["trackId"] == 3
    assert [p["frame"] for p in only["points"]] == [2, 3, 4, 5, 9]
    assert set(only["points"][0]) == {"frame", "x1", "y1", "x2", "y2"}


def test_unknown_frame_size_with_tracks_is_a_safe_500(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    tracks = FakeTracks([track("person", 0, [1, 2])])
    app = build_app(store, fake_settings, videos_dir, tracks=tracks)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/api/recordings/{REC}/boxes")
    assert_error(response, 500, "internal_error")
    assert FAKE_KEY not in response.text


def test_no_secret_or_path_in_the_response(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    tracks = FakeTracks([track("person", 0, long_frames())])
    with client_with(
        store, fake_settings, videos_dir, tracks, frame_size=lambda _id: (10.0, 10.0)
    ) as client:
        text = client.get(f"/api/recordings/{REC}/boxes").text
    assert FAKE_KEY not in text
    assert str(videos_dir) not in text


def test_the_contract_example_shape() -> None:
    example = load_example("recording-boxes.json")
    assert set(example) == {"recordingId", "frameWidth", "frameHeight", "fps", "tracks"}


# --- Short object runs are noise ------------------------------------------------------------


def test_minimum_run_is_one_second() -> None:
    assert MIN_BOX_RUN_SECONDS == 1.0


def test_object_fragments_are_dropped_but_a_person_keeps_every_point(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    noisy = [*long_frames(), 31, 32, 33, 34, 39, 40, 41, 42, 45, 46]
    tracks = FakeTracks([track("cardboard box", 0, noisy), track("person", 0, noisy)])
    with client_with(
        store, fake_settings, videos_dir, tracks, frame_size=lambda _id: (10.0, 10.0)
    ) as client:
        body = client.get(f"/api/recordings/{REC}/boxes").json()
    by_label = {t["label"]: [p["frame"] for p in t["points"]] for t in body["tracks"]}
    assert by_label["cardboard box"] == long_frames()
    assert by_label["person"] == sorted(noisy)


def test_a_one_frame_gap_keeps_a_run_and_short_runs_vanish() -> None:
    assert long_runs([1, 2, 4, 5, 6], 5.0) == {1, 2, 4, 5, 6}
    assert long_runs([1, 2, 3, 4], 5.0) == set()
    assert long_runs([1, 2, 5, 6, 7], 5.0) == set()
    assert long_runs([], 5.0) == set()


def test_a_track_of_only_noise_is_left_out(
    store: InMemoryLibrary, fake_settings: Settings, videos_dir: Path
) -> None:
    tracks = FakeTracks([track("cardboard box", 0, [1, 2, 3])])
    with client_with(
        store, fake_settings, videos_dir, tracks, frame_size=lambda _id: (10.0, 10.0)
    ) as client:
        body = client.get(f"/api/recordings/{REC}/boxes").json()
    assert body["tracks"] == []


# --- The real library --------------------------------------------------------------------------


@pytest.fixture
def real_client(tmp_path: Path) -> Iterator[TestClient]:
    if not REAL_LIBRARY.exists():
        pytest.skip("data/real/library.sqlite is not present")
    from askfootage.interfaces.real_clips import create_app

    data = tmp_path / "real"
    data.mkdir()
    shutil.copyfile(REAL_LIBRARY, data / "library.sqlite")
    for clip in ("clip1", "clip2"):
        source = REPO / "data" / "real" / clip
        if source.exists():
            shutil.copytree(source, data / clip)
    with TestClient(create_app(data, tmp_path / "videos")) as client:
        yield client


def test_real_clip2_object_points_are_the_solid_run_only(real_client: TestClient) -> None:
    body = real_client.get("/api/recordings/clip2/boxes").json()
    assert all(t["label"] != "hand" for t in body["tracks"])
    (box,) = [t for t in body["tracks"] if t["role"] == "object"]
    assert box["label"] == "cardboard box"
    assert [p["frame"] for p in box["points"]] == list(range(6, 24))
    assert len([t for t in body["tracks"] if t["role"] == "person"]) == 4
    assert body["fps"] == 5
    assert body["frameWidth"] > 0 and body["frameHeight"] > 0


def test_real_clip1_has_only_people(real_client: TestClient) -> None:
    body = real_client.get("/api/recordings/clip1/boxes").json()
    assert body["tracks"] and {t["role"] for t in body["tracks"]} == {"person"}
