"""Answer a plain-English question about one day of footage, from one camera or all of them.

The question is turned into a SearchPlan by an interpreter, and the plan is checked
against the clips already found in that day's ready recordings. v1 uses
QuestionInterpreter, a deliberately simple keyword match. A model-backed interpreter can
replace it later: anything with the same interpret() method plugs into search_day(), and
the HTTP API does not change.

When a track store is given, search_day first tries the relation layer
(askfootage/application/search_relations.py): the question is read into the closed schema
and run over each ready recording's stored tracks, giving clips with proof. The keyword
matcher stays as the fallback for a recording with no stored tracks (or no frame size for a
zone question) and for a question that names no relation. When the relation path could not
judge a recording for a reason the user should know (a concept never indexed, no frame size,
an unreadable track file) or found an unknown zone name, the note says so.

Each clip found from tracks is written to the clip store (its id is derived from the
recording, the relation, the tracks and the interval, so the same finding always has the same
id). That is what lets GET /clips/{id} and saving work for it. Such clips (ids starting
"rel-") are never matched by the keyword search, which only sees demo clips.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from askfootage.application.clips import ClipWithCamera
from askfootage.application.errors import InvalidInputError
from askfootage.application.library import Library, require_camera_filter
from askfootage.application.search_relations import (
    RELATION_CLIP_PREFIX,
    ClipProof,
    FrameSizeSource,
    NotJudged,
    answer_recording,
    read_question,
)
from askfootage.application.snapshots import SnapshotStore
from askfootage.ports.language_model import QuestionParser
from askfootage.ports.library_store import Clip, DuplicateError, EvidenceKind, MissingReferenceError
from askfootage.ports.track_store import TrackStore

logger = logging.getLogger("askfootage.search")

MAX_QUESTION_LENGTH = 300
"""Longest question accepted, in characters, before trimming."""

NO_FOOTAGE_NOTE = "There is no footage from this camera on this day."
NO_FOOTAGE_ANY_CAMERA_NOTE = "There is no footage from any camera on this day."

_CARRYING_WORDS = frozenset(
    {
        "carry",
        "carries",
        "carrying",
        "carried",
        "box",
        "boxes",
        "package",
        "packages",
        "parcel",
        "parcels",
    }
)
_DWELL_WORDS = frozenset(
    {
        "wait",
        "waits",
        "waiting",
        "waited",
        "stay",
        "stays",
        "staying",
        "stayed",
        "stand",
        "stands",
        "standing",
        "stood",
        "linger",
        "lingers",
        "lingering",
        "lingered",
        "loiter",
        "loiters",
        "loitering",
        "loitered",
        "dwell",
        "dwells",
        "dwelling",
        "dwelled",
        "dwelt",
    }
)
# Words that ask about people in general and add no condition of their own.
_GENERIC_WORDS = frozenset(
    {"person", "persons", "people", "someone", "somebody", "anyone", "anybody"}
)
_WORD = re.compile(r"[^\W_]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


@dataclass(frozen=True, slots=True)
class SearchPlan:
    """What a question asks for, as conditions a clip must all meet.

    evidence_kinds: every kind listed must be among the clip's evidence.
    zone_names: every zone listed must be the clip's zone (compared ignoring case).
    understood: False when nothing in the question was recognised; then nothing matches.
    A plan that is understood but has no conditions matches every clip.
    """

    evidence_kinds: frozenset[EvidenceKind] = frozenset()
    zone_names: frozenset[str] = frozenset()
    understood: bool = True

    def matches(self, clip: Clip) -> bool:
        """Whether the clip meets every condition of the plan."""
        if not self.understood:
            return False
        kinds = {evidence.kind for evidence in clip.evidence}
        if not self.evidence_kinds <= kinds:
            return False
        clip_zone = clip.zone.casefold() if clip.zone is not None else None
        return all(zone.casefold() == clip_zone for zone in self.zone_names)


class Interpreter(Protocol):
    """Turns a question into a SearchPlan; QuestionInterpreter is v1's implementation."""

    def interpret(self, question: str, zone_names: Sequence[str]) -> SearchPlan:
        """The plan for `question`, given the names of the searched cameras' zones."""
        ...


class QuestionInterpreter:
    """A deliberately simple keyword interpreter for the demo.

    - carry, box, package or parcel (and their forms): clips with carrying evidence.
    - wait, stay, stand, linger, loiter or dwell (and their forms): clips with dwell evidence.
    - a zone name of a searched camera, such as "loading door": clips in that zone.
    - several of these: a clip must meet all of them.
    - only general words such as person, someone, anyone or people: every clip.
    - nothing recognised: no clips (search_day then explains what it understands).

    It never looks at who a person is: there is no identity in the data to look at.
    """

    def interpret(self, question: str, zone_names: Sequence[str]) -> SearchPlan:
        """The plan for `question`, given the names of the searched cameras' zones."""
        words = _words(question)
        word_set = set(words)
        kinds: set[EvidenceKind] = set()
        if word_set & _CARRYING_WORDS:
            kinds.add("carrying")
        if word_set & _DWELL_WORDS:
            kinds.add("dwell")
        padded_question = f" {' '.join(words)} "
        zones = {
            name
            for name in zone_names
            if _words(name) and f" {' '.join(_words(name))} " in padded_question
        }
        understood = bool(kinds or zones or word_set & _GENERIC_WORDS)
        return SearchPlan(
            evidence_kinds=frozenset(kinds), zone_names=frozenset(zones), understood=understood
        )


@dataclass(frozen=True, slots=True)
class SearchResult:
    """The answer to a question: matching clips earliest first, and a note or None."""

    question: str
    day: date
    clips: list[ClipWithCamera]
    note: str | None
    proofs: tuple[ClipProof, ...] = ()
    """Proof for the clips found from stored tracks; demo-matched clips have none."""


