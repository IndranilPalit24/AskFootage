r"""API spike: check that the Meta API key works, and see what SAM 3.1 returns for a video.

Run it from the project root:

    .venv\Scripts\python.exe -m scripts.api_spike check-key
    .venv\Scripts\python.exe -m scripts.api_spike sam
    .venv\Scripts\python.exe -m scripts.api_spike sam --live

check-key sends ONE cheap request to POST /responses and reports one distinct result and
exit code per kind of failure (see EXIT_CODES). Add --dry-run to only print the request.

sam without --live is a plan: it prints the file, the frame count at 5 fps, the estimated
cost and the exact request bodies, and sends nothing (no network, no key needed).
sam --live prepares the video (ffmpeg, 5 fps H.264), uploads it with POST /files, asks
POST /responses for model sam-3.1 with stream on, and prints the RAW reply (server-sent
events included, unparsed). The reply is saved to <DATA_DIR>/spike/sam_reply.json. Every
call goes RecordingTransport -> BudgetedTransport (MAX_RUN_COST_USD hard cap) -> client.

The settings come from askfootage.settings.load_settings(). The key, request headers and
environment are never printed or saved.
"""

import argparse
import json
import math
import re
import shutil
import sys
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

if __name__ == "__main__" and not __package__:
    # Run as a file (python scripts\api_spike.py), not with -m: make askfootage importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from askfootage.adapters.media.ffmpeg import (  # noqa: E402
    PREPARED_FPS,
    FfmpegVideoPreparer,
    run_command,
)
from askfootage.adapters.meta.budget import (  # noqa: E402
    BudgetedTransport,
    HardCapBudget,
    frames_cost,
)
from askfootage.adapters.meta.client import MetaHttpClient  # noqa: E402
from askfootage.adapters.meta.record_replay import RecordingTransport, fingerprint  # noqa: E402
from askfootage.adapters.meta.transport import (  # noqa: E402
    FileUpload,
    MetaApiError,
    MetaConnectionError,
    MetaError,
    MetaRequest,
    RawResponse,
    Transport,
)
from askfootage.ports.budget import BudgetError  # noqa: E402
from askfootage.ports.video_store import (  # noqa: E402
    PreparedVideo,
    VideoPreparationError,
    VideoPreparer,
)
from askfootage.settings import ConfigurationError, Settings, load_settings  # noqa: E402

EXIT_CODES = {
    "OK": 0,
    "OK_KEY_AND_MODEL": 0,
    "UNEXPECTED": 1,
    "REFUSED": 2,
    "KEY_MISSING": 10,
    "KEY_REJECTED": 11,
    "NO_CREDITS": 12,
    "MODEL_NOT_FOUND": 13,
    "RATE_LIMITED": 14,
    "NETWORK_ERROR": 15,
}
"""Result name (printed as `RESULT: <name>`) and the exit code that goes with it.

UNEXPECTED is any other failure (unexpected status, file error); REFUSED is invalid input
or settings, a missing video, or the budget cap refusing the call.
"""
EXIT_OK = EXIT_CODES["OK"]
EXIT_API_FAILURE = EXIT_CODES["UNEXPECTED"]
EXIT_REFUSED = EXIT_CODES["REFUSED"]

SAM_MODEL = "sam-3.1"
CHECK_PROMPT = "person"
CHECK_ESTIMATE_USD = Decimal("0.001")
"""Tiny spend estimate that check-key reserves in the budget."""
EXCERPT_CHARS = 300
"""Characters of an error or check-key reply to print."""

DEFAULT_NOUN = "person"
DEFAULT_VIDEO = Path("videos") / "clip1.mp4"
SPIKE_DIR_NAME = "spike"
SAM_REPLY_FILE = "sam_reply.json"
SYNTHETIC_FILE = "synthetic.mp4"
UPLOAD_PURPOSE = "user_data"
MAX_PRINTED_LINES = 80
MAX_NOUN_CHARS = 40

_QUOTA_TEXT = re.compile(r"quota|credit|billing|insufficient|payment|balance|funds", re.I)
_REDACTED = "[REDACTED]"

HINTS = {
    "OK_KEY_AND_MODEL": "The key works and sam-3.1 exists: the API rejected this video-less "
    "request shape (400/422), as expected.",
    "KEY_MISSING": "META_API_KEY is not set. Put it in .env (never in a chat or a commit).",
    "KEY_REJECTED": "The API refused the key (401/403): it is wrong, expired or revoked.",
    "NO_CREDITS": "No credits or billing (402 or quota text): add credits to the account.",
    "MODEL_NOT_FOUND": "HTTP 404: the model name or the path does not exist for this key.",
    "RATE_LIMITED": "HTTP 429: too many requests; wait a minute and run it again.",
    "NETWORK_ERROR": "The API could not be reached: check internet, VPN, proxy and firewall.",
    "UNEXPECTED": "Unexpected status: see the reply excerpt below.",
}


