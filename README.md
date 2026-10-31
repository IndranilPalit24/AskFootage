# AskFootage

**Ask your footage. Get the clip and the proof.**

AskFootage lets you ask a plain-English question about recorded camera footage, such as *"was a pallet left blocking the exit?"* or *"show me anyone carrying a box through the loading door"*. It returns the matching clips, marks each occurrence on a timeline, outlines the objects involved, and shows the measurements that justify every match.

Built by Team **EdgeCase** (solo, Indie track) for the **Meta Global AI Developer Hackathon**, Oct 27 to Nov 4, 2026, using **SAM 3.1** and **Muse Spark** through the Meta Model API.

> **Status: work in progress (branch `feature/app-v1`).** The relation rules, the API (contract 1.3.0), the web UI on demo data, the ingest and evaluate command lines and the spend cap exist. Real perception does not: there is no working SAM 3.1 adapter yet, so nothing is indexed from a live model. Rows marked *Not done* below are not built.

| Component | Status |
|---|---|
| Relation layer: carrying, region entry, dwell (`domain/relations.py`) | Done, thresholds not yet tuned on real footage |
| Track stitching across gaps (`domain/stitching.py`) | Done (pure code, defaults not tuned) |
| Question vocabulary and keyword reader (`domain/vocabulary.py`) | Done |
| Spend cap: `Budget` port, `HardCapBudget`, `BudgetedTransport` | Done |
| 5 fps video preparation (ffmpeg) | Done |
| Ingest and add-concept use cases, `ingest` CLI | Done, `--fake` perception only |
| Search over stored tracks, with demo keyword fallback | Done in code; the default `create_app()` does not wire tracks (see below) |
| Muse Spark question parser, keyword fallback, replay transport | Done; not yet checked against a real reply |
| Evaluation scoring and `evaluate` CLI | Done; no labelled footage yet, so no results |
| Searchable index (SQLite: library, zones, clips, tracks) | Done |
| HTTP API, contract 1.3.0 (includes `proofs`) | Done |
| Web UI: player, timeline, overlay, zone editor | Built on demo data |
| SAM 3.1 adapter (`adapters/meta/sam.py`) | **Not done.** The file is empty and its reply parser waits for a real SAM reply |
| Real indexing from the API (`POST /api/recordings/{id}/index`) | **Not done.** Answers 503 `indexing_not_configured` |
| No-key demo mode from recordings in `demo/` | **Not done** (Gate 4). `demo/` is empty |
| Held-out accuracy results and Muse Spark baseline | **Not done** |

## Contents

