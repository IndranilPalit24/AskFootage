"""The closed object vocabulary and the closed question schema."""

import math

import pytest

from askfootage.domain.vocabulary import (
    MAX_MIN_SECONDS,
    OBJECT_NOUNS,
    ZONE_NAME_MAX,
    InvalidQuestionError,
    ObjectNoun,
    Question,
    UnknownNounError,
    lookup_noun,
    parse_question,
)

# --- the vocabulary ----------------------------------------------------------------------


def test_the_vocabulary_is_exactly_the_four_nouns() -> None:
    assert OBJECT_NOUNS == frozenset({"person", "cardboard box", "bag", "crate"})
    assert {noun.value for noun in ObjectNoun} == OBJECT_NOUNS


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("person", ObjectNoun.PERSON),
        ("  Person ", ObjectNoun.PERSON),
        ("CARDBOARD BOX", ObjectNoun.CARDBOARD_BOX),
        ("cardboard \t  box", ObjectNoun.CARDBOARD_BOX),
        ("\nBag\n", ObjectNoun.BAG),
        ("Crate", ObjectNoun.CRATE),
    ],
)
def test_lookup_normalises_case_and_whitespace(text: str, expected: ObjectNoun) -> None:
    assert lookup_noun(text) is expected


@pytest.mark.parametrize(
    "text",
    ["", "   ", "box", "boxes", "cardboardbox", "pallet", "people", "persons", "bags", "dog"],
)
def test_lookup_refuses_anything_outside_the_vocabulary(text: str) -> None:
    with pytest.raises(UnknownNounError):
        lookup_noun(text)


def test_lookup_refuses_a_non_string() -> None:
    with pytest.raises(UnknownNounError):
        lookup_noun(3)  # type: ignore[arg-type]


def test_unknown_noun_error_is_a_value_error_naming_the_noun() -> None:
    with pytest.raises(ValueError, match="pallet"):
        lookup_noun("pallet")


def test_a_noun_is_a_plain_string_value() -> None:
    assert ObjectNoun.CARDBOARD_BOX == "cardboard box"
    assert str(ObjectNoun.BAG) == "bag"


# --- the question schema -----------------------------------------------------------------


def test_a_dwell_question_with_zone_and_minimum() -> None:
    question = Question("dwell", ObjectNoun.CRATE, zone="exit door", min_seconds=10)
    assert (question.relation, question.subject, question.zone, question.min_seconds) == (
        "dwell",
        ObjectNoun.CRATE,
        "exit door",
        10.0,
    )


def test_subject_text_is_looked_up_and_zone_is_trimmed() -> None:
    question = Question("in_zone", " Person ", zone="  loading door ")  # type: ignore[arg-type]
    assert question.subject is ObjectNoun.PERSON
    assert question.zone == "loading door"


def test_carrying_needs_no_zone_but_may_have_one() -> None:
    assert Question("carrying", ObjectNoun.CARDBOARD_BOX).zone is None
    assert Question("carrying", ObjectNoun.BAG, zone="loading door").zone == "loading door"


def test_dwell_without_a_minimum_is_allowed() -> None:
    assert Question("dwell", ObjectNoun.PERSON, zone="doorway").min_seconds is None


def test_questions_are_frozen_and_compare_by_value() -> None:
    question = Question("in_zone", ObjectNoun.PERSON, zone="doorway")
    assert question == Question("in_zone", "person", zone="doorway")  # type: ignore[arg-type]
    with pytest.raises(AttributeError):
        question.zone = "elsewhere"  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"relation": "teleport", "subject": "person", "zone": "doorway"},
        {"relation": "dwell", "subject": "pallet", "zone": "doorway"},
        {"relation": "in_zone", "subject": "person"},
        {"relation": "dwell", "subject": "person"},
        {"relation": "dwell", "subject": "person", "zone": "   "},
        {"relation": "dwell", "subject": "person", "zone": "z" * (ZONE_NAME_MAX + 1)},
        {"relation": "dwell", "subject": "person", "zone": 7},
        {"relation": "carrying", "subject": "person"},
        {"relation": "carrying", "subject": "bag", "min_seconds": 5},
        {"relation": "in_zone", "subject": "bag", "zone": "doorway", "min_seconds": 5},
        {"relation": "dwell", "subject": "bag", "zone": "doorway", "min_seconds": 0},
        {"relation": "dwell", "subject": "bag", "zone": "doorway", "min_seconds": -1},
        {"relation": "dwell", "subject": "bag", "zone": "doorway", "min_seconds": math.inf},
        {"relation": "dwell", "subject": "bag", "zone": "doorway", "min_seconds": math.nan},
        {"relation": "dwell", "subject": "bag", "zone": "doorway", "min_seconds": True},
        {"relation": "dwell", "subject": "bag", "zone": "doorway", "min_seconds": "10"},
        {
            "relation": "dwell",
            "subject": "bag",
            "zone": "doorway",
            "min_seconds": MAX_MIN_SECONDS + 1,
        },
    ],
)
def test_invalid_questions_are_refused(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Question(**kwargs)  # type: ignore[arg-type]


def test_zone_at_the_length_limit_is_accepted() -> None:
    assert Question("in_zone", ObjectNoun.BAG, zone="z" * ZONE_NAME_MAX).zone == "z" * 60


def test_an_unknown_subject_raises_unknown_noun_error() -> None:
    with pytest.raises(UnknownNounError):
        Question("dwell", "pallet", zone="doorway")  # type: ignore[arg-type]


# --- parsing the structured form ---------------------------------------------------------


def test_parse_question_reads_the_structured_form() -> None:
    data = {"relation": "dwell", "subject": "Crate", "zone": "exit door", "min_seconds": 10}
    assert parse_question(data) == Question(
        "dwell", ObjectNoun.CRATE, zone="exit door", min_seconds=10.0
    )


def test_parse_question_treats_missing_optional_keys_as_none() -> None:
    assert parse_question({"relation": "carrying", "subject": "bag"}) == Question(
        "carrying", ObjectNoun.BAG
    )
    assert parse_question(
        {"relation": "carrying", "subject": "bag", "zone": None, "min_seconds": None}
    ) == Question("carrying", ObjectNoun.BAG)


@pytest.mark.parametrize(
    "data",
    [
        {"subject": "bag"},
        {"relation": "carrying"},
        {"relation": "carrying", "subject": "bag", "who": "anyone"},
        {"relation": 1, "subject": "bag"},
    ],
)
def test_parse_question_refuses_missing_extra_or_bad_keys(data: dict[str, object]) -> None:
    with pytest.raises(InvalidQuestionError):
        parse_question(data)


def test_parse_question_refuses_a_non_mapping() -> None:
    with pytest.raises(InvalidQuestionError):
        parse_question(["dwell"])  # type: ignore[arg-type]


def test_invalid_question_error_is_a_value_error() -> None:
    assert issubclass(InvalidQuestionError, ValueError)
    assert issubclass(UnknownNounError, ValueError)
