"""MuseQuestionParser and the keyword fallback, tested offline with fake and replay transports."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from askfootage.adapters.meta.budget import BudgetedTransport, HardCapBudget
from askfootage.adapters.meta.muse import (
    MUSE_MODEL,
    MuseQuestionParser,
    build_request,
    estimate_muse_cost,
    extract_json_object,
    keyword_parse,
)
from askfootage.adapters.meta.record_replay import ReplayTransport, fingerprint
from askfootage.adapters.meta.transport import (
    MetaApiError,
    MetaConnectionError,
    MetaRequest,
    RawResponse,
)
from askfootage.ports.language_model import (
    SOURCE_FALLBACK,
    SOURCE_MODEL,
    QuestionNotUnderstoodError,
)
from askfootage.settings import MissingApiKeyError

TEXT = "Show me anyone carrying a crate near the loading dock"
GOOD = {"relation": "carrying", "subject": "crate", "zone": "loading dock", "min_seconds": None}


class FakeTransport:
    def __init__(self, reply: RawResponse | Exception) -> None:
        self.reply = reply
        self.requests: list[MetaRequest] = []

    def send(self, request: MetaRequest) -> RawResponse:
        self.requests.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def reply_with(text: str) -> RawResponse:
    body = {"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}
    return RawResponse(200, json.dumps(body))


def parse(reply: RawResponse | Exception, text: str = TEXT):
    transport = FakeTransport(reply)
    return MuseQuestionParser(transport).parse(text), transport


def test_valid_reply_gives_a_model_question() -> None:
    result, transport = parse(reply_with(json.dumps(GOOD)))
    assert result.source == SOURCE_MODEL
    assert (result.question.relation, result.question.subject.value) == ("carrying", "crate")
    assert result.question.zone == "loading dock"
    assert transport.requests[0].json_body["model"] == MUSE_MODEL


def test_code_fenced_and_chatty_reply_is_extracted() -> None:
    text = "Sure!\n```json\n" + json.dumps(GOOD) + "\n```\nHope that helps."
    result, _ = parse(reply_with(text))
    assert result.source == SOURCE_MODEL


@pytest.mark.parametrize(
    "body",
    [
        {"output_text": json.dumps(GOOD)},
        {"choices": [{"message": {"content": json.dumps(GOOD)}}]},
    ],
)
def test_other_reply_envelopes(body: dict) -> None:
    result, _ = parse(RawResponse(200, json.dumps(body)))
    assert result.source == SOURCE_MODEL


def test_dwell_with_minimum_time() -> None:
    reply = {"relation": "dwell", "subject": "person", "zone": "exit door", "min_seconds": 10}
    result, _ = parse(reply_with(json.dumps(reply)))
    assert result.source == SOURCE_MODEL
    assert result.question.min_seconds == 10.0


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        "{broken",
        "[1, 2]",
        json.dumps({**GOOD, "extra": 1}),
        json.dumps({**GOOD, "subject": "unicorn"}),
        json.dumps({**GOOD, "relation": "flying"}),
        json.dumps({"relation": "dwell", "subject": "crate"}),
        json.dumps({**GOOD, "min_seconds": 5}),
    ],
)
def test_invalid_model_reply_falls_back(text: str) -> None:
    result, _ = parse(reply_with(text))
    assert result.source == SOURCE_FALLBACK
    assert result.question.relation == "carrying"


@pytest.mark.parametrize("body", ["", "<html>", "[]", '{"output": 3}'])
def test_unusable_envelope_falls_back(body: str) -> None:
    result, _ = parse(RawResponse(200, body))
    assert result.source == SOURCE_FALLBACK


@pytest.mark.parametrize(
    "error",
    [MissingApiKeyError("no key"), MetaConnectionError("down"), MetaApiError(500, "boom")],
)
def test_transport_errors_fall_back(error: Exception) -> None:
    result, _ = parse(error)
    assert result.source == SOURCE_FALLBACK


def test_non_2xx_reply_falls_back() -> None:
    result, _ = parse(RawResponse(500, "x"))
    assert result.source == SOURCE_FALLBACK


def test_no_transport_uses_fallback() -> None:
    assert MuseQuestionParser(None).parse(TEXT).source == SOURCE_FALLBACK


def test_unparseable_everywhere_raises() -> None:
    with pytest.raises(QuestionNotUnderstoodError):
        MuseQuestionParser(None).parse("what is the weather")
    with pytest.raises(QuestionNotUnderstoodError):
        MuseQuestionParser(None).parse("   ")


def test_replay_transport_with_canned_reply(tmp_path: Path) -> None:
    request = build_request(TEXT)
    record = {
        "fingerprint": fingerprint(request),
        "path": request.path,
        "status": 200,
        "body": reply_with("```json\n" + json.dumps(GOOD) + "\n```").body,
    }
    (tmp_path / f"{record['fingerprint']}.json").write_text(json.dumps(record), encoding="utf-8")
    parser = MuseQuestionParser(ReplayTransport(tmp_path))
    result = parser.parse(TEXT)
    assert result.source == SOURCE_MODEL
    assert result.question.zone == "loading dock"
    # an unrecorded question degrades to the fallback instead of failing
    assert parser.parse("crate in the dock").source == SOURCE_FALLBACK


def test_cost_goes_through_budget(tmp_path: Path) -> None:
    budget = HardCapBudget(Decimal("1"), tmp_path)
    inner = FakeTransport(reply_with(json.dumps(GOOD)))
    guarded = BudgetedTransport(inner, budget, estimate_muse_cost)
    assert MuseQuestionParser(guarded).parse(TEXT).source == SOURCE_MODEL
    estimate = estimate_muse_cost(build_request(TEXT))
    assert estimate is not None
    assert budget.spent == estimate > 0


def test_exhausted_budget_falls_back_without_sending(tmp_path: Path) -> None:
    budget = HardCapBudget(Decimal("0"), tmp_path)
    inner = FakeTransport(reply_with(json.dumps(GOOD)))
    guarded = BudgetedTransport(inner, budget, estimate_muse_cost)
    assert MuseQuestionParser(guarded).parse(TEXT).source == SOURCE_FALLBACK
    assert inner.requests == []


def test_estimator_ignores_other_models() -> None:
    other = MetaRequest("/responses", json_body={"model": "sam-3.1", "input": "x"})
    assert estimate_muse_cost(other) is None


def test_request_is_deterministic_and_carries_the_question() -> None:
    assert build_request(TEXT) == build_request(TEXT)
    assert TEXT in json.dumps(build_request(TEXT).json_body)


def test_extract_json_object() -> None:
    assert extract_json_object('x {"a": {"b": "}"}} y') == {"a": {"b": "}"}}
    assert extract_json_object("nothing") is None


@pytest.mark.parametrize(
    ("text", "relation", "subject", "zone", "seconds"),
    [
        (
            "Someone carrying a box through the loading dock",
            "carrying",
            "cardboard box",
            "loading dock",
            None,
        ),
        ("person carrying a bag", "carrying", "bag", None, None),
        ("When did a crate enter the exit door?", "in_zone", "crate", "exit door", None),
        ("a person walks into the Aisle 3", "in_zone", "person", "Aisle 3", None),
        ("person stayed in the dock for more than 10 seconds", "dwell", "person", "dock", 10.0),
        ("who waited at the front desk for 2 minutes", "dwell", "person", "front desk", 120.0),
        ("crate lingering in the staging area", "dwell", "crate", "staging area", None),
    ],
)
def test_keyword_fallback(text, relation, subject, zone, seconds) -> None:
    question = keyword_parse(text)
    assert question.relation == relation
    assert question.subject.value == subject
    assert question.zone == zone
    assert question.min_seconds == seconds


@pytest.mark.parametrize("text", ["", "hello there", "a unicorn in the dock", "crate"])
def test_keyword_fallback_refuses_what_it_cannot_read(text: str) -> None:
    with pytest.raises(QuestionNotUnderstoodError):
        keyword_parse(text)
