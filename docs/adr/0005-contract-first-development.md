# ADR 0005: Contract-first development

Status: Accepted (2026-10-27)

## Context

The UI is built on mock data in phase 1, before the backend in phase 3, which must return the same
shapes as the mock.

## Decision

Write `contract/openapi.yaml` first. Build the UI on mock data that matches it.

## Consequences

`contract/openapi.yaml` is the single source of truth, with generated types and contract tests.
