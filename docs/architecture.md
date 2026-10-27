# AskFootage architecture

Status: skeleton only, no application code yet.

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
| 4 | Spend | One budget guard, dry-run by default, hard cap. |
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
| `askfootage/domain` | Pure logic, including relations and the timebase; imports nothing from other layers. |
| `askfootage/ports` | Interfaces the application depends on; adapters implement them. |
| `askfootage/application` | Use cases, called by interfaces; work through domain and ports. |
| `askfootage/adapters/meta` | Meta API calls (SAM 3.1, Muse Spark), behind ports. |
| `askfootage/adapters/sqlite` | The local `index.sqlite` index. |
| `askfootage/adapters/media` | Video handling, including the 5 fps copy. |
| `askfootage/adapters/storage` | Files under `data/<video_id>/`, including raw API responses. |
| `askfootage/interfaces/api` | HTTP API that serves `contract/openapi.yaml`. |
| `askfootage/interfaces/cli` | Command-line entry points. |
| `web` | The UI, built first on mock data that matches the contract. |
| `contract` | `openapi.yaml`, the single source of truth for the API. |
| `tests` | Tests, including architecture tests and contract tests. |
| `scripts` | One-off scripts, such as the API spike and the synthetic video. |
| `demo` | Demo material. |
| `labels` | Ground-truth labels for evaluation. |
| `docs` | Architecture notes and decision records (`docs/adr`). |

## Data layout

```
videos/              originals (gitignored)
data/<video_id>/     5 fps copy, raw API responses, index.sqlite (gitignored)
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
