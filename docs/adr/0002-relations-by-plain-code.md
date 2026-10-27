# ADR 0002: Relations by plain code

Status: Accepted (2026-10-27)

## Context

AskFootage shows the measurements behind each match.

## Decision

Carrying, region traversal and dwell are resolved by deterministic code, not by models. That code
lives in `domain/relations`, which is pure: no network, no files.

## Consequences

Every match is explainable by its numbers.