class _Reporter:
    """Writes lines to `out`, scrubbing the API key from every one of them first."""

    def __init__(self, out: TextIO, settings: Settings) -> None:
        self._out = out
        self._settings = settings

    def say(self, text: str = "") -> None:
        self._out.write(_scrub(text, self._settings) + "\n")


def classify(status: int, body: str) -> str:
    """The RESULT name for an HTTP error status and its reply text."""
    if status == 401:
        return "KEY_REJECTED"
    if status == 402 or (status in (400, 403, 429) and _QUOTA_TEXT.search(body)):
        return "NO_CREDITS"
    if status == 403:
        return "KEY_REJECTED"
    if status == 404:
        return "MODEL_NOT_FOUND"
    if status == 429:
        return "RATE_LIMITED"
    return "UNEXPECTED"


def check_key_request() -> MetaRequest:
    """The one request that check-key sends: sam-3.1, a noun and no video (may get 400/422)."""
    return MetaRequest("/responses", json_body={"model": SAM_MODEL, "input": CHECK_PROMPT})


def sam_request(noun: str, video_part: dict[str, str], *, stream: bool = True) -> MetaRequest:
    """The /responses request asking SAM to find `noun` in the video given by `video_part`."""
    return MetaRequest(
        "/responses",
        json_body={
            "model": SAM_MODEL,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": noun}, video_part],
                }
            ],
            "stream": stream,
            "metadata": {"include_confidence": "true"},
        },
    )


def build_parser() -> argparse.ArgumentParser:
    """The command-line parser for both subcommands."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.api_spike",
        description="Check the Meta API key, or try SAM 3.1 on one video.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check-key", help="send ONE cheap request to test the key")
    check.add_argument("--dry-run", action="store_true", help="only print the request")
    check.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)  # no-op

    sam = commands.add_parser("sam", help="plan, or with --live run, SAM 3.1 on one video")
    sam.add_argument("--live", action="store_true", help="really upload and call (costs money)")
    sam.add_argument("--video", type=Path, default=None, help=f"default {DEFAULT_VIDEO}")
    sam.add_argument("--object", default=DEFAULT_NOUN, help=f"default {DEFAULT_NOUN}")
    sam.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)  # refused, see main
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    transport: Transport | None = None,
    out: TextIO | None = None,
    preparer: VideoPreparer | None = None,
    probe_duration: Callable[[Path], float | None] | None = None,
    synthesize: Callable[[Path], int] | None = None,
) -> int:
    """Run the spike and return its exit code (see EXIT_CODES).

    `transport` is the live side (default MetaHttpClient), used only by check-key and
    sam --live; `preparer`, `probe_duration` and `synthesize` default to ffmpeg-based ones.
    """
    out = sys.stdout if out is None else out
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as stop:  # argparse has already printed the usage message
        return EXIT_OK if stop.code in (0, None) else EXIT_REFUSED

    if settings is None:
        try:
            settings = load_settings()
        except ConfigurationError as error:
            out.write(f"REFUSED: {error}\n")
            return EXIT_REFUSED

    report = _Reporter(out, settings)
    if args.command == "check-key":
        return _check_key(args, settings, transport, report)
    if args.yes:
        report.say("REFUSED: --yes no longer exists for sam; use --live to really send.")
        return EXIT_REFUSED
    return _sam(
        args,
        settings,
        transport,
        report,
        preparer or FfmpegVideoPreparer(),
        probe_duration or _ffprobe_duration,
        synthesize or _synthesize,
    )


# --- check-key ----------------------------------------------------------------------------


def _result(report: _Reporter, name: str, *, status: int | None = None, body: str = "") -> int:
    report.say(f"RESULT: {name}")
    if status is not None:
        report.say(f"HTTP status: {status}")
    if name != "OK":
        report.say(f"hint: {HINTS[name]}")
    if body:
        report.say(f"reply (first {EXCERPT_CHARS} characters):")
        report.say(body[:EXCERPT_CHARS])
    report.say(f"exit code: {EXIT_CODES[name]}")
    return EXIT_CODES[name]


def _check_name(status: int, body: str) -> str:
    """check-key's result: a 400/422 means the key and the model name were accepted."""
    name = classify(status, body)
    if name == "UNEXPECTED" and status in (400, 422):
        return "OK_KEY_AND_MODEL"
    return name


def _failure(error: Exception, report: _Reporter, *, check: bool = False) -> int:
    """Report an exception from a send as one distinct RESULT."""
    if isinstance(error, ConfigurationError):  # a missing key: nothing was sent
        return _result(report, "KEY_MISSING")
    if isinstance(error, MetaApiError):
        name = (_check_name if check else classify)(error.status, error.body_excerpt)
        return _result(report, name, status=error.status, body=error.body_excerpt)
    if isinstance(error, MetaConnectionError):
        return _result(report, "NETWORK_ERROR")
    report.say(f"detail: {type(error).__name__}: {error}")
    return _result(report, "UNEXPECTED")


