"""The closed object vocabulary and the closed question schema.

AskFootage only looks for a fixed set of object nouns, and a question is only ever one of a
fixed set of shapes: a relation, the object it is about, an optional zone and an optional
minimum time. Anything outside these is refused here, before any search runs. A noun names
a kind of object, never who someone is. Pure data: no I/O.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from askfootage.domain.intervals import RELATION_KINDS, RelationKind

ZONE_NAME_MAX = 60
"""Longest zone name in a question, in characters; the same limit as a saved zone name."""

MAX_MIN_SECONDS = 3600.0
"""Largest minimum time a question may ask for: one hour, far beyond any clip here."""

_QUESTION_KEYS = frozenset({"relation", "subject", "zone", "min_seconds"})


class UnknownNounError(ValueError):
    """The text is not one of the object nouns AskFootage looks for."""


class InvalidQuestionError(ValueError):
    """The question does not fit the closed question schema."""


class ObjectNoun(StrEnum):
    """An object noun AskFootage looks for. The value is the canonical, lower-case noun."""

    PERSON = "person"
    CARDBOARD_BOX = "cardboard box"
    BAG = "bag"
    CRATE = "crate"


OBJECT_NOUNS: frozenset[str] = frozenset(noun.value for noun in ObjectNoun)
"""Every canonical noun in the vocabulary."""


def lookup_noun(text: str) -> ObjectNoun:
    """The noun `text` names, ignoring case and runs of whitespace.

    Only exact nouns match: no plurals, aliases or partial words. Raises UnknownNounError
    for anything else.
    """
    if not isinstance(text, str):
        raise UnknownNounError(f"an object noun must be text; got {type(text).__name__}")
    normalised = " ".join(text.casefold().split())
    try:
        return ObjectNoun(normalised)
    except ValueError:
        known = ", ".join(sorted(OBJECT_NOUNS))
        raise UnknownNounError(f"unknown object noun {text!r}; known: {known}") from None


@dataclass(frozen=True, slots=True)
class Question:
    """One question in the closed schema.

    relation: carrying (a person moves with the subject), in_zone (the subject enters a
    zone) or dwell (the subject stays in a zone).
    subject: the object the question is about; text is looked up in the vocabulary. For
    carrying it is the carried object, so it cannot be a person.
    zone: the zone's name, trimmed. Required for in_zone and dwell, optional for carrying.
    min_seconds: the least time a dwell must last; only dwell takes one. None means the
    rule's own default.
    """

    relation: RelationKind
    subject: ObjectNoun
    zone: str | None = None
    min_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.relation not in RELATION_KINDS:
            raise InvalidQuestionError(f"relation must be one of {', '.join(RELATION_KINDS)}")
        object.__setattr__(self, "subject", lookup_noun(self.subject))
        object.__setattr__(self, "zone", _checked_zone(self.relation, self.zone))
        object.__setattr__(
            self, "min_seconds", _checked_min_seconds(self.relation, self.min_seconds)
        )
        if self.relation == "carrying" and self.subject is ObjectNoun.PERSON:
            raise InvalidQuestionError("carrying needs an object to carry, not a person")


def _checked_zone(relation: RelationKind, zone: object) -> str | None:
    if zone is None:
        if relation != "carrying":
            raise InvalidQuestionError(f"{relation} needs a zone")
        return None
    if not isinstance(zone, str):
        raise InvalidQuestionError("zone must be text")
    trimmed = zone.strip()
    if not trimmed:
        raise InvalidQuestionError("zone must not be blank")
    if len(trimmed) > ZONE_NAME_MAX:
        raise InvalidQuestionError(f"zone must be at most {ZONE_NAME_MAX} characters")
    return trimmed


def _checked_min_seconds(relation: RelationKind, min_seconds: object) -> float | None:
    if min_seconds is None:
        return None
    if relation != "dwell":
        raise InvalidQuestionError("only a dwell question takes a minimum time")
    if isinstance(min_seconds, bool) or not isinstance(min_seconds, int | float):
        raise InvalidQuestionError("min_seconds must be a number")
    value = float(min_seconds)
    if not math.isfinite(value) or not 0 < value <= MAX_MIN_SECONDS:
        raise InvalidQuestionError(f"min_seconds must be above 0 and at most {MAX_MIN_SECONDS}")
    return value


def parse_question(data: Mapping[str, object]) -> Question:
    """A Question from its structured form, e.g. {"relation": "dwell", "subject": "crate",
    "zone": "exit door", "min_seconds": 10}.

    "zone" and "min_seconds" may be missing or None. Any other key is refused. Raises
    InvalidQuestionError for a bad shape or value and UnknownNounError for an unknown noun.
    """
    if not isinstance(data, Mapping):
        raise InvalidQuestionError("a question must be a mapping of fields")
    extra = set(data) - _QUESTION_KEYS
    if extra:
        raise InvalidQuestionError(f"unknown question fields: {', '.join(sorted(map(str, extra)))}")
    for key in ("relation", "subject"):
        if key not in data:
            raise InvalidQuestionError(f"a question needs a {key}")
    relation = data["relation"]
    if not isinstance(relation, str):
        raise InvalidQuestionError("relation must be text")
    return Question(
        relation,  # type: ignore[arg-type]  # checked against RELATION_KINDS on construction
        data["subject"],  # type: ignore[arg-type]  # looked up on construction
        zone=data.get("zone"),  # type: ignore[arg-type]
        min_seconds=data.get("min_seconds"),  # type: ignore[arg-type]
    )
