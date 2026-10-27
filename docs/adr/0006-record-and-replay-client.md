# ADR 0006: Record-and-replay client

Status: Accepted (2026-10-27)

## Context

Calls to the Meta API need an API key, and paid runs cost money.

## Decision

The Meta client can record API responses and replay them without a key.

## Consequences

Demo mode and fast tests need no API access.
