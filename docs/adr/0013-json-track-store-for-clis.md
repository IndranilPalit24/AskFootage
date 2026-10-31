# ADR 0013: JSON track store for the command-line tools

Status: Accepted (2026-10-31)

## Context

The `ingest` and `evaluate` commands must work on a folder of files, without opening the
SQLite library or running the API. The `TrackStore` port already hides where tracks live.

## Decision

`JsonTrackStore` (`adapters/storage/json_tracks.py`) implements `TrackStore` as one file per
video, `<DATA_DIR>/<video id>/tracks.json`. The file maps each concept to its tracks; a track
is `{"track_id", "points": [[frame, x1, y1, x2, y2], ...]}`. Writes go to a temporary file and
then replace the old one, so a crash never leaves half a file. `cli/wiring.py` builds the
services from `Settings`; it never reads the environment itself.

`--fake` swaps in `DemoPerception` and a copying preparer: no key, no ffmpeg, no spend.
Without `--fake` the real perception is not yet available, so the command exits with a
"not configured" error.

## Consequences

- The CLIs, tests and evaluation run with no database and no key.
- There are two track stores (JSON for the CLIs, SQLite for the API). They are not
  synchronised, so tracks ingested by the CLI do not appear in the API until one is wired to the other.
- The JSON store has no locking; it is meant for one command at a time.
