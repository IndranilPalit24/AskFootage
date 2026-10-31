"""Behaviour of the hard spend cap and the budgeted transport, all offline.

The inner transport is a scripted stand-in that counts calls, so nothing reaches the
network and nothing is spent. Ledgers live in pytest's tmp_path.
"""

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from askfootage.adapters.meta.budget import (
    LEDGER_FILE_NAME,
    MIN_FRAMES_PER_REQUEST,
    PRICE_PER_1000_FRAMES_USD,
    BudgetedTransport,
    DryRunSendError,
    HardCapBudget,
    frames_cost,
)
from askfootage.adapters.meta.transport import (
    MetaApiError,
    MetaConnectionError,
    MetaRequest,
    RawResponse,
    Transport,
)
from askfootage.ports.budget import (
    Budget,
    BudgetExceededError,
    MissingEstimateError,
    format_dollars,
)

REQUEST = MetaRequest("/responses", json_body={"model": "muse-test", "input": "hello"})
OK = RawResponse(200, '{"ok": true}')
CAP = Decimal("0.50")


class CountingTransport:
    """Stands in for the live client: replies with `reply` (or raises it) and counts calls."""

    def __init__(self, reply: RawResponse | Exception = OK) -> None:
        self.reply = reply
        self.calls: list[MetaRequest] = []

    def send(self, request: MetaRequest) -> RawResponse:
        """Count the call, then reply or raise as scripted."""
        self.calls.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _fixed(amount: str | None) -> Callable[[MetaRequest], Decimal | None]:
    value = None if amount is None else Decimal(amount)
    return lambda _request: value


def _transport(
    tmp_path: Path,
    inner: CountingTransport,
    estimate: str | None = "0.01",
    cap: Decimal = CAP,
    dry_run: bool = False,
) -> tuple[BudgetedTransport, HardCapBudget]:
    budget = HardCapBudget(cap, tmp_path / "ledger")
    return BudgetedTransport(inner, budget, _fixed(estimate), dry_run=dry_run), budget


def _ledger_lines(tmp_path: Path) -> list[dict[str, str]]:
    path = tmp_path / "ledger" / LEDGER_FILE_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- Decimal math -------------------------------------------------------------------------


def test_price_constants_are_exact() -> None:
    assert PRICE_PER_1000_FRAMES_USD == Decimal("0.20")
    assert type(PRICE_PER_1000_FRAMES_USD) is Decimal
    assert MIN_FRAMES_PER_REQUEST == 50


@pytest.mark.parametrize(
    ("frames", "expected"),
    [(900, "0.18"), (20, "0.01"), (50, "0.01"), (0, "0.01"), (51, "0.0102"), (1000, "0.20")],
)
def test_frames_cost_is_an_exact_decimal_with_a_minimum(frames: int, expected: str) -> None:
    cost = frames_cost(frames)
    assert type(cost) is Decimal
    assert cost == Decimal(expected)


@pytest.mark.parametrize("bad", [-1, -900])
def test_frames_cost_rejects_negative_frames(bad: int) -> None:
    with pytest.raises(ValueError, match="frames"):
        frames_cost(bad)


@pytest.mark.parametrize("bad", [1.5, True, "900"])
def test_frames_cost_rejects_non_integers(bad: object) -> None:
    with pytest.raises(TypeError, match="frames"):
        frames_cost(bad)  # type: ignore[arg-type]


def test_spend_adds_up_exactly(tmp_path: Path) -> None:
    transport, budget = _transport(tmp_path, CountingTransport(), estimate="0.10")
    for _ in range(3):
        transport.send(REQUEST)
    assert type(budget.spent) is Decimal
    assert budget.spent == Decimal("0.30")
    assert budget.remaining == Decimal("0.20")


# --- Cap boundaries -----------------------------------------------------------------------


def test_spending_exactly_up_to_the_cap_is_allowed(tmp_path: Path) -> None:
    inner = CountingTransport()
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    estimates = iter([Decimal("0.48"), Decimal("0.02")])
    transport = BudgetedTransport(inner, budget, lambda _request: next(estimates))
    transport.send(REQUEST)
    transport.send(REQUEST)
    assert len(inner.calls) == 2
    assert budget.spent == CAP
    assert budget.remaining == Decimal(0)


def test_a_single_call_costing_the_whole_cap_is_allowed(tmp_path: Path) -> None:
    inner = CountingTransport()
    transport, budget = _transport(tmp_path, inner, estimate="0.50")
    assert transport.send(REQUEST) == OK
    assert budget.spent == CAP


