"""Evidence snapshots: which frame and boxes a carrying clip is shown with, and where they go."""

from collections.abc import Sequence
from datetime import date, time
from pathlib import Path

import pytest

from askfootage.application.search_relations import ClipProof, SnapshotPlan, snapshot_plan
from askfootage.application.snapshots import SnapshotStore
from askfootage.domain.intervals import Interval, IntervalEvidence
from askfootage.domain.models import BoundingBox
from askfootage.domain.tracks import Track, TrackPoint
from askfootage.ports.library_store import Clip, Evidence
from askfootage.ports.snapshots import SnapshotBox


def track(track_id: int, label: str, boxes: dict[int, tuple[float, float, float, float]]) -> Track:
    return Track(
        track_id, label, tuple(TrackPoint(f, BoundingBox(*b)) for f, b in sorted(boxes.items()))
    )


def carrying(start: int, end: int) -> Interval:
    return Interval(start, end, IntervalEvidence("carrying", (0, 3), ()))


class TestPlan:
    def test_the_frame_is_the_first_one_where_both_were_seen(self) -> None:
        person = track(0, "person", {f: (10, 10, 50, 90) for f in range(4, 20)})
        box = track(3, "cardboard box", {f: (20, 40, 30, 50) for f in range(6, 20)})
        plan = snapshot_plan(carrying(5, 19), {("person", 0): person, ("cardboard box", 3): box})
        assert plan is not None and plan.frame == 6

    def test_there_is_one_object_box_and_one_person_box_with_their_pixels(self) -> None:
        person = track(0, "person", {6: (10, 10, 50, 90)})
        box = track(3, "cardboard box", {6: (20, 40, 30, 50)})
        plan = snapshot_plan(carrying(6, 6), {("person", 0): person, ("cardboard box", 3): box})
        assert plan is not None
        assert {(b.role, b.x1, b.y1, b.x2, b.y2) for b in plan.boxes} == {
            ("person", 10, 10, 50, 90),
            ("object", 20, 40, 30, 50),
        }

    def test_no_shared_frame_gives_no_plan(self) -> None:
        person = track(0, "person", {5: (10, 10, 50, 90)})
        box = track(3, "cardboard box", {9: (20, 40, 30, 50)})
        plan = snapshot_plan(carrying(5, 9), {("person", 0): person, ("cardboard box", 3): box})
        assert plan is None

    def test_only_a_carrying_interval_has_a_plan(self) -> None:
        zone = Interval(0, 5, IntervalEvidence("in_zone", (3,), ()))
        box = track(3, "cardboard box", {0: (1, 1, 2, 2)})
        assert snapshot_plan(zone, {("cardboard box", 3): box}) is None


class Renderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, Sequence[SnapshotBox], Path]] = []

    def render(
        self, recording_id: str, frame: int, boxes: Sequence[SnapshotBox], destination: Path
    ) -> None:
        self.calls.append((recording_id, frame, boxes, destination))
        destination.write_bytes(b"jpeg")


def clip(clip_id: str = "rel-abc", recording: str = "clip2") -> Clip:
    return Clip(
        id=clip_id,
        recording_id=recording,
        day=date(2026, 10, 30),
        start_time=time(9, 30),
        start_seconds=1,
        end_seconds=5,
        label="Person carrying a cardboard box",
        evidence=(Evidence("carrying", "Carrying · 4 s"),),
        zone=None,
        why_matched="because",
        key_frames=(),
        thumbnail_url=None,
    )


def proof(plan: SnapshotPlan | None) -> ClipProof:
    return ClipProof(
        "rel-abc", "carrying", 6, 23, 1.2, 4.8, (0, 3), ("person", "cardboard box"), (), (), plan
    )


PLAN = SnapshotPlan(6, (SnapshotBox("object", 1, 2, 3, 4), SnapshotBox("person", 5, 6, 7, 8)))


class TestStore:
    def test_creating_renders_the_planned_frame_into_a_file_named_by_the_clip(
        self, tmp_path: Path
    ) -> None:
        renderer = Renderer()
        store = SnapshotStore(tmp_path / "snaps", renderer)
        store.create(clip(), proof(PLAN))
        assert [(c[0], c[1]) for c in renderer.calls] == [("clip2", 6)]
        written_to = renderer.calls[0][3]
        assert written_to.parent == tmp_path / "snaps" and written_to.suffix == ".jpg"
        assert not written_to.exists()  # moved into place under the clip's own name
        assert renderer.calls[0][2] == PLAN.boxes
        assert store.has("rel-abc")
        assert store.path_for("rel-abc").read_bytes() == b"jpeg"

    def test_an_existing_snapshot_is_not_rendered_again(self, tmp_path: Path) -> None:
        renderer = Renderer()
        store = SnapshotStore(tmp_path, renderer)
        store.create(clip(), proof(PLAN))
        store.create(clip(), proof(PLAN))
        assert len(renderer.calls) == 1

    def test_a_proof_without_a_plan_makes_nothing(self, tmp_path: Path) -> None:
        renderer = Renderer()
        store = SnapshotStore(tmp_path, renderer)
        store.create(clip(), proof(None))
        assert renderer.calls == [] and not store.has("rel-abc")

    def test_a_failed_render_leaves_no_file(self, tmp_path: Path) -> None:
        class Broken(Renderer):
            def render(self, recording_id, frame, boxes, destination) -> None:  # noqa: ANN001
                destination.write_bytes(b"half")
                raise OSError("disk")

        store = SnapshotStore(tmp_path, Broken())
        with pytest.raises(OSError):
            store.create(clip(), proof(PLAN))
        assert not store.has("rel-abc")
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize("bad", ["../x", "a/b", "", "a b", "x" * 65, "..\\x"])
    def test_an_unsafe_id_never_becomes_a_path(self, tmp_path: Path, bad: str) -> None:
        store = SnapshotStore(tmp_path, Renderer())
        with pytest.raises(ValueError):
            store.path_for(bad)
        assert not store.has(bad)
