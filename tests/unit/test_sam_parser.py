"""Reading a SAM 3.1 server-sent-events reply into detections and domain tracks.

The fixtures in tests/fixtures/sam are slices of the REAL replies saved in data/spike
(see the README beside them): a handful of frames each, masks stripped except in
clip1_hand_with_masks.sse, which keeps real mask payloads to prove they are ignored.
"""

import json
from pathlib import Path

import pytest

from askfootage.adapters.meta.sam import (
    SamDetection,
    SamStreamError,
    parse_sam_stream,
    strip_masks,
    tracks_from_detections,
)
from askfootage.domain.stitching import stitch_tracks
from askfootage.ports.perception import PerceptionError

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "sam"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def sse(*events: tuple[str, dict[str, object]], done: bool = True) -> str:
    """A minimal reply made of (event name, data) pairs, in the real layout."""
    blocks = [
        f"event: {name}\ndata: {json.dumps({**data, 'type': name}, separators=(',', ':'))}\n\n"
        for name, data in events
    ]
    return "".join(blocks) + ("data: [DONE]\n\n" if done else "")


def completed(text: str, *, status: str = "completed") -> tuple[str, dict[str, object]]:
    output = [{"content": [{"type": "output_text", "text": text}], "type": "message"}]
    response = {"status": status, "error": None, "output": output}
    return ("response.completed", {"response": response})


def reply_with_text(text: str) -> str:
    return sse(("response.created", {}), completed(text))


BOX = "<|box;x1=10;y1=20;x2=110;y2=220;w=200;h=400;c=0.5|>"


class TestRealFixtures:
    def test_box_head_has_three_frames_starting_at_frame_six(self) -> None:
        found = parse_sam_stream(fixture("clip2_box_head.sse"))
        assert [d.frame for d in found] == [6, 7, 8]
        assert {d.object_id for d in found} == {0}

    def test_time_is_the_frame_number_over_five_frames_per_second(self) -> None:
        found = parse_sam_stream(fixture("clip2_box_head.sse"))
        assert [d.time_s for d in found] == pytest.approx([1.2, 1.4, 1.6])

    def test_box_is_in_pixels_and_normalised_by_the_reported_frame_size(self) -> None:
        first = parse_sam_stream(fixture("clip2_box_head.sse"))[0]
        assert (first.box.x1, first.box.y1, first.box.x2, first.box.y2) == (1495, 613, 1741, 723)
        assert (first.frame_width, first.frame_height) == (1920, 1080)
        n = first.norm_box
        assert (n.x1, n.y1, n.x2, n.y2) == pytest.approx(
            (1495 / 1920, 613 / 1080, 1741 / 1920, 723 / 1080)
        )
        assert all(0.0 <= v <= 1.0 for v in (n.x1, n.y1, n.x2, n.y2))

    def test_confidence_is_read(self) -> None:
        first = parse_sam_stream(fixture("clip2_box_head.sse"))[0]
        assert first.confidence == pytest.approx(0.8672199249267578)

    def test_an_empty_reply_means_no_detections(self) -> None:
        assert parse_sam_stream(fixture("clip1_box_empty.sse")) == []

    def test_two_objects_in_one_frame_share_a_line(self) -> None:
        found = parse_sam_stream(fixture("clip1_hand_two_objects.sse"))
        by_frame: dict[int, list[int]] = {}
        for d in found:
            by_frame.setdefault(d.frame, []).append(d.object_id)
        assert by_frame == {0: [0, 1], 1: [0, 1], 2: [0]}

    def test_frame_zero_is_the_first_frame_and_starts_at_zero_seconds(self) -> None:
        found = parse_sam_stream(fixture("clip1_hand_two_objects.sse"))
        assert found[0].frame == 0
        assert found[0].time_s == 0.0

    def test_masks_are_ignored_and_never_kept(self) -> None:
        with_masks = parse_sam_stream(fixture("clip1_hand_with_masks.sse"))
        stripped = parse_sam_stream(fixture("clip1_hand_two_objects.sse"))
        wanted = [d for d in stripped if d.frame in (0, 2)]
        assert with_masks == wanted
        assert "mask" not in repr(with_masks).lower()
        assert "data=" not in repr(with_masks)

    def test_detections_have_no_mask_field(self) -> None:
        assert "mask" not in " ".join(SamDetection.__dataclass_fields__)