def test_one_cent_over_the_cap_is_refused_and_nothing_is_sent(tmp_path: Path) -> None:
    inner = CountingTransport()
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    estimates = iter([Decimal("0.48"), Decimal("0.03")])
    transport = BudgetedTransport(inner, budget, lambda _request: next(estimates))
    transport.send(REQUEST)
    with pytest.raises(BudgetExceededError) as refused:
        transport.send(REQUEST)
    assert len(inner.calls) == 1
    assert budget.spent == Decimal("0.48")
    assert budget.remaining == Decimal("0.02")
    assert str(refused.value) == "$0.48 spent + $0.03 estimated would exceed the $0.50 cap"


def test_once_the_cap_is_reached_even_a_cent_is_refused(tmp_path: Path) -> None:
    inner = CountingTransport()
    transport, budget = _transport(tmp_path, inner, estimate="0.50")
    transport.send(REQUEST)
    refuse_cent = BudgetedTransport(inner, budget, _fixed("0.01"))
    with pytest.raises(BudgetExceededError):
        refuse_cent.send(REQUEST)
    assert len(inner.calls) == 1
    assert budget.spent == CAP


def test_a_refused_estimate_reserves_nothing(tmp_path: Path) -> None:
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    with pytest.raises(BudgetExceededError):
        budget.authorize(Decimal("0.51"))
    assert budget.remaining == CAP
    budget.authorize(CAP)
    assert budget.remaining == Decimal(0)


def test_in_flight_reservations_count_against_the_cap(tmp_path: Path) -> None:
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    budget.authorize(Decimal("0.30"))
    with pytest.raises(BudgetExceededError) as refused:
        budget.authorize(Decimal("0.21"))
    assert str(refused.value) == (
        "$0.00 spent (+ $0.30 in flight) + $0.21 estimated would exceed the $0.50 cap"
    )
    budget.record(Decimal("0.30"), reservation=Decimal("0.30"))
    assert budget.spent == Decimal("0.30")
    assert budget.remaining == Decimal("0.20")


def test_release_frees_a_reservation_without_spending(tmp_path: Path) -> None:
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    budget.authorize(Decimal("0.40"))
    budget.release(Decimal("0.40"))
    assert budget.spent == Decimal(0)
    assert budget.remaining == CAP


def test_the_cap_is_given_not_read_from_settings(tmp_path: Path) -> None:
    budget = HardCapBudget(Decimal("1.25"), tmp_path / "ledger")
    assert budget.cap == Decimal("1.25")
    assert budget.remaining == Decimal("1.25")


@pytest.mark.parametrize("bad", [0.5, 1, "0.50"])
def test_a_cap_that_is_not_a_decimal_is_rejected(tmp_path: Path, bad: object) -> None:
    with pytest.raises(TypeError, match="cap"):
        HardCapBudget(bad, tmp_path / "ledger")  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["-0.01", "NaN", "Infinity"])
def test_a_negative_or_non_finite_cap_is_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="cap"):
        HardCapBudget(Decimal(bad), tmp_path / "ledger")


def test_hard_cap_budget_satisfies_the_port(tmp_path: Path) -> None:
    budget: Budget = HardCapBudget(CAP, tmp_path / "ledger")
    assert budget.cap == CAP


# --- Messages -----------------------------------------------------------------------------


def test_exceeded_message_states_spent_estimate_and_cap() -> None:
    error = BudgetExceededError(spent=Decimal("0.48"), estimate=Decimal("0.03"), cap=CAP)
    assert str(error) == "$0.48 spent + $0.03 estimated would exceed the $0.50 cap"
    assert (error.spent, error.estimate, error.cap) == (Decimal("0.48"), Decimal("0.03"), CAP)


@pytest.mark.parametrize(
    ("amount", "shown"),
    [("0.5", "$0.50"), ("25", "$25.00"), ("0.0102", "$0.0102"), ("0", "$0.00"), ("0.180", "$0.18")],
)
def test_dollars_keep_cents_and_never_hide_a_fraction(amount: str, shown: str) -> None:
    assert format_dollars(Decimal(amount)) == shown


def test_refusal_message_holds_no_request_details(tmp_path: Path) -> None:
    secret_request = MetaRequest(
        "/files/C:/Users/someone/clip.mp4", json_body={"token": "SECRET-BODY-VALUE"}
    )
    transport, _budget = _transport(tmp_path, CountingTransport(), estimate="0.51")
    with pytest.raises(BudgetExceededError) as refused:
        transport.send(secret_request)
    message = str(refused.value)
    assert "SECRET" not in message
    assert "Users" not in message
    assert "/files" not in message


# --- Fail closed --------------------------------------------------------------------------


def test_no_estimate_means_no_send(tmp_path: Path) -> None:
    inner = CountingTransport()
    transport, budget = _transport(tmp_path, inner, estimate=None)
    with pytest.raises(MissingEstimateError):
        transport.send(REQUEST)
    assert inner.calls == []
    assert budget.spent == Decimal(0)
    assert budget.remaining == CAP


