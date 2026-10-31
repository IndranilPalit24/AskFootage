"""Port for turning a typed search question into a structured Question.

The Muse adapter (askfootage/adapters/meta/muse.py) implements it. Standard library and
domain only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from askfootage.domain.vocabulary import Question

SOURCE_MODEL = "model"
"""The language model understood the question."""
SOURCE_FALLBACK = "fallback"
"""The deterministic keyword reader understood it, because the model was not available."""


class QuestionNotUnderstoodError(Exception):
    """The question fits no shape AskFootage answers. The message is safe to show."""


@dataclass(frozen=True, slots=True)
class ParsedQuestion:
    """A Question plus who produced it: SOURCE_MODEL or SOURCE_FALLBACK."""

    question: Question
    source: str


class QuestionParser(Protocol):
    """Reads a natural-language search question."""

    def parse(self, text: str) -> ParsedQuestion:
        """The structured form of `text`; raises QuestionNotUnderstoodError if it has none."""
        ...