def check_question(question: str) -> str:
    """The question trimmed; raises InvalidInputError if it is too long or blank."""
    if len(question) > MAX_QUESTION_LENGTH:
        raise InvalidInputError("question", f"must be at most {MAX_QUESTION_LENGTH} characters")
    trimmed = question.strip()
    if not trimmed:
        raise InvalidInputError("question", "must not be blank")
    return trimmed


def search_day(
    library: Library,
    interpreter: Interpreter,
    question: str,
    day: date,
    camera_id: str | None = None,
    *,
    tracks: TrackStore | None = None,
    parser: QuestionParser | None = None,
    frame_size: FrameSizeSource | None = None,
    snapshots: SnapshotStore | None = None,
) -> SearchResult:
    """Answer a question about one day of footage, from one camera or (None) every camera.

    Only ready recordings are searched. With `tracks`, a question that names a relation is
    run over each recording's stored tracks and the clips come with proofs; a recording
    with no stored tracks, and any question without a relation, use the keyword
    `interpreter` over the stored clips instead. `parser` (optional) reads the question
    before the keyword reader does. The note says what the answer left out: recordings of
    the searched cameras still being indexed, a day without footage, or a question not
    understood. Each clip comes with its recording's camera, taken from the day's
    recordings. Raises InvalidInputError for a bad question and NotFoundError for an
    unknown camera.
    """
    question = check_question(question)
    require_camera_filter(library, camera_id)
    recordings = library.recordings.list_recordings(camera_id, day)
    if not recordings:
        note = NO_FOOTAGE_NOTE if camera_id is not None else NO_FOOTAGE_ANY_CAMERA_NOTE
        return SearchResult(question=question, day=day, clips=[], note=note)

    camera_of = {recording.id: recording.camera for recording in recordings}
    ready = [recording for recording in recordings if recording.status == "ready"]
    ready_ids = {recording.id for recording in ready}
    zone_names = _zone_names(library, camera_id)

    found: list[ClipWithCamera] = []
    proofs: dict[str, ClipProof] = {}
    demo_ids = set(ready_ids)
    relation_used = False  # True once any recording was answered from its tracks
    relation_notes: list[str] = []
    if tracks is not None:
        asked = read_question(question, zone_names, parser)
        if asked is not None:
            for recording in ready:
                zones = library.zones.list_zones(recording.camera)
                answer = answer_recording(recording, asked, zones, tracks, frame_size)
                if isinstance(answer, NotJudged):
                    if answer.note and answer.note not in relation_notes:
                        relation_notes.append(answer.note)
                    continue
                relation_used = True
                demo_ids.discard(recording.id)
                if answer.note and answer.note not in relation_notes:
                    relation_notes.append(answer.note)
                _remember_clips(library, answer.clips)
                found.extend(ClipWithCamera(clip, recording.camera) for clip in answer.clips)
                proofs.update((proof.clip_id, proof) for proof in answer.proofs)

    plan = interpreter.interpret(question, zone_names)
    found.extend(
        ClipWithCamera(clip=clip, camera=camera_of[clip.recording_id])
        for clip in library.clips.list_clips(camera_id, day)
        if clip.recording_id in demo_ids
        and not clip.id.startswith(RELATION_CLIP_PREFIX)
        and plan.matches(clip)
    )
    clips = sorted(found, key=lambda item: (item.clip.start_time, item.clip.id))
    if snapshots is not None:
        _make_snapshots(snapshots, clips, proofs)

    notes: list[str] = list(relation_notes)
    if not plan.understood and not relation_used:
        notes.append(_not_understood_note(zone_names))
    not_ready = len(recordings) - len(ready_ids)
    if not_ready:
        notes.append(_not_ready_note(not_ready))
    return SearchResult(
        question=question,
        day=day,
        clips=clips,
        note=" ".join(notes) or None,
        proofs=tuple(proofs[item.clip.id] for item in clips if item.clip.id in proofs),
    )


def _make_snapshots(
    snapshots: SnapshotStore, clips: Sequence[ClipWithCamera], proofs: dict[str, ClipProof]
) -> None:
    """Make the evidence snapshot of each clip that has a proof. A failure is logged by type
    and skipped: a missing picture must never break a search."""
    for item in clips:
        proof = proofs.get(item.clip.id)
        if proof is None:
            continue
        try:
            snapshots.create(item.clip, proof)
        except Exception as error:
            logger.warning("Snapshot for %s not made (%s)", item.clip.id, type(error).__name__)


def _remember_clips(library: Library, clips: Sequence[Clip]) -> None:
    """Write clips found from tracks to the clip store; one that is already there is kept."""
    for clip in clips:
        try:
            library.clips.add_clip(clip)
        except (DuplicateError, MissingReferenceError):
            pass  # same finding as an earlier search, or its recording was just deleted


def _zone_names(library: Library, camera_id: str | None) -> list[str]:
    """The searched cameras' zone names, ordered by name, each once."""
    return list(dict.fromkeys(zone.name for zone in library.zones.list_zones(camera_id)))


def _not_understood_note(zone_names: Sequence[str]) -> str:
    topics = ["someone carrying a box or package", "someone waiting or standing still"]
    if zone_names:
        topics.append(f"a zone ({', '.join(zone_names)})")
    topics.append("people in general")
    return (
        "The demo search did not recognise anything in this question. "
        f"Try asking about {', '.join(topics[:-1])}, or {topics[-1]}."
    )


def _not_ready_note(count: int) -> str:
    if count == 1:
        return "1 recording on this day is still being indexed, so it was not searched."
    return f"{count} recordings on this day are still being indexed, so they were not searched."
