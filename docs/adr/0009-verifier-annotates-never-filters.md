# ADR 0009: Verifier annotates, never filters

Status: Accepted (2026-10-27)

## Context

Matches come from deterministic code (ADR 0002). An optional Muse Spark frame check can give a
second opinion on a result.

## Decision

The optional Muse Spark frame check adds a note to a result and never removes one.

## Consequences

The result list depends only on the deterministic relation code. The frame check cannot hide a
match.
