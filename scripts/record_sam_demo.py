r"""Save the real SAM replies as small recordings that anyone can replay, with no key.

Run it from the project root, after the spike has saved its replies and prepare_clips has
made the prepared videos:

    .venv\Scripts\python.exe -m scripts.record_sam_demo

It reads every data/spike/sam_<clip>_<noun>.json, rebuilds the two requests that produced it
(the upload of data/prepared/<clip>/prepared.mp4 and the /responses call for the noun) and
saves each reply under demo/sam/<request fingerprint>.json with the masks stripped (they are
most of a reply and are never used). A recording is named by the fingerprint of its REQUEST,
so ReplayTransport answers the same request from it. It also writes demo/sam/manifest.json,
which says which clip, noun and fingerprint each recording is.

Nothing is sent to Meta and no key or setting is read. Everything is checked before
anything is written: the prepared video must be the very file that was uploaded (its size
must equal the "bytes" in the saved upload reply) and each reply must parse as a whole SAM
stream. Exit codes: 0 done, 2 refused (nothing written).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

if __name__ == "__main__" and not __package__:
    # Run as a file (python scripts\record_sam_demo.py), not with -m: make askfootage importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from askfootage.adapters.meta.record_replay import (  # noqa: E402
    RecordingTransport,
    ReplayTransport,
    fingerprint,
)
from askfootage.adapters.meta.sam import (  # noqa: E402
    DEFAULT_PROMPTS,
    SAM_MODEL,
    parse_sam_stream,
    redact_sam_reply,
    sam_request,
    upload_request,
    video_part,
)
from askfootage.adapters.meta.transport import (  # noqa: E402
    MetaError,
    MetaRequest,
    RawResponse,
)
from askfootage.domain.timebase import DEFAULT_ANALYSIS_FPS  # noqa: E402
from askfootage.ports.perception import PerceptionError  # noqa: E402

EXIT_OK = 0
EXIT_REFUSED = 2
MAX_RECORDING_BYTES = 100 * 1024
"""Target size of one saved recording: 100 KB."""
MANIFEST_NAME = "manifest.json"
DEFAULT_SPIKE_DIR = Path("data") / "spike"
DEFAULT_PREPARED_DIR = Path("data") / "prepared"
DEFAULT_OUT_DIR = Path("demo") / "sam"
PREPARED_NAME = "prepared.mp4"


class Refused(Exception):
    """Something was wrong with the inputs; the message is safe to print."""


@dataclass(frozen=True, slots=True)
class _Saved:
    """One spike reply with the requests that produced it."""

    clip: str
    prompt: str
    video: Path
    upload_reply: str
    reply: str
    file_id: str
    upload: MetaRequest
    request: MetaRequest
    detections: int
    last_frame: int | None


class _SavedReplies:
    """A transport that answers only the requests of the spike replies, from those replies."""

    def __init__(self, saved: Sequence[_Saved]) -> None:
        self._replies: dict[str, str] = {}
        for item in saved:
            self._replies[fingerprint(item.upload)] = item.upload_reply
            self._replies[fingerprint(item.request)] = item.reply

    def send(self, request: MetaRequest) -> RawResponse:
        return RawResponse(200, self._replies[fingerprint(request)])


def _load(path: Path, prepared_dir: Path) -> _Saved:
    try:
        envelope: Any = json.loads(path.read_text(encoding="utf-8"))
        clip, prompt = envelope["clip"], envelope["concept"]
        upload_reply, reply = envelope["files_reply"], envelope["raw"]
        uploaded = json.loads(upload_reply)
        file_id, uploaded_bytes = uploaded["id"], uploaded["bytes"]
    except (OSError, ValueError, KeyError, TypeError):
        raise Refused(f"{path.name}: not a saved SAM reply.") from None
    if not all(isinstance(v, str) for v in (clip, prompt, upload_reply, reply, file_id)):
        raise Refused(f"{path.name}: not a saved SAM reply.")
    video = prepared_dir / clip / PREPARED_NAME
    if not video.is_file():
        raise Refused(f"{path.name}: the prepared video of {clip} was not found.")
    if video.stat().st_size != uploaded_bytes:
        raise Refused(
            f"{path.name}: the prepared video of {clip} is {video.stat().st_size} bytes but "
            f"{uploaded_bytes} bytes were uploaded, so it is not the same file."
        )
    request = sam_request(prompt, video_part(file_id))
    try:
        found = parse_sam_stream(redact_sam_reply(request, reply))
    except PerceptionError as error:
        raise Refused(f"{path.name}: {error}") from None
    return _Saved(
        clip=clip,
        prompt=prompt,
        video=video,
        upload_reply=upload_reply,
        reply=reply,
        file_id=file_id,
        upload=upload_request(video),
        request=request,
        detections=len(found),
        last_frame=max((d.frame for d in found), default=None),
    )


def _manifest(saved: Sequence[_Saved]) -> dict[str, Any]:
    clips: dict[str, Any] = {}
    for item in sorted(saved, key=lambda s: (s.clip, s.prompt)):
        if item.clip not in clips:  # hash the video once per clip, not once per noun
            clips[item.clip] = {
                "prepared_sha256": hashlib.sha256(item.video.read_bytes()).hexdigest(),
                "file_id": item.file_id,
                "upload_fingerprint": fingerprint(item.upload),
                "requests": {},
            }
        entry = clips[item.clip]
        entry["requests"][item.prompt] = {
            "fingerprint": fingerprint(item.request),
            "detections": item.detections,
            "last_frame": item.last_frame,
        }
    return {
        "model": SAM_MODEL,
        "fps": DEFAULT_ANALYSIS_FPS,
        "prompts": dict(DEFAULT_PROMPTS),
        "note": "Real SAM 3.1 replies, masks removed. Frames are 0-based; seconds = frame / fps.",
        "clips": clips,
    }


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    """Record every saved reply; returns the exit code."""
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(
        prog="python -m scripts.record_sam_demo",
        description="Save the real SAM replies for replay.",
    )
    parser.add_argument("--spike-dir", type=Path, default=DEFAULT_SPIKE_DIR)
    parser.add_argument("--prepared-dir", type=Path, default=DEFAULT_PREPARED_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:  # argparse has already printed the usage message
        return EXIT_OK if stop.code in (0, None) else EXIT_REFUSED

    try:
        sources = sorted(args.spike_dir.glob("sam_*.json"))
        if not sources:
            raise Refused("No saved SAM replies (sam_<clip>_<noun>.json) were found.")
        saved = [_load(path, args.prepared_dir) for path in sources]
    except Refused as error:
        out.write(f"REFUSED: {error}\n")
        return EXIT_REFUSED

    recorder = RecordingTransport(_SavedReplies(saved), args.out, redact=redact_sam_reply)
    replay = ReplayTransport(args.out)
    out.write(f"{'clip':<6} {'prompt':<8} {'detections':>10} {'before':>10} {'after':>9}  file\n")
    try:
        for item in saved:
            recorder.send(item.upload)
            recorder.send(item.request)
            after = replay.send(item.request)
            name = f"{fingerprint(item.request)}.json"
            size = (args.out / name).stat().st_size
            if size > MAX_RECORDING_BYTES:
                raise Refused(f"{name} is {size} bytes, over the {MAX_RECORDING_BYTES} limit.")
            if "<|mask" in after.body:
                raise Refused(f"{name} still holds mask data.")
            out.write(
                f"{item.clip:<6} {item.prompt:<8} {item.detections:>10} "
                f"{len(item.reply) / 1024:>7.0f} KB {size / 1024:>6.1f} KB  {name[:12]}...\n"
            )
        manifest = args.out / MANIFEST_NAME
        manifest.write_text(
            json.dumps(_manifest(saved), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (Refused, MetaError, OSError) as error:
        out.write(f"REFUSED: {error if isinstance(error, Refused) else 'could not save'}\n")
        return EXIT_REFUSED
    out.write(f"saved {len(saved)} replies and {len(saved)} upload records under {args.out}\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
