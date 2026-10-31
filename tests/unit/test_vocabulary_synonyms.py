"""Free-text query terms mapped to a relation and object nouns, deterministically."""

import pytest

from askfootage.domain.vocabulary import ObjectNoun, interpret_text


@pytest.mark.parametrize(
    ("text", "relation", "nouns"),
    [
        ("person carrying a box", "carrying", (ObjectNoun.PERSON, ObjectNoun.CARDBOARD_BOX)),
        ("who is holding a bag?", "carrying", (ObjectNoun.BAG,)),
        ("worker hauls crates", "carrying", (ObjectNoun.PERSON, ObjectNoun.CRATE)),
        ("someone entered the loading zone", "in_zone", (ObjectNoun.PERSON,)),
        ("a person walks into the zone", "in_zone", (ObjectNoun.PERSON,)),
        ("a parcel enters the restricted area", "in_zone", (ObjectNoun.CARDBOARD_BOX,)),
        ("anything in the zone", "in_zone", ()),
        ("person stays in the zone", "dwell", (ObjectNoun.PERSON,)),
        ("a crate lingers by the door", "dwell", (ObjectNoun.CRATE,)),
        ("who dwells near the exit", "dwell", ()),
        ("Backpack LOITERS", "dwell", (ObjectNoun.BAG,)),
        ("cardboard box carried", "carrying", (ObjectNoun.CARDBOARD_BOX,)),
    ],
)
def test_text_maps_to_relation_and_nouns(
    text: str, relation: str, nouns: tuple[ObjectNoun, ...]
) -> None:
    result = interpret_text(text)
    assert result.relation == relation
    assert result.nouns == nouns


def test_no_match_gives_none_and_empty() -> None:
    result = interpret_text("sunny weather")
    assert result.relation is None
    assert result.nouns == ()


def test_strong_relation_beats_the_weak_word_zone() -> None:
    assert interpret_text("lingers in the zone").relation == "dwell"


def test_earliest_strong_relation_wins() -> None:
    assert interpret_text("carrying a bag then stays").relation == "carrying"


def test_deterministic_and_nouns_deduplicated() -> None:
    first = interpret_text("bag, bags and a handbag")
    assert first == interpret_text("bag, bags and a handbag")
    assert first.nouns == (ObjectNoun.BAG,)


def test_subject_prefers_the_object_over_the_person() -> None:
    assert interpret_text("person carrying a crate").subject is ObjectNoun.CRATE
    assert interpret_text("person enters zone").subject is ObjectNoun.PERSON
    assert interpret_text("zone").subject is None


def test_non_text_is_refused() -> None:
    with pytest.raises(TypeError):
        interpret_text(5)  # type: ignore[arg-type]
