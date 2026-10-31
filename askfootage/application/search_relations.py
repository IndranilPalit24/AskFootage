"""Answer a question from stored object tracks, with proof, instead of from stored clips.

The question is read into the closed schema (a parser if one is given, else the keyword
reader in askfootage.domain.vocabulary). For each ready recording that has stored tracks,
the tracks are stitched and the matching rule in askfootage.domain.relations runs:
carrying, region_entry (the "in_zone" relation) or dwell. Each interval found becomes a
Clip plus a ClipProof: the relation, the frames and seconds, the track ids and the measures
the rule recorded, and a few boxes to draw. Nothing is stored and nothing leaves the
server; this module imports the domain and the ports only.

Zones are saved as fractions of the frame, tracks are in pixels, so zone questions need the
frame size of each video (FrameSizeSource). Without it a recording cannot be judged for a
zone: the result is NotJudged with a note, and the caller falls back to the demo matcher for
that recording and shows the note.

A recording's tracks are stored under the recording's id: video_id_for() is the one place
that maps one to the other (video id == recording id).
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import time
from math import ceil, floor
from typing import Protocol

from askfootage.domain import relations
from askfootage.domain.intervals import Interval, RelationKind
from askfootage.domain.models import Point
from askfootage.domain.stitching import merge_intervals, stitch_tracks
from askfootage.domain.timebase import DEFAULT_ANALYSIS_FPS, Timebase
from askfootage.domain.tracks import Track
from askfootage.domain.vocabulary import (
    InvalidQuestionError,
    ObjectNoun,
    Question,
    interpret_text,
)
from askfootage.ports.language_model import QuestionNotUnderstoodError, QuestionParser
from askfootage.ports.library_store import Clip, Evidence, KeyFrame, Recording, Zone
from askfootage.ports.track_store import TrackDataError, TrackStore

logger = logging.getLogger("askfootage.search")

RELATION_CLIP_PREFIX = "rel-"
"""Ids of clips found from object tracks start with this."""
DEFAULT_DWELL_SECONDS = 5.0
"""How long a dwell must last when the question names no time."""

FrameSizeSource = Callable[[str], tuple[float, float] | None]
"""(width, height) in pixels of a recording's analysed video, or None when not known."""

_UNREADABLE_STORE = (TrackDataError, ValueError, KeyError, TypeError, OSError)
"""What a damaged or unreadable track store raises: the port's TrackDataError, plus a bad
video id or a disk error from a store that does not translate them."""
_MAX_ECHOED_ZONE = 60
_SECONDS = re.compile(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m)\b")


class FrameSizeProvider(Protocol):
    """A track store that also remembers each video's pixel size (JsonTrackStore does)."""

    def frame_size(self, video_id: str) -> tuple[float, float] | None:
        """(width, height) of the video's analysed frames, or None when not saved."""
        ...


def frame_size_source_of(store: object | None) -> FrameSizeSource | None:
    """The store's frame_size method when it has one, else None."""
    method = getattr(store, "frame_size", None)
    return method if callable(method) else None


def video_id_for(recording: Recording) -> str:
    """The id tracks are stored under: a recording's video id is the recording's own id."""
    return recording.id


@dataclass(frozen=True, slots=True)
class ProofBox:
    """One track's box on one frame, in pixels of the analysed video."""

    frame: int
    track_id: int
    label: str
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True, slots=True)
class ClipProof:
    """Why a clip matched: the rule, the interval and the numbers it measured.

    start_seconds and end_seconds are seconds from the start of the recording (end is the
    end of the last frame). track_ids and track_labels are the same length and order.
    """

    clip_id: str
    relation: RelationKind
    start_frame: int
    end_frame: int
    start_seconds: float
    end_seconds: float
    track_ids: tuple[int, ...]
    track_labels: tuple[str, ...]
    measures: tuple[tuple[str, float], ...]
    boxes: tuple[ProofBox, ...]


