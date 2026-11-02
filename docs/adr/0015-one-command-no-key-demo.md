# ADR 0015: One command for the no-key demo

Status: Accepted (2026-11-02)

## Context

Judges must be able to run AskFootage without a Meta key. The saved SAM 3.1 replies for the
two demo clips are in `demo/sam`, but using them took three commands in the right order
(prepare the clips, ingest from the replies, start the API), and a failure at any step ended
in a stack trace or an empty library.

## Decision

- `python -m scripts.run_demo` is the single start command. It reuses the existing steps
  (`scripts.prepare_clips`, `scripts.ingest_real_clips`, and the `real_clips` API) in
  one process. The standalone commands keep working.
- It checks first, and refuses with a short plain message and exit code 2 (no stack trace) when
  `videos/clip1.mp4` or `videos/clip2.mp4` is missing (the clips are not in the repository, so
  the message says where to put them), when ffmpeg or ffprobe is not on PATH, or when
  `demo/sam/manifest.json` is missing.
- It does the slow steps only when their output is missing, so a second start is quick.
- Replies are matched by a fingerprint that includes the hash of the prepared video's bytes.
  Before ingesting, the command compares the prepared copy's hash with the one in the
  manifest. If they differ (a different clip file or ffmpeg build) it stops and says so, with
  the exact fix, instead of failing later with "recording not found".
- It never calls Meta and reads no settings or key. The only transport is the replay one.
- It prints the PowerShell command for the web
  (`cd web; $env:VITE_API_URL='http://localhost:8000'; npm run dev`) and the address
  `http://localhost:5173`, which is the only origin the API allows.

## Consequences

- A fresh clone plus the two clips works with one command; this is tested by copying the
  clips and `demo/sam` into an empty folder, running the same steps, and checking that
  "person carrying a box" returns clip2 and not clip1.
- The demo reads questions with the keyword reader. The Muse Spark parser is not part of it.
- Only the two recorded clips can be searched. New footage needs a key and the spike scripts.
