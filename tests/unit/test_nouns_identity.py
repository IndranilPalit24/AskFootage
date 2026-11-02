"""A noun naming a face or an identity is refused, however it is joined (ADR 0008)."""

from __future__ import annotations

import pytest

from askfootage.application.errors import InvalidInputError
from askfootage.application.nouns import check_noun


@pytest.mark.parametrize(
    "noun", ["face", "face scan", "face-scan", "facial-id", "iris-reader", "my identity card"]
)
def test_identity_nouns_are_refused(noun: str) -> None:
    with pytest.raises(InvalidInputError):
        check_noun(noun)


def test_an_object_noun_is_accepted() -> None:
    assert check_noun("traffic cone") == "traffic cone"