@dataclass(frozen=True, slots=True)
class RelationAnswer:
    """The clips and proofs found in one recording."""

    clips: list[Clip]
    proofs: list[ClipProof]
    note: str | None = None
    """What the answer left out or assumed, for the user; None when there is nothing to add."""


@dataclass(frozen=True, slots=True)
class NotJudged:
    """This path could not judge the recording; the caller uses the demo matcher for it."""

    note: str | None = None


# --- Reading the question ------------------------------------------------------------------------


def read_question(
    text: str, zone_names: Sequence[str], parser: QuestionParser | None = None
) -> Question | None:
    """The question in the closed schema, or None when it names no relation we can run.

    The parser comes first when given; if it does not understand, or fails for any reason,
    the keyword reader is used. Zone questions need a zone name found in the text.
    """
    if parser is not None:
        try:
            return parser.parse(text).question
        except QuestionNotUnderstoodError:
            pass
        except Exception as error:  # a model outage must not break search
            logger.warning(
                "Question parser failed (%s); using the keyword reader", type(error).__name__
            )
    reading = interpret_text(text)
    subject = reading.subject
    if reading.relation is None or subject is None:
        return None
    zone = _zone_in_text(text, zone_names)
    min_seconds = _minimum_seconds(text) if reading.relation == "dwell" else None
    try:
        return Question(reading.relation, subject, zone=zone, min_seconds=min_seconds)
    except InvalidQuestionError:
        return None


def _zone_in_text(text: str, zone_names: Sequence[str]) -> str | None:
    padded = f" {' '.join(re.findall(r'[^\W_]+', text.casefold()))} "
    found: list[tuple[int, str]] = []
    for name in zone_names:
        words = " ".join(re.findall(r"[^\W_]+", name.casefold()))
        position = padded.find(f" {words} ") if words else -1
        if position >= 0:
            found.append((position, name))
    return min(found)[1] if found else None


def _minimum_seconds(text: str) -> float | None:
    match = _SECONDS.search(text.casefold())
    if match is None:
        return None
    value = float(match.group(1)) * (60.0 if match.group(2).startswith("m") else 1.0)
    return value if 0 < value <= 3600 else None


# --- Running the rules -----------------------------------------------------------------------


def labels_needed(question: Question) -> tuple[str, ...]:
    """The track labels a question reads: the person and the object, or just the subject."""
    if question.relation == "carrying":
        return (ObjectNoun.PERSON.value, question.subject.value)
    return (question.subject.value,)