class TestTracks:
    def test_detections_become_one_track_per_object_id_labelled_with_the_noun(self) -> None:
        found = parse_sam_stream(fixture("clip1_hand_two_objects.sse"))
        tracks = tracks_from_detections("hand", found)
        assert [(t.track_id, t.label) for t in tracks] == [(0, "hand"), (1, "hand")]
        assert tracks[0].frames == (0, 1, 2)
        assert tracks[1].frames == (0, 1)

    def test_track_boxes_are_pixels(self) -> None:
        found = parse_sam_stream(fixture("clip2_box_head.sse"))
        (track,) = tracks_from_detections("cardboard box", found)
        box = track.box_at(6)
        assert box is not None
        assert (box.x1, box.y1, box.x2, box.y2) == (1495, 613, 1741, 723)

    def test_no_detections_make_no_tracks(self) -> None:
        assert tracks_from_detections("box", []) == []

    def test_ids_are_kept_as_sam_gave_them(self) -> None:
        found = parse_sam_stream(fixture("clip2_person_id_break.sse"))
        tracks = tracks_from_detections("person", found)
        assert {t.track_id: t.frames for t in tracks} == {
            0: (28, 29),
            2: (33, 34),
            3: (33, 34),
            4: (33, 34),
        }

    def test_stitching_does_not_join_ids_that_reappear_on_the_other_side_of_the_frame(
        self,
    ) -> None:
        # Real data: id 0 leaves at the left edge on frame 29 and id 2 enters at the right
        # edge on frame 33, about 1,700 px away. They are different people, not one broken id.
        found = parse_sam_stream(fixture("clip2_person_id_break.sse"))
        stitched = stitch_tracks(tracks_from_detections("person", found))
        assert sorted(t.track_id for t in stitched) == [0, 2, 3, 4]


class TestMaskStripping:
    def test_stripped_reply_parses_to_the_same_detections(self) -> None:
        original = fixture("clip1_hand_with_masks.sse")
        assert parse_sam_stream(strip_masks(original)) == parse_sam_stream(original)

    def test_no_mask_payload_survives(self) -> None:
        stripped = strip_masks(fixture("clip1_hand_with_masks.sse"))
        assert "<|mask" not in stripped
        assert "data=" not in stripped
        assert len(stripped) < len(fixture("clip1_hand_with_masks.sse")) / 2

    def test_every_event_is_kept_and_still_valid_json(self) -> None:
        original = fixture("clip1_hand_with_masks.sse")
        stripped = strip_masks(original)
        assert stripped.count("\nevent: ") == original.count("\nevent: ")
        for block in stripped.split("\n\n"):
            if block.startswith("event:"):
                json.loads(block.split("data: ", 1)[1])
        assert stripped.endswith("data: [DONE]\n\n")

    def test_stripping_twice_changes_nothing(self) -> None:
        once = strip_masks(fixture("clip1_hand_with_masks.sse"))
        assert strip_masks(once) == once

    def test_a_reply_without_masks_is_returned_unchanged(self) -> None:
        text = fixture("clip2_box_head.sse")
        assert strip_masks(text) == text

    def test_an_unreadable_reply_is_refused_not_guessed_at(self) -> None:
        with pytest.raises(SamStreamError):
            strip_masks("not a stream")


