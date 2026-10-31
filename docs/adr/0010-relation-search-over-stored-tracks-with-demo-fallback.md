# ADR 0010: Relation search over stored tracks, with a demo fallback

Status: Accepted (2026-10-31)

## Context

Search began as a keyword matcher over seeded clips, which is enough to drive the UI but
proves nothing. The product promise is a match backed by measurements (see ADR 0002), and
real perception is not available yet, so the stored-track path cannot be the only path.

## Decision

`application/search_relations.py` answers a question from stored object tracks. It reads
the question into the closed schema, stitches the tracks of each ready recording, runs
`carrying`, `region_entry` or `dwell` from `domain/relations`, and turns each interval into
a clip plus a proof (relation, frames and seconds, track ids, measures, a few boxes). API
contract 1.3.0 returns the proofs in a new `proofs` array on the search response.

The keyword demo matcher stays as the fallback for a recording with no stored tracks, no
known frame size (saved zones are fractions, tracks are pixels), or a question with no
relation. Clips found that way have no proof. The two paths can mix in one answer.

## Consequences

- Real and demo footage can be searched together, and the UI shows proof only where it was measured.
- The default `create_app()` passes no track store, so a plain start still serves the demo matcher.
  Wiring a track store (and a frame-size source) into the app is separate work.
- The module imports only the domain and ports, so it is tested with fakes.
- The 1.3.0 change is additive: `proofs` is empty when every clip came from the demo matcher.