def answer_recording(
    recording: Recording,
    question: Question,
    zones: Sequence[Zone],
    tracks: TrackStore,
    frame_size: FrameSizeSource | None,
) -> RelationAnswer | NotJudged:
    """Clips and proofs for one recording, or NotJudged when this path cannot judge it.

    NotJudged (with a note, except for a recording that simply has no tracks) means: no
    tracks stored for it, a concept the question needs was never indexed for it, its store
    could not be read, or a zone question and no frame size. An empty RelationAnswer means
    the rules ran and found nothing; an unknown zone name is an empty answer with a note.
    """
    video_id = video_id_for(recording)
    labels = tuple(dict.fromkeys(labels_needed(question)))
    try:
        by_label = {label: stitch_tracks(tracks.tracks_for(video_id, label)) for label in labels}
    except _UNREADABLE_STORE as error:
        logger.warning("Stored tracks unreadable (%s); recording skipped", type(error).__name__)
        return NotJudged(
            f"The stored tracks of recording {recording.id} could not be read, "
            "so it was searched with the demo matcher."
        )
    missing = [label for label in labels if not by_label[label]]
    if len(missing) == len(labels):
        return NotJudged()
    if missing:
        return NotJudged(
            f"{', '.join(missing)} has not been indexed for recording {recording.id}, so it "
            "was searched with the demo matcher instead of its object tracks."
        )
    polygon: list[Point] | None = None
    zone_name: str | None = None
    if question.zone is not None:
        try:
            size = frame_size(video_id) if frame_size is not None else None
        except _UNREADABLE_STORE as error:
            logger.warning("Frame size unreadable (%s); using no size", type(error).__name__)
            size = None
        if size is None:
            return NotJudged(
                f"The frame size of recording {recording.id} is not recorded, so the "
                f"{_echo(question.zone)} zone could not be checked against its object tracks; "
                "the demo matcher was used."
            )
        zone = next((z for z in zones if z.name.casefold() == question.zone.casefold()), None)
        if zone is None:
            known = ", ".join(dict.fromkeys(z.name for z in zones)) or "none"
            return RelationAnswer(
                [],
                [],
                f"No zone named {_echo(question.zone)} on {recording.camera}; "
                f"known zones: {known}.",
            )
        zone_name = zone.name
        polygon = [(x * size[0], y * size[1]) for x, y in zone.points]

    timebase = Timebase(DEFAULT_ANALYSIS_FPS)
    subject = question.subject.value
    people = by_label.get(ObjectNoun.PERSON.value, [])
    objects = by_label.get(subject, [])
    if question.relation == "carrying":
        intervals = relations.carrying(people, objects)
        if polygon is not None:
            intervals = _inside_zone(intervals, people, polygon)
    elif question.relation == "in_zone":
        assert polygon is not None
        intervals = relations.region_entry(objects, polygon)
    else:
        assert polygon is not None
        seconds = question.min_seconds or DEFAULT_DWELL_SECONDS
        intervals = relations.dwell(objects, polygon, relations.min_frames_for(seconds, timebase))
    intervals = merge_intervals(intervals, relations.DEFAULT_THRESHOLDS.gap_tolerance_frames)

    lookup = {(t.label, t.track_id): t for group in by_label.values() for t in group}
    clips: list[Clip] = []
    proofs: list[ClipProof] = []
    for interval in intervals:
        clip, proof = _clip_and_proof(recording, question, interval, zone_name, lookup, timebase)
        clips.append(clip)
        proofs.append(proof)
    return RelationAnswer(clips, proofs)


def _echo(text: str) -> str:
    """User text quoted for a note, cut short."""
    return repr(text if len(text) <= _MAX_ECHOED_ZONE else text[:_MAX_ECHOED_ZONE] + "...")


def _inside_zone(
    intervals: list[Interval], people: Sequence[Track], polygon: Sequence[Point]
) -> list[Interval]:
    """Carry intervals that overlap a time the carrying person was inside the zone."""
    inside = relations.region_traversal(people, polygon)
    kept = []
    for interval in intervals:
        person_id = interval.evidence.track_ids[0]
        if any(
            visit.evidence.track_ids == (person_id,)
            and visit.start_frame <= interval.end_frame
            and interval.start_frame <= visit.end_frame
            for visit in inside
        ):
            kept.append(interval)
    return kept


def _track_labels(question: Question, interval: Interval) -> tuple[str, ...]:
    if interval.evidence.kind == "carrying":
        return (ObjectNoun.PERSON.value, question.subject.value)
    return (question.subject.value,)