def _check_key(
    args: argparse.Namespace, settings: Settings, transport: Transport | None, report: _Reporter
) -> int:
    request = check_key_request()
    if args.dry_run:
        report.say("DRY RUN: nothing was sent.")
        report.say(f"POST {request.path}  (base URL {settings.api_base_url})")
        report.say(f"body: {json.dumps(request.json_body, indent=2)}")
        return EXIT_OK
    if settings.api_key is None:
        return _result(report, "KEY_MISSING")
    live = transport if transport is not None else MetaHttpClient(settings)
    try:
        budget = HardCapBudget(settings.max_run_cost_usd, settings.data_dir / SPIKE_DIR_NAME)
        guarded = BudgetedTransport(live, budget, lambda _r: CHECK_ESTIMATE_USD)
        reply = guarded.send(request)
    except BudgetError as error:
        report.say(f"REFUSED: {error}")
        return EXIT_REFUSED
    except OSError as error:
        report.say(f"file error: {error}")
        return EXIT_API_FAILURE
    except (ConfigurationError, MetaError) as error:
        return _failure(error, report, check=True)
    if 200 <= reply.status < 300:
        return _result(report, "OK", status=reply.status, body=reply.body)
    return _result(
        report, _check_name(reply.status, reply.body), status=reply.status, body=reply.body
    )


# --- sam ------------------------------------------------------------------------------------


def _ffprobe_duration(path: Path) -> float | None:
    """Duration in seconds of a local video, or None when ffprobe is missing or fails."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    args = [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0"]
    try:
        result = run_command([*args, str(path)], timeout=60.0)
        seconds = float(result.stdout.strip())
    except Exception:  # noqa: BLE001 - any probe failure just means "unknown"
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _synthetic_frames_at_5_fps() -> int:
    from scripts import make_synthetic_video as synth

    return math.ceil(synth.FRAME_COUNT / synth.FPS * PREPARED_FPS)


def _synthesize(target: Path) -> int:
    """Write the synthetic clip to `target`; returns make_synthetic_video's exit code."""
    from scripts import make_synthetic_video as synth

    return synth.main([str(target), "--force"], out=sys.stderr)


def _plan(
    video: Path,
    noun: str,
    settings: Settings,
    probe: Callable[[Path], float | None],
    report: _Reporter,
) -> None:
    report.say("PLAN (nothing is sent; add --live to run it):")
    if video.is_file():
        seconds = probe(video)
        frames = None if seconds is None else math.ceil(seconds * PREPARED_FPS)
        report.say(f"file: {video}  ({video.stat().st_size} bytes)")
    else:
        report.say(f"file: {video}  NOT FOUND")
        if video == DEFAULT_VIDEO:
            report.say("  --live would fall back to a SYNTHETIC video (make_synthetic_video.py)")
            frames = _synthetic_frames_at_5_fps()
        else:
            frames = None
            report.say("  --live would refuse: the --video you named does not exist")
    if frames is None:
        report.say(f"frames at {PREPARED_FPS} fps: unknown")
        report.say("estimated cost: unknown (at least $0.01: 50 frames are always billed)")
    else:
        report.say(f"frames at {PREPARED_FPS} fps: {frames}")
        report.say(
            f"estimated cost: ${frames_cost(frames)}  (hard cap ${settings.max_run_cost_usd})"
        )
    report.say("")
    report.say(f"1) POST {settings.api_base_url}/files  (multipart/form-data)")
    report.say(f"   form field: purpose = {UPLOAD_PURPOSE}")
    report.say("   file field: file = prepared.mp4 (the 5 fps H.264 copy)")
    request = sam_request(noun, {"type": "input_video", "file_id": "<id from the /files reply>"})
    report.say(f"2) POST {settings.api_base_url}{request.path}")
    report.say(f"   body: {json.dumps(request.json_body, indent=2)}")


def _resolve_video(
    args: argparse.Namespace, spike_dir: Path, synthesize: Callable[[Path], int], report: _Reporter
) -> Path | None:
    if args.video is not None:
        return args.video if args.video.is_file() else None
    if DEFAULT_VIDEO.is_file():
        return DEFAULT_VIDEO
    target = spike_dir / SYNTHETIC_FILE
    spike_dir.mkdir(parents=True, exist_ok=True)
    report.say(f"FALLBACK: {DEFAULT_VIDEO} is missing; using a SYNTHETIC video: {target}")
    if synthesize(target) != 0 or not target.is_file():
        return None
    return target


