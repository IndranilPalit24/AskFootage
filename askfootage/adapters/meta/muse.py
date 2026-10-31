"""Muse Spark question parsing: a typed search question in, a structured Question out.

MuseQuestionParser asks the Muse model, through any Transport, to turn a sentence into the
closed question schema (relation, subject, zone, min_seconds; see domain/vocabulary.py).
The model's reply is held to that schema strictly: the first JSON object found in it (code
fences and chatter around it are tolerated) must pass parse_question, or it is discarded.

Whenever the model cannot be used, a deterministic keyword reader (keyword_parse) answers
instead and the result is marked SOURCE_FALLBACK. That covers: no transport, no API key, a
budget refusal or dry run, any Meta error or non-2xx reply, and a reply that is not valid.
If the keyword reader cannot read the question either, QuestionNotUnderstoodError is raised.

Cost: hand the parser a BudgetedTransport built with estimate_muse_cost, so every call is
authorized against the hard cap before it is sent.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from askfootage.adapters.meta.budget import DryRunSendError
from askfootage.adapters.meta.transport import MetaError, MetaRequest, Transport
from askfootage.domain.vocabulary import OBJECT_NOUNS, Question, parse_question
from askfootage.ports.budget import BudgetError
from askfootage.ports.language_model import (
    SOURCE_FALLBACK,
    SOURCE_MODEL,
    ParsedQuestion,
    QuestionNotUnderstoodError,
)
from askfootage.settings import MissingApiKeyError

MUSE_MODEL = "muse-spark-1.3"
"""Model that parses questions."""

MAX_OUTPUT_TOKENS = 200
"""Output-token limit: the reply is one small JSON object."""

MUSE_PARSE_ESTIMATE_USD = Decimal("0.001")
"""Budget reservation for one parse call: a short prompt and a short reply."""

_PROMPT = (
    "Turn the search question into one JSON object and reply with only that object.\n"
    'Fields: "relation" is one of "carrying" (a person carries the object), "in_zone" '
    '(the object enters a zone) or "dwell" (the object stays in a zone); "subject" is one of '
    + ", ".join(f'"{noun}"' for noun in sorted(OBJECT_NOUNS))
    + ' (for carrying, the carried object, never "person"); "zone" is the zone name as '
    'written in the question, or null (required for in_zone and dwell); "min_seconds" is a '
    "number of seconds above 0 for a dwell with a stated minimum time, otherwise null.\n"
    "Question: "
)


def build_request(text: str) -> MetaRequest:
    """The /responses request asking Muse to parse `text`. Deterministic, so it replays."""
    return MetaRequest(
        "/responses",
        json_body={
            "model": MUSE_MODEL,
            "input": _PROMPT + text.strip(),
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        },
    )


def estimate_muse_cost(request: MetaRequest) -> Decimal | None:
    """Estimator for BudgetedTransport: the flat parse cost for a Muse request, else None."""
    body = request.json_body
    if body is not None and body.get("model") == MUSE_MODEL:
        return MUSE_PARSE_ESTIMATE_USD
    return None


class MuseQuestionParser:
    """Implements the QuestionParser port with Muse, falling back to keywords.

    `transport` may be None, which means keyword reading only.
    """

    def __init__(self, transport: Transport | None) -> None:
        self._transport = transport

    def parse(self, text: str) -> ParsedQuestion:
        """The structured form of `text`; see the module docstring for the fallback rules."""
        if not isinstance(text, str) or not text.strip():
            raise QuestionNotUnderstoodError("The question is empty")
        question = self._ask_model(text)
        if question is not None:
            return ParsedQuestion(question, SOURCE_MODEL)
        return ParsedQuestion(keyword_parse(text), SOURCE_FALLBACK)

    def _ask_model(self, text: str) -> Question | None:
        if self._transport is None:
            return None
        try:
            reply = self._transport.send(build_request(text))
        except (MetaError, BudgetError, DryRunSendError, MissingApiKeyError):
            return None
        if not 200 <= reply.status < 300:
            return None
        reply_text = _reply_text(reply.body)
        data = None if reply_text is None else extract_json_object(reply_text)
        if data is None:
            return None
        try:
            return parse_question(data)
        except ValueError:  # InvalidQuestionError and UnknownNounError
            return None


def _reply_text(body: str) -> str | None:
    """The model's text from a /responses body, in the shapes such APIs commonly use."""
    try:
        data: Any = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    output = data.get("output")
    if isinstance(output, list):
        parts = [
            part["text"]
            for item in output
            if isinstance(item, dict) and isinstance(item.get("content"), list)
            for part in item["content"]
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        if parts:
            return "\n".join(parts)
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    return None


def extract_json_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in `text`, ignoring code fences and any text around it."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    return None


# --- deterministic keyword fallback -------------------------------------------------------

_ALIASES: dict[str, str] = {
    "person": "person",
    "people": "person",
    "someone": "person",
    "anyone": "person",
    "somebody": "person",
    "who": "person",
    "man": "person",
    "woman": "person",
    "worker": "person",
    "employee": "person",
    "cardboard box": "cardboard box",
    "box": "cardboard box",
    "boxes": "cardboard box",
    "package": "cardboard box",
    "parcel": "cardboard box",
    "bag": "bag",
    "bags": "bag",
    "backpack": "bag",
    "crate": "crate",
    "crates": "crate",
}
_NOUN_RE = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, _ALIASES), key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_CARRY_RE = re.compile(r"\b(?:carry|carries|carrying|carried|holding|hauling|lifting)\b", re.I)
_DWELL_RE = re.compile(
    r"\b(?:stay|stays|stayed|staying|dwell|dwells|dwelling|wait|waits|waited|waiting|"
    r"linger|lingers|lingered|lingering|loiter\w*|remain\w*)\b",
    re.I,
)
_ENTER_RE = re.compile(r"\b(?:enter|enters|entered|entering|into)\b", re.I)
_ZONE_RE = re.compile(
    r"\b(?:enters?|entered|entering|into|inside|within|through|near|in|at|on)\s+"
    r"(?:(?:the|a|an)\s+)?(.+?)"
    r"(?=\s+(?:for|more\s+than|longer|over|at\s+least)\b|\s*[?.!,;]*\s*$)",
    re.I,
)
_SECONDS_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?)\b", re.IGNORECASE)


