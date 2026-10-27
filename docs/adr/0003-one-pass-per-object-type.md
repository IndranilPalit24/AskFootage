# ADR 0003: One pass per object type

Status: Accepted (2026-10-27)

## Context

SAM 3.1 accepts one concept per request. Comma-separated lists return zero matches.

## Decision

Send one SAM request per object type. Save raw responses to disk before parsing them.

## Consequences

Each object type is a separate pass over the video. A parsing error can be fixed and re-run from
the saved responses without calling the API again.
