# ADR 0004: Five fps copy and chunking

Status: Accepted (2026-10-27)

## Context

SAM track IDs are stable only while an object stays in view. The API allows 15,000 frames per
request and 16 tracked objects per frame.

## Decision

Re-encode each video to a 5 fps constant-frame-rate copy. Split long videos into overlapping
chunks and match track IDs on the overlaps.

## Consequences

The 5 fps copy is stored under `data/<video_id>/`. One timebase module converts frame numbers to
seconds.
