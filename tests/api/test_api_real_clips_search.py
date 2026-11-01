"""Searching the two REAL clips: "person carrying a box" finds clip2 with proof, and not clip1.

The tracks come from the committed SAM recordings in demo/sam (no key, no network, no video),
are stitched and stored in a real SQLite file exactly as scripts.ingest_real_clips stores
them, and the API searches them. The snapshot renderer is a fake that records what it was
asked to draw; the picture itself is covered in tests/unit/test_ffmpeg_snapshots.py.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest
from api_support import build_app
from fastapi.testclient import TestClient

from askfootage.adapters.meta.record_replay import ReplayTransport
from askfootage.adapters.meta.sam import (
    DEFAULT_PROMPTS,
    parse_sam_stream,
    sam_request,
    tracks_from_detections,
    video_part,
)
from askfootage.adapters.sqlite.store import SqliteLibraryStore
from askfootage.adapters.sqlite.tracks import SqliteTrackStore
from askfootage.application.library import Library
from askfootage.application.snapshots import SnapshotStore
from askfootage.domain.stitching import stitch_tracks
from askfootage.ports.library_store import NewCamera, Recording
from askfootage.ports.snapshots import SnapshotBox
from askfootage.settings import Settings

DEMO = Path(__file__).resolve().parents[2] / "demo" / "sam"
DAY = date(2026, 10, 30)
JPEG = b"\xff\xd8real-enough\xff\xd9"
NOUNS = ("person", "cardboard box", "hand")


class Renderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, tuple[SnapshotBox, ...]]] = []

    def render(
        self, recording_id: str, frame: int, boxes: Sequence[SnapshotBox], destination: Path
    ) -> None:
        self.calls.append((recording_id, frame, tuple(boxes)))
        destination.write_bytes(JPEG)


def _store_real_tracks(tracks: SqliteTrackStore) -> None:
    manifest = json.loads((DEMO / "manifest.json").read_text(encoding="utf-8"))
    replay = ReplayTransport(DEMO)
    for clip, entry in manifest["clips"].items():
        for noun in NOUNS:
            prompt = DEFAULT_PROMPTS.get(noun, noun)
            reply = replay.send(sam_request(prompt, video_part(entry["file_id"])))
            found = tracks_from_detections(noun, parse_sam_stream(reply.body))
            tracks.save_tracks(clip, noun, stitch_tracks(found))


@pytest.fixture
def renderer() -> Renderer:
    return Renderer()


@pytest.fixture
def client(
    tmp_path: Path, fake_settings: Settings, videos_dir: Path, renderer: Renderer
) -> Iterator[TestClient]:
    library = SqliteLibraryStore(tmp_path / "library.sqlite")
    library.add_camera(
        NewCamera(
            "Real clips",
            "192.0.2.10",
            "replay",
            "online",
            None,
            None,
            datetime(2026, 10, 30, tzinfo=UTC),
        )
    )
    library.add_recording(Recording("clip1", "CAM-001", DAY, time(9, 0), 10, "ready"))
    library.add_recording(Recording("clip2", "CAM-001", DAY, time(9, 30), 10, "ready"))
    tracks = SqliteTrackStore(library)
    _store_real_tracks(tracks)
    app = build_app(
        None,  # type: ignore[arg-type]
        fake_settings,
        videos_dir,
        library=Library.from_store(library),
        tracks=tracks,
        snapshots=SnapshotStore(tmp_path / "snapshots", renderer),
    )
    with TestClient(app) as test_client:
        yield test_client


def ask(client: TestClient, question: str = "person carrying a box") -> dict[str, object]:
    response = client.post("/api/search", json={"question": question, "day": DAY.isoformat()})
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_clip2_is_returned_and_clip1_is_not(client: TestClient) -> None:
    answer = ask(client)
    assert [c["recordingId"] for c in answer["clips"]] == ["clip2"]  # type: ignore[index]


def test_clip2_comes_with_proof_of_a_carry(client: TestClient) -> None:
    answer = ask(client)
    (proof,) = answer["proofs"]  # type: ignore[misc]
    assert proof["relation"] == "carrying"
    assert proof["trackLabels"] == ["person", "cardboard box"]
    assert (proof["startFrame"], proof["endFrame"]) == (6, 23)
    assert proof["startSeconds"] == pytest.approx(1.2)
    assert proof["endSeconds"] == pytest.approx(4.8)
    assert proof["clipId"] == answer["clips"][0]["id"]  # type: ignore[index]
    measures = {m["name"]: m["value"] for m in proof["measures"]}
    assert measures["motion_agreement"] >= 0.6


def test_clip1_is_judged_from_its_tracks_not_reported_as_unindexed(client: TestClient) -> None:
    answer = ask(client)
    assert answer["note"] is None


def test_the_clip_window_covers_the_carry(client: TestClient) -> None:
    (clip,) = ask(client)["clips"]  # type: ignore[misc]
    assert clip["startSeconds"] <= 1 and clip["endSeconds"] >= 5
    assert clip["evidence"][0]["kind"] == "carrying"


def test_other_wordings_give_the_same_answer(client: TestClient) -> None:
    for question in ("someone carrying a cardboard box", "who is carrying a box?"):
        assert [c["recordingId"] for c in ask(client, question)["clips"]] == ["clip2"]  # type: ignore[index]


def test_the_snapshot_is_taken_at_the_first_carrying_frame_with_both_boxes(
    client: TestClient, renderer: Renderer
) -> None:
    ask(client)
    ((recording, frame, boxes),) = renderer.calls
    assert (recording, frame) == ("clip2", 6)
    by_role = {b.role: (b.x1, b.y1, b.x2, b.y2) for b in boxes}
    assert by_role["object"] == (1495, 613, 1741, 723)
    assert by_role["person"] == (1558, 301, 1906, 1037)


def test_the_snapshot_is_served_and_linked_from_the_clip(client: TestClient) -> None:
    (clip,) = ask(client)["clips"]  # type: ignore[misc]
    assert clip["snapshotUrl"] == f"/api/clips/{clip['id']}/snapshot"
    image = client.get(clip["snapshotUrl"])
    assert image.headers["content-type"] == "image/jpeg" and image.content == JPEG
    assert client.get(f"/api/clips/{clip['id']}").json()["snapshotUrl"] == clip["snapshotUrl"]
