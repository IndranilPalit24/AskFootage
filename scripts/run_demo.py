r"""Start the no-key demo: the API over the two real clips, replayed from demo/sam.

Run it from the project root:

    .venv\Scripts\python.exe -m scripts.run_demo
    .venv\Scripts\python.exe -m scripts.run_demo --port 8001

It needs videos/clip1.mp4 and videos/clip2.mp4 (not in the repository) and ffmpeg on PATH.
On the first run it makes the 5 fps copies and stores the tracks in data/real/library.sqlite,
using only the saved replies in demo/sam. Nothing is sent to Meta, no key is needed and no
setting is read. Then it serves the API; the last lines it prints say how to start the web UI.

Exit codes: 0 stopped normally, 2 refused (a clear message says why).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

if __name__ == "__main__" and not __package__:
    # Run as a file (python scripts\run_demo.py), not with -m: make askfootage importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import ingest_real_clips, prepare_clips  # noqa: E402

EXIT_OK = 0
EXIT_REFUSED = 2
CLIPS = ingest_real_clips.CLIPS
DEFAULT_PORT = 8000
WEB_URL = "http://localhost:5173"
MANIFEST_NAME = "manifest.json"
REPO_ROOT = Path(__file__).resolve().parents[1]

Serve = Callable[[Path, int], None]
"""Starts the API for a root folder on a port, and returns when it stops."""


def _video(root: Path, clip: str) -> Path:
    return root / "videos" / f"{clip}.mp4"


def check_videos(root: Path, out: TextIO) -> bool:
    """True when both clips exist; otherwise print what is missing and where to put it."""
    missing = [clip for clip in CLIPS if not _video(root, clip).is_file()]
    if not missing:
        return True
    names = " and ".join(f"{clip}.mp4" for clip in missing)
    out.write(
        f"REFUSED: {names} not found in {root / 'videos'}.\n"
        "The two demo clips are not part of the repository. Put them at\n"
        f"  {_video(root, 'clip1')}\n"
        f"  {_video(root, 'clip2')}\n"
        "and run this command again. Without them the rest of the app still works, but\n"
        "nothing can play, and the searches cannot be answered from the footage.\n"
    )
    return False


def check_tools(out: TextIO, which: Callable[[str], str | None] = shutil.which) -> bool:
    """True when ffmpeg and ffprobe are on PATH; otherwise print how to install them."""
    missing = [tool for tool in ("ffmpeg", "ffprobe") if which(tool) is None]
    if not missing:
        return True
    out.write(
        f"REFUSED: {' and '.join(missing)} not found on PATH.\n"
        "Install ffmpeg (it includes ffprobe), open a new terminal, and check it with\n"
        "  ffmpeg -version\n"
        "then run this command again.\n"
    )
    return False


def check_recordings(root: Path, out: TextIO) -> dict[str, str] | None:
    """The saved replies' manifest (clip -> prepared sha256), or None after a message."""
    path = root / ingest_real_clips.DEFAULT_RECORDINGS_DIR / MANIFEST_NAME
    try:
        clips = json.loads(path.read_text(encoding="utf-8"))["clips"]
        return {clip: str(clips[clip]["prepared_sha256"]) for clip in CLIPS}
    except (OSError, ValueError, KeyError, TypeError):
        out.write(
            f"REFUSED: the saved replies were not found or are damaged ({path}).\n"
            "They ship with the repository in demo/sam; restore that folder with\n"
            "  git checkout -- demo/sam\n"
        )
        return None


def _sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def check_prepared_bytes(root: Path, expected: dict[str, str], out: TextIO) -> bool:
    """True when each prepared copy has the bytes the saved replies were recorded for."""
    prepared = root / ingest_real_clips.DEFAULT_PREPARED_DIR
    wrong = [c for c in CLIPS if _sha256(prepared / c / "prepared.mp4") != expected[c]]
    if not wrong:
        return True
    out.write(
        f"REFUSED: the prepared copy of {', '.join(wrong)} differs from the one the saved "
        "replies were recorded for\n(its sha256 does not match demo/sam/manifest.json), so "
        "they cannot be replayed.\nThis happens when the clip file or the ffmpeg build is "
        "not the one used when the replies were saved.\n"
        "Use the original clip1.mp4 and clip2.mp4 and an ffmpeg 8.x full build "
        "(for example gyan.dev), then delete the stale copies and run again:\n"
        f"  Remove-Item -Recurse {prepared}\n"
    )
    return False


def _library(root: Path) -> Path:
    return root / ingest_real_clips.DEFAULT_DATA_DIR / ingest_real_clips.LIBRARY_NAME


def needs_ingest(root: Path) -> bool:
    """True when the library or a clip's working copy is missing."""
    data = root / ingest_real_clips.DEFAULT_DATA_DIR
    return not _library(root).is_file() or any(
        not (data / clip / "prepared.mp4").is_file() for clip in CLIPS
    )


def prepare_and_ingest(root: Path, out: TextIO) -> bool:
    """Make the prepared copies and the library offline when they are missing."""
    prepared = root / ingest_real_clips.DEFAULT_PREPARED_DIR
    missing = [c for c in CLIPS if not (prepared / c / "prepared.mp4").is_file()]
    if missing:
        out.write("Preparing the clips (5 fps copy, no audio)...\n")
        code = prepare_clips.main(
            [str(_video(root, clip)) for clip in missing], data_dir=root / "data", out=out
        )
        if code != EXIT_OK:
            return False
    expected = check_recordings(root, out)
    if expected is None or not check_prepared_bytes(root, expected, out):
        return False
    out.write("Reading the saved replies from demo/sam into the library (no network)...\n")
    code = ingest_real_clips.main(
        [
            "--data-dir",
            str(root / ingest_real_clips.DEFAULT_DATA_DIR),
            "--prepared-dir",
            str(prepared),
            "--recordings-dir",
            str(root / ingest_real_clips.DEFAULT_RECORDINGS_DIR),
        ],
        out=out,
    )
    return code == EXIT_OK


def web_instructions(port: int) -> str:
    """The exact commands to start the web UI against this API."""
    return (
        "In a second PowerShell window, start the web UI:\n"
        f"  cd web; $env:VITE_API_URL='http://localhost:{port}'; npm run dev\n"
        f"Then open {WEB_URL}\n"
    )


def serve_api(root: Path, port: int) -> None:
    """Run the real-clips API until interrupted."""
    import uvicorn

    from askfootage.interfaces.real_clips import create_app

    app = create_app(root / ingest_real_clips.DEFAULT_DATA_DIR, root / "videos")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path = REPO_ROOT,
    out: TextIO | None = None,
    serve: Serve = serve_api,
    which: Callable[[str], str | None] = shutil.which,
) -> int:
    """Check, prepare, ingest and serve; returns the exit code."""
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(
        prog="python -m scripts.run_demo",
        description="Run the no-key demo over videos/clip1.mp4 and clip2.mp4.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="API port (default 8000)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:  # argparse has already printed the usage message
        return EXIT_OK if stop.code in (0, None) else EXIT_REFUSED

    if not check_videos(root, out) or not check_tools(out, which):
        return EXIT_REFUSED
    if needs_ingest(root) and not prepare_and_ingest(root, out):
        return EXIT_REFUSED
    out.write(f"\nAPI: http://localhost:{args.port}  (stop with Ctrl+C)\n")
    out.write(web_instructions(args.port))
    out.flush()
    try:
        serve(root, args.port)
    except KeyboardInterrupt:
        out.write("Stopped.\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