def test_an_estimator_that_raises_means_no_send(tmp_path: Path) -> None:
    def broken(_request: MetaRequest) -> Decimal | None:
        raise ValueError("cannot read C:/Users/someone/clip.mp4")

    inner = CountingTransport()
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    transport = BudgetedTransport(inner, budget, broken)
    with pytest.raises(MissingEstimateError) as refused:
        transport.send(REQUEST)
    assert inner.calls == []
    assert budget.remaining == CAP
    assert "Users" not in str(refused.value)
    assert refused.value.__cause__ is None
    assert refused.value.__suppress_context__


@pytest.mark.parametrize("bad", [0.01, 1, "0.01", Decimal("-0.01"), Decimal("NaN")])
def test_an_estimate_that_is_not_a_usable_decimal_means_no_send(
    tmp_path: Path, bad: object
) -> None:
    inner = CountingTransport()
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    transport = BudgetedTransport(inner, budget, lambda _request: bad)  # type: ignore[arg-type,return-value]
    with pytest.raises(MissingEstimateError):
        transport.send(REQUEST)
    assert inner.calls == []
    assert budget.remaining == CAP


@pytest.mark.parametrize("bad", [None, 0.01, Decimal("-1"), Decimal("sNaN")])
def test_authorize_itself_refuses_an_unusable_estimate(tmp_path: Path, bad: object) -> None:
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    with pytest.raises(MissingEstimateError):
        budget.authorize(bad)  # type: ignore[arg-type]
    assert budget.remaining == CAP


# --- Failures add no spend ----------------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [MetaApiError(500, "server error"), MetaConnectionError("unreachable"), RuntimeError("bug")],
    ids=["api-error", "connection-error", "unexpected-error"],
)
def test_a_failed_call_adds_no_spend_and_frees_its_reservation(
    tmp_path: Path, failure: Exception
) -> None:
    inner = CountingTransport(failure)
    transport, budget = _transport(tmp_path, inner, estimate="0.20")
    with pytest.raises(type(failure)):
        transport.send(REQUEST)
    assert len(inner.calls) == 1
    assert budget.spent == Decimal(0)
    assert budget.remaining == CAP


@pytest.mark.parametrize("status", [100, 199, 300, 404, 429, 500, 503])
def test_a_non_2xx_reply_is_returned_but_adds_no_spend(tmp_path: Path, status: int) -> None:
    reply = RawResponse(status, "nope")
    transport, budget = _transport(tmp_path, CountingTransport(reply), estimate="0.20")
    assert transport.send(REQUEST) == reply
    assert budget.spent == Decimal(0)
    assert budget.remaining == CAP


@pytest.mark.parametrize("status", [200, 201, 204, 299])
def test_every_2xx_reply_is_recorded(tmp_path: Path, status: int) -> None:
    reply = RawResponse(status, "")
    transport, budget = _transport(tmp_path, CountingTransport(reply), estimate="0.20")
    assert transport.send(REQUEST) == reply
    assert budget.spent == Decimal("0.20")


def test_spend_is_recorded_only_after_the_reply(tmp_path: Path) -> None:
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    seen: list[tuple[Decimal, Decimal]] = []

    class Watching:
        def send(self, request: MetaRequest) -> RawResponse:
            seen.append((budget.spent, budget.remaining))
            return OK

    BudgetedTransport(Watching(), budget, _fixed("0.20")).send(REQUEST)
    assert seen == [(Decimal(0), Decimal("0.30"))]
    assert budget.spent == Decimal("0.20")


def test_budgeted_transport_is_a_transport(tmp_path: Path) -> None:
    transport: Transport = _transport(tmp_path, CountingTransport())[0]
    assert transport.send(REQUEST) == OK


# --- Ledger -------------------------------------------------------------------------------


def test_ledger_has_one_line_per_call_with_its_outcome(tmp_path: Path) -> None:
    inner = CountingTransport()
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    BudgetedTransport(inner, budget, _fixed("0.30")).send(REQUEST)
    with pytest.raises(BudgetExceededError):
        BudgetedTransport(inner, budget, _fixed("0.30")).send(REQUEST)
    with pytest.raises(MissingEstimateError):
        BudgetedTransport(inner, budget, _fixed(None)).send(REQUEST)
    inner.reply = MetaApiError(500, "server error")
    with pytest.raises(MetaApiError):
        BudgetedTransport(inner, budget, _fixed("0.10")).send(REQUEST)
    inner.reply = RawResponse(429, "slow down")
    BudgetedTransport(inner, budget, _fixed("0.10")).send(REQUEST)

    lines = _ledger_lines(tmp_path)
    assert [line["outcome"] for line in lines] == [
        "sent",
        "refused",
        "no_estimate",
        "failed",
        "http_429",
    ]
    assert [line["estimate"] for line in lines] == ["0.30", "0.30", None, "0.10", "0.10"]
    assert [line["spent_after"] for line in lines] == ["0.30"] * 5
    for line in lines:
        assert set(line) == {"time", "run", "method", "path", "estimate", "outcome", "spent_after"}
        assert line["method"] == "POST"
        assert line["path"] == "/responses"
        assert line["time"].endswith("+00:00")
    assert len({line["run"] for line in lines}) == 1


