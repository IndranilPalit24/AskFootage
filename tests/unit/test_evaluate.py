"""Scoring predicted relation intervals against hand-made labels."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app_fakes import MemoryTracks, track

from askfootage.application.errors import InvalidInputError, NotFoundError
from askfootage.application.evaluate import (
    LabeledSpan,
    LabelSet,
    evaluate,
    load_labels,
    predict_relations,
    score_spans,
)
from askfootage.domain.intervals import Interval, IntervalEvidence


def _interval(start: int, end: int, kind: str = "carrying") -> Interval:
    return Interval(start, end, IntervalEvidence(kind, (1,)))  # type: ignore[arg-type]


def test_perfect_match() -> None:
    score = score_spans([(10, 19)], [(10, 19)])
    assert (score.precision, score.recall, score.f1, score.frame_iou) == (1.0, 1.0, 1.0, 1.0)
    assert score.matched == 1 and score.mean_matched_iou == 1.0


def test_partial_overlap_frames_and_intervals() -> None:
    score = score_spans([(0, 9)], [(5, 14)])
    assert score.precision == 0.5 and score.recall == 0.5
    assert score.frame_iou == pytest.approx(5 / 15)
    assert score.matched == 0  # IoU 1/3 is under the 0.5 threshold
    assert score_spans([(0, 9)], [(5, 14)], iou_threshold=0.3).matched == 1


def test_empty_cases() -> None:
    both = score_spans([], [])
    assert (both.precision, both.recall, both.frame_iou) == (1.0, 1.0, 1.0)
    miss = score_spans([], [(0, 5)])
    assert (miss.precision, miss.recall, miss.f1) == (0.0, 0.0, 0.0)
    extra = score_spans([(0, 5)], [])
    assert (extra.precision, extra.recall) == (0.0, 0.0)


def test_overlapping_predictions_do_not_double_count() -> None:
    score = score_spans([(0, 9), (5, 14)], [(0, 14)])
    assert score.precision == 1.0 and score.recall == 1.0


def test_one_truth_matches_one_prediction_only() -> None:
    score = score_spans([(0, 9), (20, 29)], [(0, 9)])
    assert score.matched == 1 and score.predicted == 2 and score.truth == 1


def test_evaluate_per_relation() -> None:
    labels = LabelSet(
        video_id="v",
        spans=(LabeledSpan("carrying", 0, 9), LabeledSpan("dwell", 0, 4, "dock")),
    )
    report = evaluate({"carrying": [_interval(0, 9)]}, labels)
    assert report["carrying"].f1 == 1.0
    assert report["dwell:dock"].recall == 0.0  # no prediction for it
    assert set(report) == {"carrying", "dwell:dock"}


def _write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "l.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_labels(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "video_id": "v1",
            "zones": {"dock": [[0, 0], [10, 0], [10, 10], [0, 10]]},
            "dwell_min_frames": 3,
            "relations": [
                {"kind": "carrying", "start_frame": 1, "end_frame": 5},
                {"kind": "in_zone", "zone": "dock", "start_frame": 2, "end_frame": 8},
            ],
        },
    )
    labels = load_labels(path)
    assert labels.video_id == "v1" and labels.dwell_min_frames == 3
    assert labels.spans[1] == LabeledSpan("in_zone", 2, 8, "dock")
    assert labels.zones["dock"][0] == (0.0, 0.0)


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"relations": []},
        {"video_id": "v", "relations": [{"kind": "flying", "start_frame": 0, "end_frame": 1}]},
        {"video_id": "v", "relations": [{"kind": "carrying", "start_frame": 5, "end_frame": 1}]},
        {"video_id": "v", "relations": [{"kind": "dwell", "start_frame": 0, "end_frame": 1}]},
        {
            "video_id": "v",
            "relations": [{"kind": "dwell", "zone": "nope", "start_frame": 0, "end_frame": 1}],
        },
    ],
)
def test_load_labels_rejects_bad_files(tmp_path: Path, data: object) -> None:
    with pytest.raises(InvalidInputError):
        load_labels(_write(tmp_path, data))


def test_load_labels_missing_file(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        load_labels(tmp_path / "nope.json")


def test_load_labels_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(InvalidInputError):
        load_labels(path)


def test_predict_relations_from_stored_tracks() -> None:
    store = MemoryTracks()
    person = track(1, "person", range(0, 30))
    box = track(1, "cardboard box", range(0, 30), x0=10)
    store.save_tracks("v", "person", [person])
    store.save_tracks("v", "cardboard box", [box])
    labels = LabelSet(
        video_id="v",
        spans=(LabeledSpan("carrying", 0, 29), LabeledSpan("in_zone", 0, 29, "everywhere")),
        zones={"everywhere": ((60.0, -100.0), (500.0, -100.0), (500.0, 500.0), (60.0, 500.0))},
    )
    predicted = predict_relations(store, labels)
    assert set(predicted) == {"carrying", "in_zone:everywhere"}
    # the same rule as search: region_entry, so the interval starts at the entry frame
    assert predicted["in_zone:everywhere"][0].start_frame == 20
    labels = LabelSet("v", (LabeledSpan("in_zone", 20, 29, "everywhere"),), labels.zones)
    assert evaluate(predicted, labels)["in_zone:everywhere"].f1 == 1.0


# --- aligned with search -------------------------------------------------------------------

_BIG_ZONE = ((-100.0, -100.0), (500.0, -100.0), (500.0, 500.0), (-100.0, 500.0))


def test_a_track_first_seen_inside_is_not_an_entry() -> None:
    store = MemoryTracks()
    store.save_tracks("v", "person", [track(1, "person", range(0, 30))])
    labels = LabelSet("v", (LabeledSpan("in_zone", 0, 29, "all"),), {"all": _BIG_ZONE})
    assert predict_relations(store, labels)["in_zone:all"] == []


def test_fragments_are_stitched_and_neighbouring_intervals_merged() -> None:
    store = MemoryTracks()
    store.save_tracks(
        "v", "person", [track(1, "person", range(0, 20)), track(2, "person", range(22, 40), 44)]
    )
    zone = ((60.0, -100.0), (900.0, -100.0), (900.0, 500.0), (60.0, 500.0))
    labels = LabelSet("v", (LabeledSpan("in_zone", 0, 39, "z"),), {"z": zone})
    (interval,) = predict_relations(store, labels)["in_zone:z"]
    assert interval.end_frame == 39


def test_fractional_zones_are_scaled_by_the_stored_frame_size() -> None:
    class Sized(MemoryTracks):
        def frame_size(self, video_id: str):
            return (200, 200)

    store = Sized()
    store.save_tracks("v", "person", [track(1, "person", range(0, 30))])
    half = ((0.3, 0.0), (1.0, 0.0), (1.0, 1.0), (0.3, 1.0))  # x >= 60 px of 200
    spans = (LabeledSpan("in_zone", 20, 29, "z"),)
    labels = LabelSet("v", spans, {"z": half}, zone_units="fraction")
    assert predict_relations(store, labels)["in_zone:z"][0].start_frame == 20
    with pytest.raises(NotFoundError):
        predict_relations(MemoryTracks(), labels)


def test_unknown_video_is_an_error_not_zeros() -> None:
    labels = LabelSet("ghost", (LabeledSpan("carrying", 0, 5),))
    with pytest.raises(NotFoundError):
        predict_relations(MemoryTracks(), labels)


def test_a_searched_but_empty_video_is_scored_not_an_error() -> None:
    class Marked(MemoryTracks):
        def concept_done(self, video_id: str, concept: str) -> bool:
            return True

    labels = LabelSet("v", (LabeledSpan("carrying", 0, 5),))
    assert predict_relations(Marked(), labels) == {"carrying": []}


def test_frame_numbers_have_an_upper_bound(tmp_path: Path) -> None:
    for bad in (10**9, 2_000_000):
        entry = {"kind": "carrying", "start_frame": 0, "end_frame": bad}
        data = {"video_id": "v", "relations": [entry]}
        with pytest.raises(InvalidInputError):
            load_labels(_write(tmp_path, data))
    data = {"video_id": "v", "dwell_min_frames": 10**9, "relations": []}
    with pytest.raises(InvalidInputError):
        load_labels(_write(tmp_path, data))


def test_zone_units_are_validated_and_default_to_pixels(tmp_path: Path) -> None:
    ok = {"video_id": "v", "relations": []}
    assert load_labels(_write(tmp_path, ok)).zone_units == "pixels"
    assert load_labels(_write(tmp_path, {**ok, "zone_units": "fraction"})).zone_units == "fraction"
    with pytest.raises(InvalidInputError):
        load_labels(_write(tmp_path, {**ok, "zone_units": "inches"}))