def keyword_parse(text: str) -> Question:
    """Read `text` by keywords alone: deterministic, offline, and deliberately modest.

    Relation: carrying words, else dwell words or a stated duration, else a zone (in_zone).
    Subject: the first known noun (a carried object, never a person, for carrying). Zone:
    the words after the first place word (in, into, at, near, through, enter...). Raises
    QuestionNotUnderstoodError when no valid Question can be read.
    """
    zone_match = _ZONE_RE.search(text)
    zone = zone_match.group(1).strip() if zone_match else None
    before = text[: zone_match.start()] if zone_match else text
    subject = _pick_subject(before, carrying=bool(_CARRY_RE.search(text))) or _pick_subject(
        text, carrying=bool(_CARRY_RE.search(text))
    )
    seconds = _seconds(text)
    if _CARRY_RE.search(text):
        relation = "carrying"
    elif _DWELL_RE.search(text) or seconds is not None:
        relation = "dwell"
    elif _ENTER_RE.search(text) or zone is not None:
        relation = "in_zone"
    else:
        relation = None
    if relation is None or subject is None:
        raise QuestionNotUnderstoodError("I could not tell what to look for in that question")
    try:
        return parse_question(
            {
                "relation": relation,
                "subject": subject,
                "zone": zone,
                "min_seconds": seconds if relation == "dwell" else None,
            }
        )
    except ValueError:
        raise QuestionNotUnderstoodError(
            "I could not tell what to look for in that question"
        ) from None


def _pick_subject(text: str, *, carrying: bool) -> str | None:
    nouns = [_ALIASES[match.group(1).lower()] for match in _NOUN_RE.finditer(text)]
    if carrying:
        nouns = [noun for noun in nouns if noun != "person"]
    return nouns[0] if nouns else None


def _seconds(text: str) -> float | None:
    match = _SECONDS_RE.search(text)
    if match is None:
        return None
    value = float(match.group(1))
    return value * 60 if match.group(2).lower().startswith("m") else value
