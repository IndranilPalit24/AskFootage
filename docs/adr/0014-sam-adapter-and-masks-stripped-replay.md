# ADR 0014: SAM adapter, masks stripped from saved replies, offline replay

Status: Accepted (2026-11-01)

## Context

The real SAM 3.1 replies for two clips were saved by the API spike (about $0.06 spent). They
are 0.2 to 4 MB each, almost all of it mask data the product never uses. Judges and CI must
be able to run everything with no key and no network.

## Decision

- `adapters/meta/sam.py` implements the perception port. It reads the server-sent-events
  reply (frames are 0-based indexes into the 5 fps copy, seconds = frame / 5; several objects
  on one frame share a line; an empty text means nothing found) and refuses unknown, failed
  or truncated streams with a short, fixed message. Masks are skipped, never decoded or kept.
- `RecordingTransport` takes an optional `redact` hook; `redact_sam_reply` strips masks from a
  reply when it is saved. The recording is still named by the fingerprint of the request, so
  `ReplayTransport` finds it. Saved replies live in `demo/sam/` (each under 100 KB) with a
  manifest of clips, prompts, fingerprints and the prepared video's hash.
- A vocabulary noun maps to the words SAM was asked: "cardboard box" is sent as "box" and the
  track keeps the label "cardboard box".
- An already prepared video is copied, not re-encoded (`PreparedCopyPreparer`), so the upload's
  content hash, and with it the fingerprint, does not change.
- The one relation threshold that missed real footage, `carry_motion_tolerance`, moved from
  0.5 to 0.75. A person's box from SAM changes shape with posture and with the feet leaving
  the frame, so its centre jitters; at 0.5 and 0.6 the confirmed carry in clip2 is missed, at
  0.7 and above it is found. Labels were not touched.
- A noun that was searched and found nothing is a result: the SQLite store keeps a "searched"
  marker (schema v4), so search judges the recording from its tracks instead of reporting the
  noun as not indexed.
- A clip found from tracks gets an evidence snapshot: the frame where the carry began, the
  object's box in red and the person's in neutral grey, made with ffmpeg and kept under
  `data/` (never committed, since a frame can show a face). Contract 1.4.0.

## Consequences

- No face detection or identity feature is added (ADR 0008); a snapshot is a frame with boxes.
- `leaves_room` has no rule and no zone, so it is reported as not evaluable, not invented.
- Real run quirks are kept as they are: SAM may give one person several ids; stitching joins
  only fragments that are close in time and space.