def _sam(
    args: argparse.Namespace,
    settings: Settings,
    transport: Transport | None,
    report: _Reporter,
    preparer: VideoPreparer,
    probe: Callable[[Path], float | None],
    synthesize: Callable[[Path], int],
) -> int:
    noun: str = args.object.strip()
    if not 1 <= len(noun) <= MAX_NOUN_CHARS:
        report.say(f"INVALID: --object must be 1 to {MAX_NOUN_CHARS} characters")
        return EXIT_REFUSED
    spike_dir = settings.data_dir / SPIKE_DIR_NAME

    if not args.live:
        _plan(
            args.video if args.video is not None else DEFAULT_VIDEO, noun, settings, probe, report
        )
        return EXIT_OK

    if settings.api_key is None:
        return _result(report, "KEY_MISSING")
    if args.video is not None and not args.video.is_file():
        report.say(f"INVALID: video {args.video} does not exist or is not a file")
        return EXIT_REFUSED
    source = _resolve_video(args, spike_dir, synthesize, report)
    if source is None:
        report.say("INVALID: no video to send (the synthetic fallback could not be made)")
        return EXIT_REFUSED
    try:
        prepared: PreparedVideo = preparer.prepare(source, spike_dir / "prepared")
    except VideoPreparationError as error:
        report.say(f"INVALID: could not prepare the video: {error}")
        return EXIT_REFUSED
    report.say(
        f"prepared: {prepared.path} ({PREPARED_FPS} fps H.264, {prepared.frame_count} frames, "
        f"{prepared.duration_seconds:.2f} s)"
    )

    cost = frames_cost(prepared.frame_count)
    live = transport if transport is not None else MetaHttpClient(settings)
    try:
        budget = HardCapBudget(settings.max_run_cost_usd, spike_dir)
    except OSError as error:
        report.say(f"file error: {error}")
        return EXIT_API_FAILURE
    guarded = BudgetedTransport(live, budget, lambda r: Decimal(0) if r.upload else cost)
    recordings = settings.data_dir / "recordings"
    recorder = RecordingTransport(guarded, recordings)

    try:
        upload_reply: RawResponse = recorder.send(
            MetaRequest("/files", upload=FileUpload(prepared.path, UPLOAD_PURPOSE))
        )
        file_id = _file_id(upload_reply.body)
        if file_id is None:
            report.say("FAIL: the /files reply has no file id.")
            report.say(f"HTTP status: {upload_reply.status}")
            report.say(upload_reply.body[:EXCERPT_CHARS])
            return EXIT_API_FAILURE
        request = sam_request(noun, {"type": "input_video", "file_id": file_id})
        recording = recordings / f"{fingerprint(request)}.json"
        replayed = recording.is_file()
        reply = recorder.send(request)
    except BudgetError as error:
        report.say(f"REFUSED: {error}")
        return EXIT_REFUSED
    except (ConfigurationError, MetaError) as error:
        return _failure(error, report)
    except OSError as error:
        report.say(f"file error: {error}")
        return EXIT_API_FAILURE

    saved = spike_dir / SAM_REPLY_FILE
    payload = {
        "http_status": reply.status,
        "files_reply": _scrub(upload_reply.body, settings),
        "raw": _scrub(reply.body, settings),
    }
    try:
        saved.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as error:
        report.say(f"file error: {error}")
        return EXIT_API_FAILURE

    ok = 200 <= reply.status < 300
    name = "OK" if ok else classify(reply.status, reply.body)
    report.say(f"RESULT: {name}")
    report.say(f"HTTP status: {reply.status}")
    report.say(
        "source: saved recording (nothing sent, no cost)" if replayed else "source: live call"
    )
    lines = reply.body.splitlines()
    report.say(f"RAW reply ({len(lines)} lines, {len(reply.body)} characters):")
    for line in lines[:MAX_PRINTED_LINES]:
        report.say(line)
    if len(lines) > MAX_PRINTED_LINES:
        report.say(f"... {len(lines) - MAX_PRINTED_LINES} more lines; full reply in {saved}")
    report.say(f"full reply saved to: {saved}")
    report.say(f"estimated cost of this call: ${cost}")
    report.say(f"total spend recorded (all runs): ${budget.spent} of ${budget.cap} cap")
    report.say(f"spend ledger: {spike_dir / 'spend-ledger.jsonl'}")
    return EXIT_CODES[name]


def _scrub(text: str, settings: Settings) -> str:
    if settings.api_key is None:
        return text
    return text.replace(settings.require_api_key(), _REDACTED)


def _file_id(body: str) -> str | None:
    """The `id` field of a /files reply, or None if the reply has no usable one."""
    try:
        parsed: Any = json.loads(body)
    except json.JSONDecodeError:
        return None
    file_id = parsed.get("id") if isinstance(parsed, dict) else None
    return file_id if isinstance(file_id, str) and file_id else None


if __name__ == "__main__":
    sys.exit(main())