def test_ledger_is_utf8_with_lf_endings(tmp_path: Path) -> None:
    transport, _budget = _transport(tmp_path, CountingTransport())
    transport.send(MetaRequest("/caf\u00e9", json_body={}))
    transport.send(REQUEST)
    raw = (tmp_path / "ledger" / LEDGER_FILE_NAME).read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 2
    assert "/caf\u00e9".encode() in raw
    raw.decode("utf-8")


def test_ledger_holds_no_bodies_headers_or_query_strings(tmp_path: Path) -> None:
    request = MetaRequest("/responses?key=QUERY-SECRET", json_body={"input": "SECRET-BODY"})
    transport, _budget = _transport(tmp_path, CountingTransport())
    transport.send(request)
    text = (tmp_path / "ledger" / LEDGER_FILE_NAME).read_text(encoding="utf-8")
    assert "SECRET" not in text
    assert "Authorization" not in text
    assert "Bearer" not in text
    assert _ledger_lines(tmp_path)[0]["path"] == "/responses"


def test_ledger_is_append_only_across_budgets(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    earlier = b'{"outcome": "from an earlier run"}\n'
    (ledger_dir / LEDGER_FILE_NAME).write_bytes(earlier)

    first, _ = _transport(tmp_path, CountingTransport())
    first.send(REQUEST)
    after_first = (ledger_dir / LEDGER_FILE_NAME).read_bytes()
    second, second_budget = _transport(tmp_path, CountingTransport())
    second.send(REQUEST)
    after_second = (ledger_dir / LEDGER_FILE_NAME).read_bytes()

    assert after_first.startswith(earlier)
    assert after_second.startswith(after_first)
    lines = _ledger_lines(tmp_path)
    assert len(lines) == 3
    assert lines[1]["run"] != lines[2]["run"]
    assert second_budget.spent == Decimal("0.01")  # a new run starts from zero


def test_ledger_dir_is_created_when_missing(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "deep" / "ledger"
    HardCapBudget(CAP, ledger_dir)
    assert ledger_dir.is_dir()


# --- Dry run ------------------------------------------------------------------------------


def test_dry_run_preview_returns_the_estimate_and_sends_nothing(tmp_path: Path) -> None:
    inner = CountingTransport()
    transport, budget = _transport(tmp_path, inner, estimate="0.18", dry_run=True)
    assert transport.dry_run is True
    estimate = transport.preview(REQUEST)
    assert estimate == Decimal("0.18")
    assert type(estimate) is Decimal
    assert inner.calls == []
    assert budget.spent == Decimal(0)
    assert budget.remaining == CAP
    assert _ledger_lines(tmp_path) == []


def test_dry_run_send_raises_and_sends_nothing(tmp_path: Path) -> None:
    inner = CountingTransport()
    transport, budget = _transport(tmp_path, inner, dry_run=True)
    with pytest.raises(DryRunSendError, match="dry run"):
        transport.send(REQUEST)
    assert inner.calls == []
    assert budget.remaining == CAP


def test_preview_fails_closed_too(tmp_path: Path) -> None:
    transport, _budget = _transport(tmp_path, CountingTransport(), estimate=None, dry_run=True)
    with pytest.raises(MissingEstimateError):
        transport.preview(REQUEST)


def test_preview_works_outside_dry_run_without_spending(tmp_path: Path) -> None:
    inner = CountingTransport()
    transport, budget = _transport(tmp_path, inner, estimate="0.05")
    assert transport.dry_run is False
    assert transport.preview(REQUEST) == Decimal("0.05")
    assert inner.calls == []
    assert budget.remaining == CAP


@pytest.mark.parametrize("free", ["release", "record"])
def test_freeing_more_than_is_reserved_is_refused(tmp_path: Path, free: str) -> None:
    budget = HardCapBudget(CAP, tmp_path / "ledger")
    budget.authorize(Decimal("0.10"))
    with pytest.raises(ValueError, match="reserved"):
        if free == "release":
            budget.release(Decimal("0.20"))
        else:
            budget.record(Decimal("0.20"), reservation=Decimal("0.20"))
    assert budget.remaining == Decimal("0.40")
    assert budget.spent == Decimal(0)