class TestRefusals:
    def test_errors_are_perception_errors(self) -> None:
        assert issubclass(SamStreamError, PerceptionError)

    def test_an_unknown_event_type_is_refused_by_name(self) -> None:
        body = sse(("response.created", {}), ("response.surprise", {}), completed(""))
        with pytest.raises(SamStreamError, match="response.surprise"):
            parse_sam_stream(body)

    def test_a_failure_event_is_refused(self) -> None:
        body = sse(("response.created", {}), ("response.failed", {"response": {"error": {}}}))
        with pytest.raises(SamStreamError, match="failed"):
            parse_sam_stream(body)

    def test_a_stream_cut_before_completion_is_refused(self) -> None:
        full = fixture("clip2_box_head.sse")
        cut = full[: full.index("event: response.completed")]
        with pytest.raises(SamStreamError, match="truncated|completed"):
            parse_sam_stream(cut)

    def test_a_stream_cut_in_the_middle_of_an_event_is_refused(self) -> None:
        full = fixture("clip2_box_head.sse")
        with pytest.raises(SamStreamError, match="truncated|completed|JSON"):
            parse_sam_stream(full[: len(full) // 2])

    def test_a_completed_event_that_did_not_complete_is_refused(self) -> None:
        with pytest.raises(SamStreamError, match="status"):
            parse_sam_stream(sse(("response.created", {}), completed("", status="incomplete")))

    def test_an_empty_body_is_refused(self) -> None:
        with pytest.raises(SamStreamError):
            parse_sam_stream("")

    def test_deltas_that_disagree_with_the_final_text_are_refused(self) -> None:
        text = f"<0f>0{BOX}\n"
        body = sse(
            ("response.created", {}),
            ("response.output_text.delta", {"delta": f"<1f>0{BOX}\n"}),
            ("response.output_text.done", {"text": text}),
            completed(text),
        )
        with pytest.raises(SamStreamError, match="match"):
            parse_sam_stream(body)

    @pytest.mark.parametrize(
        "text",
        [
            "hello\n",
            f"<0f>{BOX}\n",  # no object id
            f"<0f>0{BOX[:-4]}\n",  # box cut off
            f"0{BOX}\n",  # no frame prefix
            f"<0f>0{BOX}<|mask;x=0;y=0;c=0.5;data=1,1,abc\n",  # mask never closed
            f"<0f>0{BOX}junk\n",
            f"<0f>0{BOX},\n",  # separator with nothing after it
        ],
    )
    def test_a_garbled_fragment_names_its_line(self, text: str) -> None:
        with pytest.raises(SamStreamError, match="line 1"):
            parse_sam_stream(reply_with_text(text))

    def test_the_same_object_twice_on_a_frame_is_refused(self) -> None:
        with pytest.raises(SamStreamError, match="twice"):
            parse_sam_stream(reply_with_text(f"<0f>0{BOX},0{BOX}\n"))

    def test_the_same_object_on_two_lines_of_one_frame_is_refused(self) -> None:
        with pytest.raises(SamStreamError, match="twice"):
            parse_sam_stream(reply_with_text(f"<0f>0{BOX}\n<0f>0{BOX}\n"))

    def test_an_inverted_box_is_refused(self) -> None:
        bad = "<|box;x1=50;y1=20;x2=10;y2=220;w=200;h=400;c=0.5|>"
        with pytest.raises(SamStreamError, match="box"):
            parse_sam_stream(reply_with_text(f"<0f>0{bad}\n"))

    def test_frames_of_different_sizes_in_one_reply_are_refused(self) -> None:
        other = "<|box;x1=10;y1=20;x2=110;y2=220;w=640;h=360;c=0.5|>"
        with pytest.raises(SamStreamError, match="size"):
            parse_sam_stream(reply_with_text(f"<0f>0{BOX}\n<1f>0{other}\n"))

    def test_a_box_slightly_past_the_frame_is_clamped_in_the_normalised_box_only(self) -> None:
        edge = "<|box;x1=190;y1=390;x2=205;y2=401;w=200;h=400;c=0.5|>"
        (found,) = parse_sam_stream(reply_with_text(f"<0f>0{edge}\n"))
        assert found.box.x2 == 205
        assert found.norm_box.x2 == 1.0
        assert found.norm_box.y2 == 1.0

    def test_the_error_does_not_echo_long_text(self) -> None:
        text = "<0f>" + "A" * 5000 + "\n"
        with pytest.raises(SamStreamError) as caught:
            parse_sam_stream(reply_with_text(text))
        assert len(str(caught.value)) < 200
