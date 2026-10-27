# ADR 0007: Budget guard with hard cap

Status: Accepted (2026-10-27)

## Context

The console Spend Limit only sends a notification and does not cap spend.

## Decision

Show a dry-run cost estimate before any paid run, and enforce a hard cap (default 25 USD per run).

## Consequences

All spend goes through one budget guard, which runs dry-run by default. The cap is set with
`MAX_RUN_COST_USD`.
