"""Answer a plain-English question about one day of one camera's footage.

The question is turned into a SearchPlan by an interpreter, and the plan is checked
against the clips already found in that day's ready recordings. v1 uses
QuestionInterpreter, a deliberately simple keyword match. A model-backed interpreter can
replace it later: anything with the same interpret() method plugs into search_day(), and
the HTTP API does not change.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from askfootage.application.errors import InvalidInputError
from askfootage.application.library import Library, require_camera
from askfootage.ports.library_store import Clip, EvidenceKind

MAX_QUESTION_LENGTH = 300
"""Longest question accepted, in characters, before trimming."""

NO_FOOTAGE_NOTE = "There is no footage from this camera on this day."

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
        """The plan for `question`, given the names of the camera's zones."""
        ...


class QuestionInterpreter:
    """A deliberately simple keyword interpreter for the demo.

    - carry, box, package or parcel (and their forms): clips with carrying evidence.
    - wait, stay, stand, linger, loiter or dwell (and their forms): clips with dwell evidence.
    - a zone name of the camera, such as "loading door": clips in that zone.
    - several of these: a clip must meet all of them.
    - only general words such as person, someone, anyone or people: every clip.
    - nothing recognised: no clips (search_day then explains what it understands).

    It never looks at who a person is: there is no identity in the data to look at.
    """

    def interpret(self, question: str, zone_names: Sequence[str]) -> SearchPlan:
        """The plan for `question`, given the names of the camera's zones."""
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
    clips: list[Clip]
    note: str | None


def check_question(question: str) -> str:
    """The question trimmed; raises InvalidInputError if it is too long or blank."""
    if len(question) > MAX_QUESTION_LENGTH:
        raise InvalidInputError("question", f"must be at most {MAX_QUESTION_LENGTH} characters")
    trimmed = question.strip()
    if not trimmed:
        raise InvalidInputError("question", "must not be blank")
    return trimmed


def search_day(
    library: Library, interpreter: Interpreter, question: str, day: date, camera_id: str
) -> SearchResult:
    """Answer a question about one camera's footage on one day.

    Only ready recordings are searched. The note says what the answer left out: recordings
    still being indexed, a day without footage, or a question the interpreter did not
    understand. Raises InvalidInputError for a bad question and NotFoundError for an
    unknown camera.
    """
    question = check_question(question)
    require_camera(library, camera_id)
    recordings = library.recordings.list_recordings(camera_id, day)
    if not recordings:
        return SearchResult(question=question, day=day, clips=[], note=NO_FOOTAGE_NOTE)

    ready_ids = {recording.id for recording in recordings if recording.status == "ready"}
    zone_names = [zone.name for zone in library.zones.list_zones(camera_id)]
    plan = interpreter.interpret(question, zone_names)
    clips = sorted(
        (
            clip
            for clip in library.clips.list_clips(camera_id, day)
            if clip.recording_id in ready_ids and plan.matches(clip)
        ),
        key=lambda clip: (clip.start_time, clip.id),
    )

    notes: list[str] = []
    if not plan.understood:
        notes.append(_not_understood_note(zone_names))
    not_ready = len(recordings) - len(ready_ids)
    if not_ready:
        notes.append(_not_ready_note(not_ready))
    return SearchResult(question=question, day=day, clips=clips, note=" ".join(notes) or None)


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