def _clip_and_proof(
    recording: Recording,
    question: Question,
    interval: Interval,
    zone_name: str | None,
    lookup: dict[tuple[str, int], Track],
    timebase: Timebase,
) -> tuple[Clip, ClipProof]:
    kind = interval.evidence.kind
    labels = _track_labels(question, interval)
    start_s, end_s = interval.seconds(timebase)
    start = floor(start_s)
    end = max(start + 1, ceil(end_s))
    if recording.length_seconds > 0:
        start = min(start, recording.length_seconds - 1)
        end = min(max(end, start + 1), recording.length_seconds)
    duration = max(1, round(end_s - start_s))
    clip_id = _clip_id(recording.id, interval, zone_name)
    clip_time = _clock_time(recording.start_time, start)
    clip = Clip(
        id=clip_id,
        recording_id=recording.id,
        day=recording.day,
        start_time=clip_time,
        start_seconds=start,
        end_seconds=end,
        label=_label(question, zone_name),
        evidence=(Evidence(kind, _evidence_text(kind, duration, zone_name)),),
        zone=zone_name,
        why_matched=_why(question, interval, duration, zone_name),
        key_frames=tuple(KeyFrame(s) for s in dict.fromkeys((start, (start + end) // 2, end))),
        thumbnail_url=None,
    )
    boxes = tuple(
        box
        for track_id, label in zip(interval.evidence.track_ids, labels, strict=True)
        for box in _boxes(lookup[(label, track_id)], interval)
    )
    proof = ClipProof(
        clip_id=clip_id,
        relation=kind,
        start_frame=interval.start_frame,
        end_frame=interval.end_frame,
        start_seconds=start_s,
        end_seconds=end_s,
        track_ids=interval.evidence.track_ids,
        track_labels=labels,
        measures=interval.evidence.measures,
        boxes=boxes,
    )
    return clip, proof


def _clock_time(start_time: time, offset_seconds: int) -> time:
    """Recording start plus an offset as a time of day, held at 23:59:59 rather than wrapped.

    A clip belongs to its recording's day, so one starting after midnight stays on that
    day at its last second instead of reading as the early hours of the same day.
    """
    seconds = start_time.hour * 3600 + start_time.minute * 60 + start_time.second + offset_seconds
    seconds = min(max(seconds, 0), 24 * 3600 - 1)
    return time(seconds // 3600, seconds % 3600 // 60, seconds % 60)


def _clip_id(recording_id: str, interval: Interval, zone_name: str | None) -> str:
    ids = "-".join(map(str, interval.evidence.track_ids))
    span = f"{interval.start_frame}|{interval.end_frame}"
    seed = f"{recording_id}|{interval.evidence.kind}|{ids}|{span}|{zone_name}"
    return RELATION_CLIP_PREFIX + hashlib.blake2s(seed.encode(), digest_size=8).hexdigest()


def _boxes(track: Track, interval: Interval) -> list[ProofBox]:
    inside = [p for p in track.points if interval.start_frame <= p.frame <= interval.end_frame]
    if not inside:
        return []
    # The first, middle and last frame the track was seen in the interval.
    picks = {p.frame: p for p in (inside[0], inside[len(inside) // 2], inside[-1])}
    return [
        ProofBox(p.frame, track.track_id, track.label, p.box.x1, p.box.y1, p.box.x2, p.box.y2)
        for _, p in sorted(picks.items())
    ]


def _label(question: Question, zone_name: str | None) -> str:
    subject = question.subject.value
    if question.relation == "carrying":
        tail = f" through the {zone_name}" if zone_name else ""
        return f"Person carrying a {subject}{tail}"
    if question.relation == "in_zone":
        return f"{subject.capitalize()} entering the {zone_name}"
    return f"{subject.capitalize()} staying in the {zone_name}"


def _evidence_text(kind: RelationKind, seconds: int, zone_name: str | None) -> str:
    if kind == "carrying":
        return f"Carrying · {seconds} s"
    if kind == "in_zone":
        return f"Entered {zone_name}"
    return f"In {zone_name} · {seconds} s"


def _why(question: Question, interval: Interval, seconds: int, zone_name: str | None) -> str:
    measures = dict(interval.evidence.measures)
    subject = question.subject.value
    if interval.evidence.kind == "carrying":
        agreement = round(100 * measures.get("motion_agreement", 0.0))
        return (
            f"A person was tracked moving together with a {subject} for {seconds} seconds. "
            f"The {subject} stayed within reach of the person and moved with them on "
            f"{agreement}% of the steps."
        )
    if interval.evidence.kind == "in_zone":
        return (
            f"A {subject} was first seen outside the {zone_name} zone and then crossed into "
            f"it, staying inside for {seconds} seconds."
        )
    coverage = round(100 * measures.get("coverage", 1.0))
    return (
        f"A {subject} stayed inside the {zone_name} zone for {seconds} seconds, "
        f"seen there on {coverage}% of the frames."
    )
