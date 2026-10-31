"""Scoring: how well predicted relation intervals match hand-made ground-truth labels.

Labels live as one JSON file per video in labels/ (format in labels/README.md). The
predicted intervals come from the stored tracks through the domain rules
(domain/relations.py). Each relation is scored on its own, with these measures:

- precision / recall / f1 / frame_iou: counted per frame, so an interval that is too long,
  too short or late is penalised by exactly how far it is off;
- matched, interval_precision, interval_recall, mean_matched_iou: counted per interval,
  where a predicted and a labelled interval match when their IoU reaches iou_threshold
  (0.5 by default), each used at most once, best overlaps first.

With nothing predicted and nothing labelled every measure is 1.0. With one side empty and
the other not, precision, recall, f1 and IoU are 0.0. Overlapping or touching spans are
merged before scoring, whichever tracks they came from.

Predictions use the same rules and steps as search (application/search_relations.py):
fragments are stitched, "in_zone" is region_entry (a track first seen inside the zone is
not an entry), "dwell" is dwell, and neighbouring intervals are merged across the standard
gap tolerance. An evaluation of a video with no stored tracks for the labels' concepts is an
error (NotFoundError), never a table of zeros.

Zones in a labels file are polygons in PIXELS of the prepared video by default; with
"zone_units": "fraction" they are fractions (0 to 1) of the frame, as saved zones are in the
app, and are scaled by the video's recorded frame size.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from askfootage.application.errors import InvalidInputError, NotFoundError
from askfootage.domain.intervals import RELATION_KINDS, Interval
from askfootage.domain.models import Point
from askfootage.domain.relations import (
    DEFAULT_THRESHOLDS,
    carrying,
    dwell,
    region_entry,
)
from askfootage.domain.stitching import merge_intervals, stitch_tracks
from askfootage.domain.tracks import Track
from askfootage.ports.track_store import TrackStore

DEFAULT_IOU_THRESHOLD = 0.5
DEFAULT_PERSON = "person"
DEFAULT_OBJECT = "cardboard box"
DEFAULT_DWELL_MIN_FRAMES = 10
_ZONE_KINDS = ("in_zone", "dwell")
ZONE_UNITS = ("pixels", "fraction")
MAX_FRAME = 1_000_000
"""Largest frame number a labels file may name (55 hours at 5 fps). Scoring keeps a set of
every labelled frame, so an unbounded number would exhaust memory."""

Span = tuple[int, int]
"""Start and end frame, both inclusive."""


@dataclass(frozen=True, slots=True)
class LabeledSpan:
    """One labelled interval. `zone` names the zone for in_zone and dwell, else None."""

    kind: str
    start_frame: int
    end_frame: int
    zone: str | None = None

    @property
    def key(self) -> str:
        """The name the relation is scored under: "carrying" or "in_zone:dock"."""
        return relation_key(self.kind, self.zone)


@dataclass(frozen=True, slots=True)
class LabelSet:
    """Everything a labels file says about one video."""

    video_id: str
    spans: tuple[LabeledSpan, ...]
    zones: Mapping[str, tuple[Point, ...]] = field(default_factory=dict)
    person: str = DEFAULT_PERSON
    obj: str = DEFAULT_OBJECT
    dwell_min_frames: int = DEFAULT_DWELL_MIN_FRAMES
    zone_units: str = "pixels"


@dataclass(frozen=True, slots=True)
class RelationScore:
    """The measures for one relation (see the module docstring)."""

    predicted: int
    truth: int
    precision: float
    recall: float
    f1: float
    frame_iou: float
    matched: int
    interval_precision: float
    interval_recall: float
    mean_matched_iou: float

    def as_dict(self) -> dict[str, float | int]:
        """All measures by name, for JSON output."""
        return {name: getattr(self, name) for name in self.__slots__}


def relation_key(kind: str, zone: str | None) -> str:
    """"carrying", or "in_zone:dock" for a zone relation."""
    return kind if zone is None else f"{kind}:{zone}"


# --- scoring -------------------------------------------------------------------------------


def _merge(spans: Iterable[Span]) -> list[Span]:
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _frames(spans: Iterable[Span]) -> set[int]:
    return {frame for start, end in spans for frame in range(start, end + 1)}


def _ratio(numerator: float, denominator: float, empty: float = 0.0) -> float:
    return numerator / denominator if denominator else empty


def _span_iou(a: Span, b: Span) -> float:
    overlap = min(a[1], b[1]) - max(a[0], b[0]) + 1
    if overlap <= 0:
        return 0.0
    return overlap / ((a[1] - a[0] + 1) + (b[1] - b[0] + 1) - overlap)


def _match(
    predicted: Sequence[Span], truth: Sequence[Span], threshold: float
) -> list[float]:
    """IoUs of the one-to-one matches, taking the best overlaps first."""
    pairs = sorted(
        (
            (_span_iou(p, t), i, j)
            for i, p in enumerate(predicted)
            for j, t in enumerate(truth)
        ),
        reverse=True,
    )
    used_p: set[int] = set()
    used_t: set[int] = set()
    ious: list[float] = []
    for iou, i, j in pairs:
        if iou < threshold or iou == 0.0:
            break
        if i in used_p or j in used_t:
            continue
        used_p.add(i)
        used_t.add(j)
        ious.append(iou)
    return ious


def score_spans(
    predicted: Iterable[Span],
    truth: Iterable[Span],
    iou_threshold: float = DEFAULT_IOU_THRESHOLD,
) -> RelationScore:
    """Score predicted frame spans against labelled ones (inclusive frame ranges)."""
    if not 0.0 < iou_threshold <= 1.0:
        raise ValueError("iou_threshold must be above 0 and at most 1")
    pred = _merge(predicted)
    true = _merge(truth)
    if not pred and not true:
        return RelationScore(0, 0, 1.0, 1.0, 1.0, 1.0, 0, 1.0, 1.0, 1.0)
    pred_frames = _frames(pred)
    true_frames = _frames(true)
    both = len(pred_frames & true_frames)
    precision = _ratio(both, len(pred_frames))
    recall = _ratio(both, len(true_frames))
    ious = _match(pred, true, iou_threshold)
    return RelationScore(
        predicted=len(pred),
        truth=len(true),
        precision=precision,
        recall=recall,
        f1=_ratio(2 * precision * recall, precision + recall),
        frame_iou=_ratio(both, len(pred_frames | true_frames)),
        matched=len(ious),
        interval_precision=_ratio(len(ious), len(pred)),
        interval_recall=_ratio(len(ious), len(true)),
        mean_matched_iou=_ratio(sum(ious), len(ious)),
    )


def evaluate(
    predicted: Mapping[str, Sequence[Interval]],
    labels: LabelSet,
    iou_threshold: float = DEFAULT_IOU_THRESHOLD,
) -> dict[str, RelationScore]:
    """Score every relation named in the labels or the predictions, by relation key."""
    truth: dict[str, list[Span]] = {}
    for span in labels.spans:
        truth.setdefault(span.key, []).append((span.start_frame, span.end_frame))
    keys = sorted(set(truth) | set(predicted))
    return {
        key: score_spans(
            [(i.start_frame, i.end_frame) for i in predicted.get(key, ())],
            truth.get(key, ()),
            iou_threshold,
        )
        for key in keys
    }


# --- predictions from stored tracks -------------------------------------------------------


def _stitched(tracks: TrackStore, video_id: str, label: str) -> list[Track]:
    return stitch_tracks(tracks.tracks_for(video_id, label))


def _was_searched(tracks: TrackStore, video_id: str, label: str) -> bool:
    marker = getattr(tracks, "concept_done", None)
    return bool(marker(video_id, label)) if marker is not None else False


def _zone_polygon(
    tracks: TrackStore, labels: LabelSet, name: str
) -> tuple[Point, ...]:
    polygon = labels.zones[name]
    if labels.zone_units == "pixels":
        return polygon
    size_of = getattr(tracks, "frame_size", None)
    size = size_of(labels.video_id) if size_of is not None else None
    if size is None:
        raise NotFoundError("The video's frame size is unknown; fractional zones cannot be used.")
    return tuple((x * size[0], y * size[1]) for x, y in polygon)


def predict_relations(tracks: TrackStore, labels: LabelSet) -> dict[str, list[Interval]]:
    """Run the relation rules on the stored tracks, for each relation the labels name.

    Same steps as search: stitch, carrying / region_entry / dwell, then merge_intervals
    across the standard gap tolerance. carrying uses the labels' person and object
    concepts; in_zone and dwell use each named zone's polygon and the person's tracks.
    Raises NotFoundError when the video has no tracks (and no "searched, found nothing"
    record) for a concept the labels need.
    """
    wanted = {span.key: span for span in labels.spans}
    needs_object = any(span.kind == "carrying" for span in wanted.values())
    people = _stitched(tracks, labels.video_id, labels.person)
    objects = _stitched(tracks, labels.video_id, labels.obj) if needs_object else []
    for label, found in ((labels.person, people), (labels.obj, objects)):
        needed = label == labels.person or needs_object
        if needed and not found and not _was_searched(tracks, labels.video_id, label):
            raise NotFoundError("No stored tracks for that video and concept; ingest it first.")
    gap = DEFAULT_THRESHOLDS.gap_tolerance_frames
    predicted: dict[str, list[Interval]] = {}
    for key, span in wanted.items():
        if span.kind == "carrying":
            found_intervals = carrying(people, objects)
        elif span.zone is None:
            continue
        elif span.kind == "in_zone":
            found_intervals = region_entry(people, _zone_polygon(tracks, labels, span.zone))
        else:
            found_intervals = dwell(
                people, _zone_polygon(tracks, labels, span.zone), labels.dwell_min_frames
            )
        predicted[key] = merge_intervals(found_intervals, gap)
    return predicted


# --- the labels file ----------------------------------------------------------------------


def _bad(field_name: str, problem: str) -> InvalidInputError:
    return InvalidInputError(field_name, problem)


def _int_field(entry: Mapping[str, object], name: str) -> int:
    value = entry.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_FRAME:
        raise _bad(name, f"must be a whole number of frames, 0 to {MAX_FRAME}")
    return value


def _polygon(name: str, raw: object) -> tuple[Point, ...]:
    if not isinstance(raw, list) or len(raw) < 3:
        raise _bad("zones", f"zone {name!r} needs a list of at least 3 [x, y] points")
    points: list[Point] = []
    for item in raw:
        ok = (
            isinstance(item, list)
            and len(item) == 2
            and all(isinstance(v, int | float) and not isinstance(v, bool) for v in item)
        )
        if not ok:
            raise _bad("zones", f"zone {name!r} has a point that is not [x, y]")
        points.append((float(item[0]), float(item[1])))
    return tuple(points)


def load_labels(path: Path) -> LabelSet:
    """Read and check one labels file.

    Raises NotFoundError when the file is missing and InvalidInputError (naming the field,
    never echoing file text) when it is not valid JSON or breaks the format.
    """
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise NotFoundError("The labels file was not found.") from None
    except OSError:
        raise _bad("labels", "the file could not be read") from None
    try:
        data = json.loads(text)
    except ValueError:
        raise _bad("labels", "the file is not valid JSON") from None
    if not isinstance(data, dict):
        raise _bad("labels", "the file must hold a JSON object")
    video_id = data.get("video_id")
    if not isinstance(video_id, str) or not video_id.strip():
        raise _bad("video_id", "must be a non-empty string")
    raw_zones = data.get("zones", {})
    if not isinstance(raw_zones, dict):
        raise _bad("zones", "must be an object of zone name to points")
    zones = {name: _polygon(name, raw) for name, raw in raw_zones.items()}
    person = data.get("person", DEFAULT_PERSON)
    obj = data.get("object", DEFAULT_OBJECT)
    if not isinstance(person, str) or not isinstance(obj, str):
        raise _bad("person", "person and object must be strings")
    min_frames = data.get("dwell_min_frames", DEFAULT_DWELL_MIN_FRAMES)
    if (
        isinstance(min_frames, bool)
        or not isinstance(min_frames, int)
        or not 1 <= min_frames <= MAX_FRAME
    ):
        raise _bad("dwell_min_frames", f"must be a whole number, 1 to {MAX_FRAME}")
    zone_units = data.get("zone_units", "pixels")
    if zone_units not in ZONE_UNITS:
        raise _bad("zone_units", f"must be one of {', '.join(ZONE_UNITS)}")
    entries = data.get("relations")
    if not isinstance(entries, list):
        raise _bad("relations", "must be a list")
    spans: list[LabeledSpan] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise _bad("relations", "each entry must be an object")
        kind = entry.get("kind")
        if kind not in RELATION_KINDS:
            raise _bad("kind", f"must be one of {', '.join(RELATION_KINDS)}")
        start = _int_field(entry, "start_frame")
        end = _int_field(entry, "end_frame")
        if end < start:
            raise _bad("end_frame", "must not be before start_frame")
        zone: str | None = None
        if kind in _ZONE_KINDS:
            zone = entry.get("zone")
            if not isinstance(zone, str) or zone not in zones:
                raise _bad("zone", "must name a zone listed in zones")
        spans.append(LabeledSpan(kind, start, end, zone))
    return LabelSet(video_id.strip(), tuple(spans), zones, person, obj, min_frames, zone_units)