1. [What it does](#what-it-does)
2. [The problem](#the-problem)
3. [How it works](#how-it-works)
4. [Tech stack](#tech-stack)
5. [Getting started](#getting-started)
6. [Configuration and secrets](#configuration-and-secrets)
7. [Cost and API limits](#cost-and-api-limits)
8. [Evaluation](#evaluation)
9. [Known limitations](#known-limitations)
10. [Privacy and responsible use](#privacy-and-responsible-use)
11. [Project layout](#project-layout)
12. [Built during the hackathon](#built-during-the-hackathon)
13. [License](#license)

## What it does

You give AskFootage a video from a **fixed camera**. It watches the video once, builds an index of every object it finds and where each one moves, and then answers questions about that index.

**Example questions**

- "Was a pallet left blocking the exit?"
- "Show me anyone carrying a box through the loading door."
- "When did someone stand in the doorway for more than 10 seconds?"

**What you get back for each question**

- The matching clips, ranked.
- A timeline with each occurrence marked.
- The objects involved, outlined on the video as it plays.
- An **evidence panel** with the numbers behind each match, such as how long the object stayed in the zone, or how steady its position was relative to the person.

**Relations it can resolve**

| Relation | Meaning | Example |
|---|---|---|
| Carrying | A person holds an object that moves with them | A person walks out with a box |
| Region traversal | Something enters and leaves a zone you drew | A person crosses the doorway |
| Dwell | Something stays in a zone longer than a set time | A pallet sits in the exit zone |

**Objects it looks for (current vocabulary):** person, cardboard box, bag, crate. More can be added later; each new object type costs one extra processing pass over the video

AskFootage does **not** identify who anyone is. It has no face recognition and no names.

## The problem

Hours of camera footage are effectively unsearchable. Finding one moment means someone scrubs through the recording by hand. The usual alternatives are tagging footage manually, which rarely happens at scale, or training an object detector, which takes months of labelling and only recognises the categories it was trained on.

AskFootage uses an open-vocabulary segmentation model instead, so the objects to look for are chosen with short text phrases and no training.

## How it works

```
video ──ffmpeg──> 5 fps copy ──> overlapping chunks
                                      │
                       one SAM 3.1 request per (chunk × object type)
                                      │
                    raw responses saved to disk, then parsed
                                      │
                 track stitching (match IDs across chunk overlaps)
                                      │
                                SQLite index
                                      │
question ──> Muse Spark parses it into a fixed structure
                                      │
                 relation resolver (plain code, no model)
                                      │
            ranked events ──> optional Muse Spark check ──> UI
```

### 1. Perception: SAM 3.1

SAM 3.1 runs through the Meta Model API and returns a box, a mask and a tracking ID for every object matching a short text phrase. The API accepts **one object type per request**, so each type is a separate pass over the video. Raw responses are saved before anything is parsed, so a parsing bug never costs a second API run.

### 2. The index

Everything the model found is stored locally in one SQLite file: each track, its boxes per frame, confidence values, and the zones you drew. Questions are then answered from the index and do not re-run the vision model. Looking things up in the index takes milliseconds. A whole question also includes one language-model call to interpret it, so expect seconds end to end.

### 3. Relation resolution: plain code

Neither model decides what "carrying" means. That is ordinary, testable code (`askfootage/domain/relations.py`), so results are reproducible and every match can be explained with numbers. All numbers are named fields of `Thresholds`, with defaults for 5 fps footage that are **not yet tuned on real footage**:

- **Carrying:** an object counts as carried when, step after step, its centre is inside the person's box grown by 15 percent, at least 50 percent of its area is inside that grown box, and both the person and the object actually move (at least 2 percent of the person's height per frame) by nearly the same displacement (difference at most half the person's). The run must last at least 10 frames (2 s), agree on at least 60 percent of its steps, and may pause for at most 3 frames. A box at rest beside a person, or a person walking past a box, is not carried. A person who stands still while holding something is also not detected, because there is no movement to compare.
- **Region entry (`in_zone`):** a track's foot point (bottom-centre of its box) is inside a polygon you drew. The interval runs from the first frame inside to the last, and leaving or going undetected for at most 3 frames does not split it. `region_entry` keeps only tracks that were first seen outside the zone; `region_traversal` keeps all.
- **Dwell:** a stay inside a zone of at least a minimum number of frames (taken from the question, 5 seconds by default), with the same gap tolerance.

**Stitching** (`domain/stitching.py`): when perception loses an object and returns it under a new ID, fragments with the same label are joined if they are at most 15 frames (3 s) apart and the box centre moved no more than 25 percent of the box size per elapsed frame. `merge_intervals` joins adjacent intervals of the same relation.

### 4. Query interpretation: Muse Spark

Muse Spark (`muse-spark-1.3`, in `askfootage/adapters/meta/muse.py`) turns a question into a fixed structure and nothing else. The reply must be a JSON object that passes the strict schema check in `domain/vocabulary.parse_question`, or it is discarded. It may only pick object types from the indexed vocabulary, one of the supported relations, and a zone from your named list. Anything else is reported as unsupported, or as "needs indexing" with a cost estimate.

```json
{
  "relation": "dwell",
  "subject": "crate",
  "zone": "exit door",
  "min_seconds": 10
}
```

**Fallback.** If there is no key, the budget refuses, the call fails or the reply is invalid, a deterministic keyword reader (`vocabulary.interpret_text`, which maps words such as "holding", "parcel" or "lingers" to the closed relations and nouns) answers instead and the result is marked as fallback. If neither can read the question, it is reported as not understood. Tests and the future demo mode run the parser over a replay transport that answers from saved recordings and never touches the network. See [ADR 0012](docs/adr/0012-muse-parsing-with-deterministic-fallback.md).

### 5. Search: stored tracks first, demo matcher as fallback

`askfootage/application/search_relations.py` reads the question, then for each ready recording with stored tracks it stitches the tracks and runs `carrying`, `region_entry` or `dwell`. Each interval becomes a clip plus a proof (relation, frames and seconds, track ids, measures, a few boxes to draw), returned in the `proofs` array added in API contract 1.3.0. A recording with no stored tracks, no frame size (needed to turn saved zones into pixels), or a question with no relation uses the older demo keyword matcher over stored clips, and those clips have no proof. The default `create_app()` wires no track store, so a plain `uvicorn` start still serves the demo matcher; the stored-track path runs when tracks and a frame-size source are passed in (as the API tests do). Nothing connects the CLI's JSON files to the API yet. See [ADR 0010](docs/adr/0010-relation-search-over-stored-tracks-with-demo-fallback.md).

### 6. Optional verification *(Not done)*

Muse Spark can look at a few frames from each candidate result and say whether it agrees. This is **shown beside the result and never silently removes one**, and every verdict is logged so you can see what it disagreed with.

## Tech stack

| Part | Choice |
|---|---|
| Vision model | SAM 3.1 (`sam-3.1`) via Meta Model API |
| Language model | Muse Spark 1.3 (`muse-spark-1.3`) via Meta Model API |
| Backend and relation logic | Python 3.11+ with FastAPI |
| Index | SQLite |
| Video preparation | ffmpeg |
| Web UI | React, Vite, TypeScript |
| Tests | pytest (Python), vitest (web) |

## Getting started

### Prerequisites

Install these and check each one from a terminal:

| Tool | Check |
|---|---|
| Git | `git --version` |
| Python 3.11 or newer | `python --version` |
| Node.js (LTS), for the web UI | `node --version` |
| ffmpeg, on your PATH | `ffmpeg -version` |

Tested on Python 3.14.4 (Windows).

### 1. Clone

```
git clone https://github.com/<your-username>/askfootage.git
cd askfootage
```

### 2. Create a virtual environment

A virtual environment is a private folder of Python packages for this project only.

Windows (PowerShell):

```
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks the script, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` once in that window and try again.

macOS or Linux:

```
python3 -m venv .venv
source .venv/bin/activate
```

Always call the virtual environment's own programs, as below. A bare `python` may be a different install (this project was built on a system Python 3.14 with an older FastAPI), so the commands name `.venv\Scripts\python.exe`. On macOS or Linux use `.venv/bin/python`.

### 3. Install

```
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
cd web
npm install
cd ..
```

### 4. Run the tests

```
.venv\Scripts\python.exe -m pytest
cd web
npm test
npm run typecheck
```

The Python tests need no API key, no network and no real video. Some tests need ffmpeg on your PATH.

### 5. Run the API and the web UI (demo data)

In one terminal:

```
.venv\Scripts\python.exe -m uvicorn askfootage.interfaces.api.app:create_app --factory --port 8000
```

There is no module-level `app`, so `--factory` is required. On first start it creates `data/demo.sqlite` from `contract/examples/demo-seed.json`. The demo clip is `videos/clip1.mp4`, which is gitignored: put your own clip there. The interactive API docs are at `http://localhost:8000/api/docs`.

In a second terminal:

```
cd web
npm run dev
```

Open the address it prints (the API only accepts requests from `http://localhost:5173`). Questions here are answered by the keyword demo matcher over seeded clips, so this shows the interface and the evidence panel, not real perception.

### 6. Try the ingest and evaluate command lines (no key, no spend)

`--fake` uses a deterministic made-up perception (one person walking right with one object moving alongside), so the carrying rule fires. It needs no key and no ffmpeg and costs nothing. It does need a video file to exist, because the "preparation" step copies it.

```
.venv\Scripts\python.exe scripts\make_synthetic_video.py data\synthetic.mp4
.venv\Scripts\python.exe -m askfootage.interfaces.cli.ingest ingest vid-1 data\synthetic.mp4 --fake
.venv\Scripts\python.exe -m askfootage.interfaces.cli.ingest add-concept vid-1 crate --fake
.venv\Scripts\python.exe -m askfootage.interfaces.cli.evaluate labels\demo-1.json
```

- `make_synthetic_video.py` needs ffmpeg and writes a 6 second clip of a disc carrying a square into a shaded region. Add `--force` to overwrite.
- Tracks are written to `data/vid-1/tracks.json` (JSON, one file per video). Without `--fake`, `ingest` exits with a "not configured" error, because the real perception does not exist yet.
- `ingest` defaults to the concepts `person` and `cardboard box`; repeat `-c` for others. Re-running skips concepts already stored unless `--force`.
- `evaluate` scores the relations found in the stored tracks against a hand-written labels file (format in [labels/README.md](labels/README.md)) and prints precision, recall, f1 and IoU per relation. No labels file ships yet, so write one first.

### 7. API spike: check your key and see what SAM returns

Needs your own key in `.env` (see below). Every command is a dry run until you add `--yes`.

```
.venv\Scripts\python.exe -m scripts.api_spike check-key
.venv\Scripts\python.exe -m scripts.api_spike check-key --yes
.venv\Scripts\python.exe -m scripts.api_spike sam --video data\synthetic.mp4 --object person --duration-seconds 6
.venv\Scripts\python.exe -m scripts.api_spike sam --video data\synthetic.mp4 --object person --duration-seconds 6 --yes
```

`check-key` sends one tiny request and prints PASS or FAIL with a hint. `sam` prints the estimated cost first and refuses if it is above `--max-cost-usd` or `MAX_RUN_COST_USD`. A live run saves each successful reply under `data/recordings`, so repeating the same command replays it free. The SAM reply is printed raw and unparsed: **the SAM reply parser (`adapters/meta/sam.py`) waits for a real reply and does not exist yet.**

### 8. Run on the full pipeline *(Not done)*

Real indexing needs the SAM adapter, which is not built, so there is no honest "index my video" command yet. The intended flow is the `ingest` command without `--fake`, then search from the UI.

### 9. Demo mode without a key *(Not done, Gate 4)*

The plan is a short sample clip with its model responses saved in `demo/`, replayed through the record-and-replay transport so judges can run it without a key. `demo/` is empty today and `ASKFOOTAGE_DEMO` is read by the settings but not yet used to switch on a replay mode. Today's no-key experience is step 5 (seeded demo data) and step 6 (`--fake`).

## Configuration and secrets

Settings come from environment variables, loaded from a local `.env` file. These are read by `askfootage/settings.py`, the only module that reads the environment.

| Variable | Purpose | Secret? |
|---|---|---|
| `META_API_KEY` | Your Meta Model API key | **Yes** |
| `META_API_BASE_URL` | API address, as given in the Meta Model API docs | No |
| `MAX_RUN_COST_USD` | Hard cap in US dollars for one run (default 25) | No |
| `DATA_DIR` | Where videos, raw responses and the index live | No |
| `ASKFOOTAGE_DEMO` | Reserved for replay demo mode (Gate 4); no effect yet | No |

**Rules**

- `.env` is listed in `.gitignore` and must never be committed.
- `.env.example` holds variable names with **empty values** only.
- The key is read by the backend only and is never sent to the browser.
- If a key is ever committed or pasted somewhere public, revoke it in the Meta console and create a new one. Deleting it from a later commit does not remove it from git history.

## Cost and API limits

Facts below come from Meta's documentation (links at the end).

| Item | Value |
|---|---|
| SAM 3.1 video price | $0.20 per 1,000 frames, minimum 50 frames per request |
| Frames per request | Up to 15,000 |
| Objects tracked per frame | Up to 16 |
| Object types per request | One. Comma-separated lists return no matches. |
| Muse Spark 1.3 price | $1.25 per million input tokens, $4.25 per million output tokens |

Sampling at 5 frames per second gives 300 frames per minute of video:

- **$0.06** per object type per minute of video.
- A **30-minute video with 4 object types costs about $7.20.**
- Adding one more object type later costs about $1.80 per 30 minutes of video.

Spend is enforced in code, not only shown. Every paid call goes through the budget guard: it reserves the estimated cost before sending, records it only after a 2xx reply, fails closed when it cannot estimate a cost, and refuses anything that would pass `MAX_RUN_COST_USD` ($25 by default). Each send attempt is appended to a spend ledger (`spend-ledger.jsonl`, with no bodies, headers or keys). The cap is per run (one budget object), not a lifetime total; the Meta console Spend Limit only sends a notice. The CLI `--fake` mode uses a $0 cost per concept; without it, the CLI assumes $0.10 per concept unless you pass `--cost-per-concept`. See [ADR 0011](docs/adr/0011-run-cost-hard-cap-in-code.md).

## Evaluation

The scoring code exists (`askfootage/application/evaluate.py`); accuracy will be measured against hand-labelled ground truth on footage filmed for this project, following a written script of what happens at what time.

- A result counts as correct when its time range overlaps a labelled event by at least a set threshold.
- Thresholds are tuned on one set of clips and reported on a **separate held-out set**.
- Results report raw counts (true positives, false positives, missed events), not only percentages, because the test set is small.
- Scripted footage and any uncontrolled footage are reported separately.
- A baseline will compare AskFootage with asking Muse Spark the same questions directly on the raw video.

**Results: not yet available.** They will be published here after evaluation, with the failure cases.

## Known limitations

- **Fixed camera only.** Zones are drawn in image coordinates, so a moving camera breaks them.
- **Tracking IDs are not stable forever.** Meta's docs say IDs hold only while an object stays in view. An object hidden behind something can come back under a new ID. `stitch_tracks` joins nearby fragments of the same label, but its limits (3 s, 25 percent shift) are untuned guesses.
- **16 objects per frame.** Crowded scenes are truncated by the API.
- **5 frames per second.** Start and end times are accurate to roughly a third of a second.
- **Carrying can be confused** by a box hidden behind a body, a bag on a shoulder, two people carrying one item, an overhead camera, or a load being pushed on a trolley (known gap), and a person who stands still while holding something.
- **Vocabulary must be indexed.** Asking about an object type that has not been indexed returns a "needs indexing" message with a cost, not a guess.
- **Synonyms matter.** "Box" and "carton" can be detected differently, so the vocabulary keeps an alias list.
- **Results are leads, not verdicts.** They need a person to review them.

## Privacy and responsible use

- AskFootage has **no face recognition and no identification** of anyone.
- The demo footage is filmed by the author with the consent of everyone in it.
- Indexing uploads video to Meta's servers. Meta's docs say uploaded files do not expire by default, so the app sets a short expiry and deletes the upload after indexing. Meta may retain inputs and outputs under its standard terms, so read Meta's data-handling terms before uploading anyone's image.
- The index, the questions you ask and the results stay on your machine. Interpreting a question sends the text to Muse Spark. If verification is switched on, a few frames from each candidate are sent as well.
- Do not use this to make decisions about people without human review.
- Only use footage you have the right to use.

## Project layout

*Folder purposes are in [docs/architecture.md](docs/architecture.md); `data/`, `videos/` and `.env` are not committed.*

```
AskFootage/
  .github/              CI workflows (tests, secret scan)
    workflows/
  .vscode/              editor settings (LF line endings)
  askfootage/           backend: domain, ports, application, adapters, interfaces
    adapters/
      fake/             demo perception for --fake
      media/
      meta/
      sqlite/
      storage/
    application/
    domain/
    interfaces/
      api/
      cli/
    ports/
  contract/             openapi.yaml, the single source of truth for the API
    examples/
  demo/                 demo material
  docs/                 architecture notes and decision records
    adr/
    wireframes/
  labels/               ground-truth labels for evaluation
  scripts/              one-off scripts, such as the API spike and the synthetic video
  tests/                tests, including architecture tests and contract tests
    architecture/
    contract/
    e2e/
    fixtures/
    unit/
  web/                  the UI, built first on mock data that matches the contract
    src/
      api/
        generated/
      components/
      features/
        evidence/
        indexing/
        player/
        search/
        timeline/
        zones/
      hooks/
      styles/
  .gitattributes
  .gitignore
  pyproject.toml
  README.md
  requirements-dev.txt
  requirements.txt
```

## Built during the hackathon

Everything in this repository was created between **Oct 27 and Nov 4, 2026** for the Meta Global AI Developer Hackathon, starting from an empty repository. The commit history shows what was written and when. No code from earlier projects is included.

The only external components are the models and API of Meta Model API and standard open-source libraries listed in `requirements.txt` and `web/package.json`.

## References

- [Pricing and rate limits, Meta Model API](https://dev.meta.ai/docs/pricing-rate-limits)
- [Segmenting with prompts, Meta Model API](https://dev.meta.ai/docs/sam/segmenting)
- [Reading segmentation output, Meta Model API](https://dev.meta.ai/docs/sam/reading-segmentation)
- [File handling, Meta Model API](https://dev.meta.ai/docs/file-handling)
