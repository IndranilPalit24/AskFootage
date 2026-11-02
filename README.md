# AskFootage

**Ask your footage. Get the clip and the proof.**

[![tests](https://github.com/IndranilPalit24/AskFootage/actions/workflows/tests.yml/badge.svg)](https://github.com/IndranilPalit24/AskFootage/actions/workflows/tests.yml)

AskFootage lets you ask a plain-English question about recorded camera footage, such as *"was a pallet left blocking the exit?"* or *"show me anyone carrying a box through the loading door"*. It returns the matching clips, marks each occurrence on a timeline, outlines the objects involved, and shows the measurements that justify every match.

Built by Team **EdgeCase** (solo, Indie track) for the **Meta Global AI Developer Hackathon**, Oct 27 to Nov 4, 2026, using **SAM 3.1** and **Muse Spark** through the Meta Model API.

> **Status: hackathon build.** SAM 3.1 perception works end to end on two real clips, and anyone can run it with **no key**: the model's recorded replies are in `demo/sam`, and one command replays them (see [Quick start](#quick-start-no-key-demo)). Live indexing of whole new recordings from the API, question reading by Muse Spark in the API, and held-out accuracy results are not built. Rows marked *Not done* below are not built.

| Component | Status |
|---|---|
| Relation layer: carrying, region entry, dwell (`domain/relations.py`) | Done, thresholds not yet tuned on real footage |
| Track stitching across gaps (`domain/stitching.py`) | Done (pure code, defaults not tuned) |
| Question vocabulary and keyword reader (`domain/vocabulary.py`) | Done |
| Spend cap: `Budget` port, `HardCapBudget`, `BudgetedTransport` | Done |
| 5 fps video preparation (ffmpeg) | Done |
| Ingest and add-concept use cases, `ingest` CLI | Done; the CLI uses `--fake` perception only. The real clips are ingested by `scripts.ingest_real_clips` (replayed SAM) |
| Search over stored tracks, with demo keyword fallback | Done; wired for the two real clips in `askfootage.interfaces.real_clips`. The default `create_app()` still serves the seeded demo matcher |
| Muse Spark question parser, keyword fallback, replay transport | Parser built (`adapters/meta/muse.py`); **not wired into the API**, which reads questions with the keyword reader. Not checked against a real reply |
| Evaluation scoring and `evaluate` CLI | Done; on the two labelled clips the carried box is found at 1.2 to 4.8 s against 1 to 5 s labelled (`labels/`); no held-out set yet |
| Any-object search (`POST /api/concepts`, "Not searched yet" panel) | Done: shows an estimated cost, runs one pass per object after you confirm, behind the spend cap; replays saved results with no key |
| Searchable index (SQLite: library, zones, clips, tracks) | Done |
| HTTP API, contract 1.7.0 (proofs, recording boxes, evidence snapshots, any-object search) | Done |
| Web UI: sign-in, Find Footage, Cameras, Zones, Saved Clips, Activity Log preview, player with timeline and red box overlay | Built; the real-clips demo plays both clips with the overlay |
| SAM 3.1 adapter (`adapters/meta/sam.py`) | Done. Parses real replies; masks are dropped from saved replies; replays offline from `demo/sam` |
| Real indexing from the API (`POST /api/recordings/{id}/index`) | **Not done.** Answers 503 `indexing_not_configured` |
| No-key demo mode from recordings in `demo/sam` | Done: `python -m scripts.run_demo`. Needs your own `videos/clip1.mp4` and `clip2.mp4` (not in the repository) |
| Held-out accuracy results and Muse Spark baseline | **Not done** |

## Highlights

- **Ask in plain English.** Type what you are looking for, such as *"person carrying a box"*, and get the matching clips.
- **Every match comes with its proof:** the relation, the time range, the measurements behind it, and a red box that follows the object on the playing video.
- **Index once, search for free.** The vision model runs once per object type; questions are then answered from a local SQLite index with no new paid call.
- **Try it with no API key.** The model's recorded replies ship in `demo/sam`, and one command replays them ([Quick start](#quick-start-no-key-demo)).
- **Cost is capped in code.** Every paid call goes through a budget guard with a hard cap, default $25 per run ([Cost and API limits](#cost-and-api-limits)).
- **No face recognition, no identity features** ([ADR 0008](docs/adr/0008-no-identity-or-face-recognition.md)).
- **Contract-first and tested:** one OpenAPI contract for the UI and the API, with Python and web test suites.

## Screenshots

Three screens show the flow from sign-in to a match with its proof.

### 1. Sign-in page
<img width="1907" height="917" alt="SigninPage" src="https://github.com/user-attachments/assets/fdb22e53-6c76-4494-8c06-7b138bfd2dc0" />


### 2. Find Footage page
<img width="1906" height="922" alt="FindFootagePage" src="https://github.com/user-attachments/assets/337aa366-cc79-4928-9110-a96b67ccfb64" />


### 3. A match with its proof: "someone carrying a box"

<img width="1905" height="921" alt="FindingFootage" src="https://github.com/user-attachments/assets/16647706-44a7-4424-8835-4a806368593e" />


## Author

Built by **Indranil Palit** as Team **EdgeCase** (solo), for the Meta Global AI Developer Hackathon. Source: [github.com/IndranilPalit24/AskFootage](https://github.com/IndranilPalit24/AskFootage).

## Contents

1. [Highlights](#highlights)
2. [Screenshots](#screenshots)
3. [Author](#author)
4. [Quick start (no-key demo)](#quick-start-no-key-demo)
5. [What it does](#what-it-does)
6. [The problem](#the-problem)
7. [How it works](#how-it-works)
8. [Tech stack](#tech-stack)
9. [Getting started](#getting-started)
10. [Configuration and secrets](#configuration-and-secrets)
11. [Cost and API limits](#cost-and-api-limits)
12. [Evaluation](#evaluation)
13. [Demo data](#demo-data)
14. [Known limitations](#known-limitations)
15. [Privacy and responsible use](#privacy-and-responsible-use)
16. [Project layout](#project-layout)
17. [Built during the hackathon](#built-during-the-hackathon)
18. [Feedback](#feedback)
19. [References](#references)

## Quick start (no-key demo)

You need Python 3.11+, Node.js, ffmpeg on PATH, a virtual environment with the requirements installed ([Getting started](#getting-started) steps 1 to 3), and the two demo clips at `videos/clip1.mp4` and `videos/clip2.mp4`. The clips are not in the repository (`videos/` is git-ignored). **No Meta key, no `.env` and no network are needed.**

Terminal 1, from the project root (PowerShell):

```
.venv\Scripts\python.exe -m scripts.run_demo
```

Terminal 2:

```
cd web; $env:VITE_API_URL='http://localhost:8000'; npm run dev
```

Open `http://localhost:5173`, pick 30 Oct 2026, and ask *person carrying a box*. You get clip2 with the red box overlay on the playing video, the proof and a snapshot; clip1 is not returned.

What `scripts.run_demo` does: checks both clips and ffmpeg exist (it prints what is missing and exits with code 2 if not), makes the 5 fps copies in `data/prepared/`, stores the tracks from the saved replies in `data/real/library.sqlite` (first run only), then serves the API on port 8000 (`--port N` changes it; use the same port in `VITE_API_URL`). If the prepared bytes differ from the ones the replies were recorded for (a different clip file or ffmpeg build), it stops and says so with a hint. The same steps can be run one by one:

```
.venv\Scripts\python.exe -m scripts.prepare_clips
.venv\Scripts\python.exe -m scripts.ingest_real_clips
.venv\Scripts\python.exe -m uvicorn askfootage.interfaces.real_clips:create_app --factory --port 8000
```

**Real mode (your own key, spends money).** Put your key in `.env` (see [Configuration and secrets](#configuration-and-secrets)), then check it and record new replies with `scripts.api_spike` and `scripts.record_sam_demo` (section 7 below; every command is a dry run until you add `--yes`). The API does not index new footage yet, so there is no one-command real mode.

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

SAM 3.1 runs through the Meta Model API and returns a box, a mask and a tracking ID for every object matching a short text phrase. It finds the objects and tracks them in the footage, **once per object type** (the API accepts one type per request, so each type is a separate pass over the video). The two real clips were run once with a key; the replies were saved (masks removed, which the product never uses) in `demo/sam`, so anyone can run the demo with **no key**: a replay transport answers every request from those files and nothing is sent to Meta. Raw responses are saved before anything is parsed, so a parsing bug never costs a second API run.

### 2. The index

Everything the model found is stored locally in one SQLite file: each track, its boxes per frame, confidence values, and the zones you drew. Questions are then answered from the index and do not re-run the vision model. Looking things up in the index takes milliseconds. A whole question also includes one language-model call to interpret it, so expect seconds end to end.

### 3. Relation resolution: plain code

Neither model decides what "carrying" means. That is ordinary, testable code (`askfootage/domain/relations.py`), so results are reproducible and every match can be explained with numbers. All numbers are named fields of `Thresholds`, with defaults for 5 fps footage that are **not yet tuned on real footage**:

- **Carrying:** an object counts as carried when, step after step, its centre is inside the person's box grown by 15 percent, at least 50 percent of its area is inside that grown box, and both the person and the object actually move (at least 2 percent of the person's height per frame) by nearly the same displacement (difference at most half the person's). The run must last at least 10 frames (2 s), agree on at least 60 percent of its steps, and may pause for at most 3 frames. A box at rest beside a person, or a person walking past a box, is not carried. A person who stands still while holding something is also not detected, because there is no movement to compare.
- **Region entry (`in_zone`):** a track's foot point (bottom-centre of its box) is inside a polygon you drew. The interval runs from the first frame inside to the last, and leaving or going undetected for at most 3 frames does not split it. `region_entry` keeps only tracks that were first seen outside the zone; `region_traversal` keeps all.
- **Dwell:** a stay inside a zone of at least a minimum number of frames (taken from the question, 5 seconds by default), with the same gap tolerance.

**Stitching** (`domain/stitching.py`): when perception loses an object and returns it under a new ID, fragments with the same label are joined if they are at most 15 frames (3 s) apart and the box centre moved no more than 25 percent of the box size per elapsed frame. `merge_intervals` joins adjacent intervals of the same relation.

### 4. Query interpretation: Muse Spark

*Current wiring:* the API, in demo mode and in the real-clips demo, reads questions with the deterministic keyword reader only. The Muse Spark parser below is built and tested over replayed replies but is not connected to the API, so the demo makes no language-model call.

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

`askfootage/application/search_relations.py` reads the question, then for each ready recording with stored tracks it stitches the tracks and runs `carrying`, `region_entry` or `dwell`. Each interval becomes a clip plus a proof (relation, frames and seconds, track ids, measures, a few boxes to draw), returned in the `proofs` array added in API contract 1.3.0. A recording with no stored tracks, no frame size (needed to turn saved zones into pixels), or a question with no relation uses the older demo keyword matcher over stored clips, and those clips have no proof. The default `create_app()` wires no track store, so a plain `uvicorn` start still serves the demo matcher; the stored-track path runs in `askfootage.interfaces.real_clips`, which passes in the SQLite tracks and a frame-size source (and in the API tests). The CLI's JSON files are not connected to the API. See [ADR 0010](docs/adr/0010-relation-search-over-stored-tracks-with-demo-fallback.md).

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

Open the address it prints (the API only accepts requests from `http://localhost:5173`). In PowerShell, the web reads the API address from `$env:VITE_API_URL` (for example `'http://localhost:8000'`), set before `npm run dev`. Questions here are answered by the keyword demo matcher over seeded clips, so this shows the interface and the evidence panel, not real perception.

**Sign-in is a demo gate, not security.** AskFootage has no accounts and no authentication. The web app opens on a sign-in page: "Continue with Microsoft" is disabled (no single sign-on is built), and "Continue with company SSO" asks for a 6-digit demo access code, which the API checks (`POST /api/auth/demo-code`). On success the web app sets a flag in the browser tab (`sessionStorage`) so the pages open. That flag is a UI convenience only: the rest of the API is not authenticated, and nothing is protected by it. Codes are created with the access CLI and are never in the source, the README or the web bundle. In the web app's mock mode no code is valid (tests inject their own). The API limits wrong codes to 5 a minute per client and 50 a minute across all clients (then 429 with `Retry-After`); the counts are in memory, so this assumes one server process and no reverse proxy (the client is the socket address; `X-Forwarded-For` is deliberately ignored).

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

`check-key` sends one tiny request and prints PASS or FAIL with a hint. `sam` prints the estimated cost first and refuses if it is above `--max-cost-usd` or `MAX_RUN_COST_USD`. A live run saves each successful reply under `data/recordings`, so repeating the same command replays it free. The SAM reply is printed raw and unparsed; parsing is done by `adapters/meta/sam.py` during ingest.

### 8. Run on your own footage with a key *(Not done)*

Live indexing from the API (`POST /api/recordings/{id}/index`) answers 503 and the `ingest` command without `--fake` is not configured. New footage can only be perceived through `scripts.api_spike` and `scripts.record_sam_demo`, which spend money and need a key.

### 9. Demo mode without a key

See the [Quick start](#quick-start-no-key-demo): `.venv\Scripts\python.exe -m scripts.run_demo`. Design notes: [ADR 0015](docs/adr/0015-one-command-no-key-demo.md).

## Configuration and secrets

Settings come from environment variables, loaded from a local `.env` file. These are read by `askfootage/settings.py`, the only module that reads the environment.

| Variable | Purpose | Secret? |
|---|---|---|
| `META_API_KEY` | Your Meta Model API key | **Yes** |
| `META_API_BASE_URL` | API address, as given in the Meta Model API docs | No |
| `MAX_RUN_COST_USD` | Hard cap in US dollars for one run (default 25) | No |
| `DATA_DIR` | Where videos, raw responses and the index live | No |
| `ASKFOOTAGE_DEMO` | Read by the settings, no effect yet; the no-key demo is started with `scripts.run_demo`, which reads no settings | No |

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

**Results so far:** on the two labelled clips the carried box is found at 1.2 to 4.8 s against 1 to 5 s labelled (`labels/`). That is a smoke test on two short clips, not an accuracy claim. Held-out results and the failure cases are not available yet.

## Demo data

This build includes a generated demo dataset. It exists so the library looks the size of a real site; it is not a real facility and not real activity.

- **Generated:** 18 cameras with factory-style names and invented department names, 61 zones, and 1,421 recordings over seven days (24 to 30 October 2026) with mixed statuses (ready, processing, and a few waiting with a plain note). The generator is `askfootage/adapters/sqlite/volume_seed.py`; it is deterministic, so every run gives the same data. Every generated row carries `origin = 'demo_volume'`.
- **Real:** the two clips, `clip1` and `clip2`, are the only recordings with video, stored object tracks, proofs and evidence snapshots. Search only ever returns them. Generated recordings have no video: opening one answers `footage_not_included`, and the app says "Footage not included in this demo build".
- **Not generated:** saved clips, search matches, proofs, tracks and activity history. Nothing about the generated cameras is evidence.
- **Where it applies:** the documented demo start (`python -m scripts.run_demo`) adds it. A plain real-mode start does not, unless `ASKFOOTAGE_DEMO_VOLUME=1`.
- **Commands** (PowerShell, from the project root; `--demo` picks the demo database, `--database PATH` a file):

```powershell
.venv\Scripts\python.exe -m askfootage.interfaces.cli.volume --status
.venv\Scripts\python.exe -m askfootage.interfaces.cli.volume --add
.venv\Scripts\python.exe -m askfootage.interfaces.cli.volume --remove
```

`--add` twice changes nothing. `--remove` deletes every generated row and leaves the real rows and the two clips as they were.

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
- The index, the questions you ask and the results stay on your machine. In the current API, questions are read locally by the keyword reader and nothing is sent; the Muse Spark parser, if connected in future, would send the question text. If verification is switched on, a few frames from each candidate are sent as well.
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
  demo/sam/             saved SAM 3.1 replies and a manifest, for the no-key demo
  docs/                 architecture notes and decision records
    adr/
    images/             README screenshots
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
        cameras/
        evidence/
        indexing/
        player/
        saved/
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

## Feedback

Questions, bug reports and ideas are welcome: open an [issue](https://github.com/IndranilPalit24/AskFootage/issues) on GitHub.

## References

- [Pricing and rate limits, Meta Model API](https://dev.meta.ai/docs/pricing-rate-limits)
- [Segmenting with prompts, Meta Model API](https://dev.meta.ai/docs/sam/segmenting)
- [Reading segmentation output, Meta Model API](https://dev.meta.ai/docs/sam/reading-segmentation)
- [File handling, Meta Model API](https://dev.meta.ai/docs/file-handling)
