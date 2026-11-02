"""The committed recordings of the real SAM replies (demo/sam) replay with no key.

These tests read only files in the repository, so CI and judges run them without a key, a
network or the footage. The last class needs the prepared videos (data/ is not committed)
and is skipped without them.
"""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from askfootage.adapters.meta.record_replay import ReplayTransport, fingerprint
from askfootage.adapters.meta.sam import (
    SamPerception,
    parse_sam_stream,
    sam_request,
    tracks_from_detections,
    upload_request,
    video_part,
)
from askfootage.domain.relations import DEFAULT_THRESHOLDS, carrying
from askfootage.domain.stitching import merge_intervals, stitch_tracks
from askfootage.domain.timebase import Timebase
from askfootage.domain.tracks import Track

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demo" / "sam"
PREPARED = ROOT / "data" / "prepared"
MAX_BYTES = 100 * 1024
PREPARED_FRAMES = {"clip1": 47, "clip2": 49}
"""Frames in each prepared 5 fps video, counted with ffprobe -count_frames."""

# What the real replies contain: (clip, prompt) -> (detections, first frame, last frame).
EXPECTED = {
    ("clip1", "person"): (45, 0, 42),
    ("clip1", "box"): (0, None, None),
    ("clip1", "hand"): (31, 0, 40),
    ("clip2", "person"): (68, 0, 48),
    ("clip2", "box"): (28, 6, 46),
    ("clip2", "hand"): (26, 3, 35),
}


def manifest() -> dict[str, dict[str, object]]:
    return json.loads((DEMO / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def reply_for(clip: str, prompt: str) -> str:
    entry = manifest()["clips"][clip]  # type: ignore[index]
    request = sam_request(prompt, video_part(entry["file_id"]))
    return ReplayTransport(DEMO).send(request).body


def test_the_manifest_lists_both_clips_and_all_three_nouns() -> None:
    clips = manifest()["clips"]
    assert set(clips) == {"clip1", "clip2"}  # type: ignore[arg-type]
    for clip in clips:  # type: ignore[attr-defined]
        assert set(clips[clip]["requests"]) == {"person", "box", "hand"}  # type: ignore[index]


def test_every_recording_is_under_the_size_target_and_holds_no_mask() -> None:
    files = list(DEMO.glob("*.json"))
    assert len(files) == 2 * 3 + 2 + 1
    for path in files:
        assert path.stat().st_size < MAX_BYTES, path.name
        assert "<|mask" not in path.read_text(encoding="utf-8"), path.name


def test_every_recording_is_named_by_its_own_fingerprint() -> None:
    for path in DEMO.glob("*.json"):
        if path.name == "manifest.json":
            continue
        assert json.loads(path.read_text(encoding="utf-8"))["fingerprint"] == path.stem


@pytest.mark.parametrize(("clip", "prompt"), sorted(EXPECTED))
def test_each_request_replays_and_holds_what_the_real_reply_held(clip: str, prompt: str) -> None:
    entry = manifest()["clips"][clip]  # type: ignore[index]
    request = sam_request(prompt, video_part(entry["file_id"]))
    assert fingerprint(request) == entry["requests"][prompt]["fingerprint"]
    found = parse_sam_stream(reply_for(clip, prompt))
    count, first, last = EXPECTED[(clip, prompt)]
    assert len(found) == count
    if count:
        assert (min(d.frame for d in found), max(d.frame for d in found)) == (first, last)


@pytest.mark.parametrize(("clip", "prompt"), sorted(EXPECTED))
def test_frames_fit_the_prepared_video_and_start_from_zero(clip: str, prompt: str) -> None:
    found = parse_sam_stream(reply_for(clip, prompt))
    assert all(0 <= d.frame < PREPARED_FRAMES[clip] for d in found)
    assert all(d.time_s == Timebase(5.0).frame_to_seconds(d.frame) for d in found)


def test_frame_zero_exists_so_frames_are_zero_based() -> None:
    assert min(d.frame for d in parse_sam_stream(reply_for("clip1", "person"))) == 0


def test_the_last_frame_of_clip2_is_the_last_index_of_its_49_frames() -> None:
    found = parse_sam_stream(reply_for("clip2", "person"))
    assert max(d.frame for d in found) == PREPARED_FRAMES["clip2"] - 1


def test_clip2_has_a_box_from_frame_6_that_moves_left() -> None:
    (track,) = tracks_from_detections("cardboard box", parse_sam_stream(reply_for("clip2", "box")))
    first, last = track.box_at(6), track.box_at(46)
    assert first is not None and last is not None
    assert last.center[0] < first.center[0]


@pytest.mark.skipif(not PREPARED.is_dir(), reason="the prepared videos are not in this checkout")
class TestWithThePreparedVideos:
    @pytest.mark.parametrize("clip", ["clip1", "clip2"])
    def test_the_video_is_the_one_that_was_uploaded(self, clip: str) -> None:
        video = PREPARED / clip / "prepared.mp4"
        entry = manifest()["clips"][clip]  # type: ignore[index]
        assert hashlib.sha256(video.read_bytes()).hexdigest() == entry["prepared_sha256"]
        assert fingerprint(upload_request(video)) == entry["upload_fingerprint"]

    @pytest.mark.parametrize(("clip", "prompt"), sorted(EXPECTED))
    def test_sam_perception_replays_end_to_end_with_no_key(self, clip: str, prompt: str) -> None:
        perception = SamPerception(ReplayTransport(DEMO), prompts={})
        tracks = perception.detect_and_track(PREPARED / clip / "prepared.mp4", prompt)
        assert sum(len(t.points) for t in tracks) == EXPECTED[(clip, prompt)][0]


class TestRelationsOnTheRealReplies:
    """The relation rules over the real tracks, labels in labels/ (never edited to fit)."""

    @staticmethod
    def stitched(clip: str, prompt: str, noun: str) -> list[Track]:
        found = parse_sam_stream(reply_for(clip, prompt))
        return stitch_tracks(tracks_from_detections(noun, found))

    def test_clip2_box_is_carried_from_1_2_to_4_8_seconds(self) -> None:
        people = self.stitched("clip2", "person", "person")
        boxes = self.stitched("clip2", "box", "cardboard box")
        (interval,) = merge_intervals(carrying(people, boxes), 3)
        assert (interval.start_frame, interval.end_frame) == (6, 23)
        assert Timebase(5.0).frame_to_seconds(interval.start_frame) == pytest.approx(1.2)

    def test_the_old_tolerance_of_one_half_would_miss_the_confirmed_carry(self) -> None:
        people = self.stitched("clip2", "person", "person")
        boxes = self.stitched("clip2", "box", "cardboard box")
        strict = replace(DEFAULT_THRESHOLDS, carry_motion_tolerance=0.5)
        assert carrying(people, boxes, strict) == []

    def test_clip1_has_no_box_so_nothing_is_carried(self) -> None:
        people = self.stitched("clip1", "person", "person")
        boxes = self.stitched("clip1", "box", "cardboard box")
        assert boxes == []
        assert carrying(people, boxes) == []
