# ADR 0012: Muse parsing with a deterministic fallback

Status: Accepted (2026-10-31)

## Context

A free-text question must become a structured one before any relation runs. A model can
understand loose wording, but it may be unavailable (no key, budget refused, network error)
and it may answer badly. The app and its demo must still work in those cases.

## Decision

`MuseQuestionParser` (`adapters/meta/muse.py`) asks `muse-spark-1.3` through any `Transport`
for one JSON object with `relation`, `subject`, `zone` and `min_seconds`. The first JSON
object in the reply (code fences and chatter tolerated) must pass `parse_question`, the
strict closed-schema check in `domain/vocabulary.py`, or it is discarded.

When the model cannot be used, or its reply is invalid, `interpret_text` (a keyword and
synonym reader in `domain/vocabulary.py`) answers and the result is marked `fallback`. If
that cannot read the question either, `QuestionNotUnderstoodError` is raised and the API
reports the question as not understood. The request is deterministic, so a replay transport
(`adapters/meta/record_replay.py`, keyed by a hash of path and body, never the key) can serve
tests and the future demo mode.

## Consequences

- No key is needed to ask a question. Quality is lower, but it is predictable and testable.
- The model can only choose from the closed vocabulary; it cannot widen what is searched.
- Every parse call is authorized by the budget guard (ADR 0011).
- The parser is tested against our own prompt and fake replies. It has not yet been checked
  against a real Muse reply, so wording that real replies add may still need handling.
- The SAM reply parser is a separate piece and is still waiting for a real reply.
