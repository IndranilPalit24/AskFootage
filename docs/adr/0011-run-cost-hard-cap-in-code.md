# ADR 0011: Run cost hard cap in code

Status: Accepted (2026-10-31)

Builds on ADR 0007, which decided on a dry-run estimate and a hard cap of 25 USD per run.

## Context

Paid calls come from several places: SAM perception, Muse question parsing and the spike
script. A cap that each caller checks for itself would be bypassed by the first one that
forgets.

## Decision

- A `Budget` port (`ports/budget.py`) with `authorize(estimate)`, `record(cost, reservation)`
  and `release(reservation)`. Amounts are exact `Decimal`s, never floats. Spend plus
  in-flight reservations plus the estimate must stay at or under the cap, so concurrent
  callers cannot jointly pass it.
- `HardCapBudget` (`adapters/meta/budget.py`) holds the state under one lock and appends
  every send attempt to an append-only `spend-ledger.jsonl` (no bodies, headers or query strings).
- `BudgetedTransport` wraps any `Transport`: estimate, reserve, send, and record only after a
  2xx reply. A failure or non-2xx reply releases the reservation. It fails closed: no usable
  estimate means no send. Dry-run mode never sends and offers `preview()`.
- `application/budgeted_perception.py` applies the same authorize, call, record or release
  around each `detect_and_track` call.
- The cap is `MAX_RUN_COST_USD`, default 25, and is per run: each budget object starts at zero.
- SAM is billed 0.20 USD per 1,000 frames with a 50 frame minimum per request. A Muse parse
  reserves a flat 0.001 USD.

## Consequences

- No paid call can skip the guard if it is given a budgeted transport or perception.
- A new process starts with a fresh budget, so the cap is not a lifetime or daily limit.
  The ledger records spend but is not read back to restore it.
- The estimates are ours. If Meta changes its prices, the constants in `budget.py` must change.
- The CLI uses 0 USD per concept with `--fake` and a 0.10 USD placeholder otherwise,
  overridable with `--cost-per-concept`.
