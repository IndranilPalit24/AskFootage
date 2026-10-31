# AskFootage architecture

Status: the domain, ports, application, SQLite and JSON adapters, API (contract 1.3.0), CLIs and budget guard exist. Real SAM perception (`adapters/meta/sam.py`, currently empty) and the no-key demo mode (Gate 4) do not.

## Purpose

Ask a plain-English question about fixed-camera recorded footage. Get the matching clips on a
timeline, the objects outlined, and the measurements behind each match.

## Boundaries

Five boundaries, each held by one mechanism:

| # | Boundary | Mechanism |
|---|---|---|
| 1 | Vendor | Meta API calls sit behind ports, so the provider can be swapped. |
| 2 | Determinism | `domain/relations` is pure: no network, no files. |
| 3 | Contract | `contract/openapi.yaml` is the single source of truth, with generated types and contract tests. |
| 4 | Spend | `Budget` port and `HardCapBudget`; every paid call goes through a budgeted transport or perception. Dry-run by default for the spike, hard cap of 25 USD per run (ADR 0011). |
| 5 | Data and privacy | `.gitignore`, a fixed data layout, no footage or keys in git. |

A sixth rule: one timebase module converts frame numbers to seconds.

## Layering

```
interfaces -> application -> domain
```

- Dependencies point one way: interfaces -> application -> domain.
- Adapters implement ports.
- `domain` imports nothing from the other layers.
- `settings.py` is the only file that reads `.env`.
- An architecture test under `tests/architecture` fails the build on a layer breach.

## Module map

| Path | Role |
|---|---|
| `askfootage/domain` | Pure logic; imports nothing from other layers. `relations` (carrying, region traversal and entry, dwell), `stitching`, `vocabulary` (closed nouns and questions, `interpret_text`), `tracks`, `intervals`, `timebase`. |
| `askfootage/ports` | Interfaces the application depends on: `budget`, `language_model`, `perception`, `track_store`, `library_store`, `video_store`. |
| `askfootage/application` | Use cases through domain and ports: `search` and `search_relations` (answer from stored tracks, demo matcher as fallback), `ingest_video`, `add_concept`, `evaluate`, `budgeted_perception`, library, zones, cameras, clips. |
| `askfootage/adapters/meta` | Meta API calls behind ports: `client` and `transport`, `budget`, `record_replay`, `muse` (question parser). `sam.py` is empty until a real reply is seen. |
| `askfootage/adapters/fake` | Demo perception and a copying preparer for `--fake`. |
| `askfootage/adapters/sqlite` | The local library and track index (the API demo uses `data/demo.sqlite`). |
| `askfootage/adapters/media` | ffmpeg and ffprobe: the constant 5 fps, silent H.264 working copy. |
| `askfootage/adapters/storage` | Files under `data/<video_id>/`: `local_files` layout and `json_tracks` (`tracks.json`, ADR 0013). |
| `askfootage/interfaces/api` | HTTP API that serves `contract/openapi.yaml`. |
| `askfootage/interfaces/cli` | `ingest` (ingest, add-concept; `--fake`), `evaluate`, and `wiring`. |
| `web` | The UI, built first on mock data that matches the contract. |
| `contract` | `openapi.yaml`, the single source of truth for the API. |
| `tests` | Tests, including architecture tests and contract tests. |
| `scripts` | `api_spike.py` (`check-key`, `sam`; dry run unless `--yes`) and `make_synthetic_video.py`. |
| `demo` | Reserved for saved API recordings (empty today). |
| `labels` | Ground-truth labels for evaluation. |
| `docs` | Architecture notes and decision records (`docs/adr`). |

## Flows

Ingest (CLI today; the API route returns 503 until real perception exists):

```
video -> ffmpeg 5 fps copy -> per concept: budget.authorize -> perception -> stitch -> TrackStore
```

Search:

```
question -> QuestionParser (Muse, else keyword reader) -> closed Question
         -> per ready recording with stored tracks: stitch -> carrying | region_entry | dwell
         -> clips + proofs   (no tracks, no frame size or no relation: demo keyword matcher)
```

The default `create_app()` wires no track store, so the stored-track branch runs only when one is injected (ADR 0010). The CLI writes JSON tracks and the API reads SQLite; they are not connected yet.

## Data layout

```
videos/              originals (gitignored)
data/<video_id>/     5 fps copy, tracks.json from the CLI (gitignored)
data/demo.sqlite     API demo library, seeded on first start (gitignored)
data/ledger/         spend-ledger.jsonl written by the CLI budget (gitignored)
data/recordings/     spike replies kept for free replay (gitignored)
```

## Not building

- Microservices
- Queues
- Redis
- Postgres
- An ORM
- Login
- Multi-container Docker
- GraphQL
- Live streaming

## Phase map

| Phase | Exit criterion |
|---|---|
| 0 | Data contract, screens, synthetic video and mock data exist. |
| 1 | The UI runs on mock data. |
| 2 | API spike done. Gate: if the hosted API fails, switch to open weights. |
| 3 | The backend returns the same shapes as the mock. |
| 4 | The relation layer runs on real tracks, with thresholds tuned. |
| 5 | Muse Spark parses questions. |
| 6 | Evaluation done, plus a Muse Spark baseline. |
| 7 | UI polished, 3-minute demo video recorded, submission made. |

## Decision records

See `docs/adr/` for the accepted decisions behind this layout.
