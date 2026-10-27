# ADR 0001: Local-first SQLite index

Status: Accepted (2026-10-27)

## Context

Meta provides no database, and its Files API is temporary upload storage.

## Decision

The index is kept in local SQLite. Videos stay on disk and are not stored in the database.

## Consequences

Each video's index lives at `data/<video_id>/index.sqlite`, next to its 5 fps copy and raw API
responses. Both `videos/` and `data/` are gitignored, so footage and indexes stay out of git.
