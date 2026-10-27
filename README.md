# AskFootage

**Ask your footage. Get the clip and the proof.**

AskFootage lets you ask a plain-English question about recorded camera footage, such as *"was a pallet left blocking the exit?"* or *"show me anyone carrying a box through the loading door"*. It returns the matching clips, marks each occurrence on a timeline, outlines the objects involved, and shows the measurements that justify every match.

Built by Team **EdgeCase** (solo, Indie track) for the **Meta Global AI Developer Hackathon**, Oct 27 to Nov 4, 2026, using **SAM 3.1** and **Muse Spark** through the Meta Model API.

> **Status: work in progress.** This README describes the design and marks what exists today. Anything labelled *Planned* is not built yet, and its commands may change until the first release.

| Component | Status |
|---|---|
| Relation layer: carrying, region traversal, dwell (`relations.py`) | Planned |
| Video preparation and ingest pipeline | Planned |
| Searchable index (SQLite) | Planned |
| Track stitching across occlusion | Planned |
| Query interpreter (Muse Spark) | Planned |
| Search API | Planned |
| Web UI: player, timeline, overlay, zone editor | Planned |
| Evaluation harness (precision and recall vs. hand-labelled truth) | Planned |
| No-key demo mode for judges | Planned |

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

**Objects it looks for (current vocabulary):** person, cardboard box, bag, crate. More can be added later; each new object type costs one extra processing pass over the video (see [Cost](#cost-and-api-limits)).

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

Neither model decides what "carrying" means. That is ordinary, testable code (`relations.py`), so results are reproducible and every match can be explained with numbers. Defaults, which will be tuned on real footage:

- **Carrying:** the object sits mostly inside the person's box (at least 55 percent) and its position **relative to the person** stays steady (standard deviation at most 0.18 of the person's size) for at least 8 frames (about 1.6 seconds at 5 fps). Because it measures position relative to the person, it works for a person standing still and rejects a box resting on the floor that a person walks past.
- **Region traversal:** the person's foot point enters and then leaves a polygon you drew. Each entry and exit is one event.
- **Dwell:** a traversal that lasts longer than a threshold, for people or objects.

### 4. Query interpretation: Muse Spark

Muse Spark turns a question into a fixed structure and nothing else. It may only pick object types from the indexed vocabulary, one of the supported relations, and a zone from your named list. Anything else is reported as unsupported, or as "needs indexing" with a cost estimate.

```json
{
  "relation": "dwell",
  "subject": "crate",
  "zone": "exit door",
  "min_seconds": 10
}
```

### 5. Optional verification

Muse Spark can look at a few frames from each candidate result and say whether it agrees. This is **shown beside the result and never silently removes one**, and every verdict is logged so you can see what it disagreed with.

## Tech stack

| Part | Choice |
|---|---|
| Vision model | SAM 3.1 (`sam-3.1`) via Meta Model API |
| Language model | Muse Spark 1.3 (`muse-spark-1.3`) via Meta Model API |
| Backend and relation logic | Python 3.11+ with FastAPI |
| Index | SQLite |
| Video preparation | ffmpeg |
| Web UI | React |
| Tests | Python |

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
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks the script, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` once in that window and try again.

macOS or Linux:

```
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Check the relation layer *(Planned)*

The relation tests will need no API key and no video. With the virtual environment activated, install the development tools and run the tests:

```
pip install -r requirements-dev.txt
python -m pytest
```

No tests exist yet, so today pytest reports "no tests ran". Planned: 12 passing, 2 marked as known gaps (a track that changes ID behind an obstacle, and a trolley being pushed). The two known gaps are listed under [Known limitations](#known-limitations).

### 4. Run the full pipeline *(Planned)*

These steps describe the intended interface and will work as each component lands.

1. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```
2. **Add your own Meta Model API key.** Copy `.env.example` to `.env` and fill in your key. See [Configuration and secrets](#configuration-and-secrets). Never commit `.env`.
3. **Put a video in `videos/`.** Use a fixed camera, MP4 with H.264. Only use footage you have the right to use, with the consent of anyone who appears in it.
4. **Preview the cost before spending anything**
   ```
   python -m askfootage.ingest videos/demo.mp4 --concepts "person,cardboard box,bag,crate" --dry-run
   ```
5. **Index the video**
   ```
   python -m askfootage.ingest videos/demo.mp4 --concepts "person,cardboard box,bag,crate"
   ```
6. **Start the API and the web UI**
   ```
   uvicorn askfootage.interfaces.api.app:app --port 8000
   cd web
   npm install
   npm run dev
   ```
   Then open the address that `npm run dev` prints.
7. **Draw your zones** (the doorway, the exit) on a reference frame in the UI, then **ask a question**.

### 5. Demo mode without a key *(Planned)*

For anyone who wants to try AskFootage without an API key, the repo will include a short sample clip with its model responses already saved. Setting `ASKFOOTAGE_DEMO=1` runs the full interface on that clip using the saved responses. Preset example questions work offline. Free-text questions need a key, because interpreting them calls Muse Spark.

### 6. Measure accuracy *(Planned)*

```
python -m askfootage.evaluate --truth labels/demo_truth.csv
```

## Configuration and secrets

Settings come from environment variables, loaded from a local `.env` file. Names below are planned.

| Variable | Purpose | Secret? |
|---|---|---|
| `META_API_KEY` | Your Meta Model API key | **Yes** |
| `META_API_BASE_URL` | API address, as given in the Meta Model API docs | No |
| `MAX_RUN_COST_USD` | Hard stop for one indexing run (default 25) | No |
| `DATA_DIR` | Where videos, raw responses and the index live | No |
| `ASKFOOTAGE_DEMO` | `1` to run on the bundled sample without a key | No |

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

The app shows a cost estimate before any run and stops at `MAX_RUN_COST_USD`.

## Evaluation

Accuracy will be measured against hand-labelled ground truth on footage filmed for this project, following a written script of what happens at what time.

- A result counts as correct when its time range overlaps a labelled event by at least a set threshold.
- Thresholds are tuned on one set of clips and reported on a **separate held-out set**.
- Results report raw counts (true positives, false positives, missed events), not only percentages, because the test set is small.
- Scripted footage and any uncontrolled footage are reported separately.
- A baseline will compare AskFootage with asking Muse Spark the same questions directly on the raw video.

**Results: not yet available.** They will be published here after evaluation, with the failure cases.

## Known limitations

- **Fixed camera only.** Zones are drawn in image coordinates, so a moving camera breaks them.
- **Tracking IDs are not stable forever.** Meta's docs say IDs hold only while an object stays in view. An object hidden behind something can come back under a new ID. A stitching step is planned, and the test for it is marked as a known gap.
- **16 objects per frame.** Crowded scenes are truncated by the API.
- **5 frames per second.** Start and end times are accurate to roughly a third of a second.
- **Carrying can be confused** by a box hidden behind a body, a bag on a shoulder, two people carrying one item, an overhead camera, or a load being pushed on a trolley (known gap).
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

*Skeleton only, no application code yet. Folder purposes come from [docs/architecture.md](docs/architecture.md).*

```
AskFootage/
  .github/              CI workflows (tests, secret scan)
    workflows/
  .vscode/              editor settings (LF line endings)
  askfootage/           backend: domain, ports, application, adapters, interfaces
    adapters/
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
  .env.example
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
