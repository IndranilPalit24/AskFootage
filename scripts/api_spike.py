r"""API spike: check that the Meta API key works, and see what SAM 3.1 returns for a video.

Run it from the project root, as a module or as a file
(.venv\Scripts\python.exe scripts\api_spike.py check-key works too). Every command is a
dry run unless you add --yes: a dry run prints what would be sent and sends nothing.

    .venv\Scripts\python.exe -m scripts.api_spike check-key
    .venv\Scripts\python.exe -m scripts.api_spike check-key --yes
    .venv\Scripts\python.exe -m scripts.api_spike sam --video clip.mp4 --object car `
        --duration-seconds 30
    .venv\Scripts\python.exe -m scripts.api_spike sam --video clip.mp4 --object car `
        --duration-seconds 30 --yes

check-key sends one tiny request to /responses and says PASS or FAIL, with a plain-English
hint for each failure. It is never recorded, so it always tests the key as it is now.

sam checks the video and the estimated cost first, and refuses (exit code 2) when the cost
is above --max-cost-usd or above MAX_RUN_COST_USD from the settings. A live run goes
through a RecordingTransport that saves each successful reply under
<DATA_DIR>/recordings, so running the same command again replays it at no cost. The SAM
reply is printed raw, unparsed.

The settings come from askfootage.settings.load_settings(). Nothing here reads the
environment, and the key, request headers and environment are never printed.

Exit codes: 0 success or dry run, 1 the API call failed, 2 refused or invalid input.
"""

import argparse
import base64
import json
import math
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TextIO

if __name__ == "__main__" and not __package__:
    # Run as a file (python scripts\api_spike.py), not with -m: make askfootage importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
from askfootage.settings import ConfigurationError, Settings, load_settings  # noqa: E402

EXIT_OK = 0
"""Exit code for a successful call or a dry run."""
EXIT_API_FAILURE = 1
"""Exit code when the API call failed or its reply was unusable."""
EXIT_REFUSED = 2
"""Exit code for invalid input, invalid settings, or a cost above a limit."""

CHECK_MODEL = "muse-spark-1.3"
"""Model that check-key asks."""
CHECK_PROMPT = "Reply with the single word OK."
"""Prompt that check-key sends."""
CHECK_MAX_OUTPUT_TOKENS = 16
"""Output-token limit for check-key, so the check costs next to nothing."""
CHECK_EXCERPT_CHARS = 200
"""Characters of the check-key reply to print."""

SAM_MODEL = "sam-3.1"
"""Model that the sam command asks."""
SAM_EXCERPT_CHARS = 300
"""Characters of the SAM reply to print."""
UPLOAD_PURPOSE = "user_data"
"""Purpose sent with a video uploaded to /files."""

MIN_BILLED_FRAMES = 50
"""Fewest frames a SAM call is billed for."""
USD_PER_THOUSAND_FRAMES = Decimal("0.20")
"""Estimated SAM price per thousand frames, in US dollars."""
DEFAULT_MAX_COST_USD = Decimal("0.50")
"""Default for --max-cost-usd."""
DEFAULT_FPS = Decimal("30")
"""Default for --fps."""

MAX_VIDEO_BYTES = 100_000_000
"""A video must be smaller than this (100 MB) to be sent."""
MAX_OBJECT_CHARS = 40
"""Longest object noun, after trimming spaces."""
VIDEO_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime"}
"""Accepted video file extensions and the media type of each."""

STATUS_HINTS = {
    400: "body not accepted: the API did not accept the request body; check the model "
    "name and the fields",
    401: "key rejected: META_API_KEY is wrong, expired or revoked",
    403: "not allowed or billing: the key is valid but may not use this model, or billing "
    "is not set up for the account",
    404: "model or path not found: check the model name and META_API_BASE_URL",
    429: "rate limited: too many requests or quota used up; wait and try again",
}
"""Plain-English hint for each HTTP error status the spike expects."""
CONNECTION_HINT = (
    "network or proxy: the API could not be reached; check the internet connection, VPN, "
    "proxy or firewall, and META_API_BASE_URL"
)
"""Hint when no reply arrived at all."""
OTHER_STATUS_HINT = "unexpected status: see the reply below"
"""Hint for an error status without a specific hint."""

_REDACTED = "[REDACTED]"


class _Reporter:
    """Writes lines to `out`, scrubbing the API key from every one of them first."""

    def __init__(self, out: TextIO, settings: Settings) -> None:
        self._out = out
        self._settings = settings

    def say(self, text: str = "") -> None:
        if self._settings.api_key is not None:
            text = text.replace(self._settings.require_api_key(), _REDACTED)
        self._out.write(text + "\n")


def estimate_cost_usd(duration_seconds: Decimal, fps: Decimal) -> Decimal:
    """Estimated SAM cost in US dollars: frames rounded up, at least 50, at $0.20 per 1000."""
    frames = max(MIN_BILLED_FRAMES, math.ceil(duration_seconds * fps))
    return frames * USD_PER_THOUSAND_FRAMES / 1000


def check_key_request() -> MetaRequest:
    """The one request that check-key sends."""
    return MetaRequest(
        "/responses",
        json_body={
            "model": CHECK_MODEL,
            "input": CHECK_PROMPT,
            "max_output_tokens": CHECK_MAX_OUTPUT_TOKENS,
        },
    )


def sam_request(noun: str, video_part: dict[str, str], *, stream: bool) -> MetaRequest:
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
        description="Check the Meta API key, or try SAM 3.1 on one video. "
        "Dry run unless --yes is given.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check-key", help="send one tiny request to test the key")
    check.add_argument("--yes", action="store_true", help="really send it")

    sam = commands.add_parser("sam", help="ask SAM 3.1 to find an object in a video")
    sam.add_argument("--video", type=Path, required=True, help=".mp4 or .mov under 100 MB")
    sam.add_argument("--object", required=True, help="what to look for, 1-40 characters")
    sam.add_argument(
        "--duration-seconds", type=_positive_decimal, required=True, help="video length"
    )
    sam.add_argument("--fps", type=_positive_decimal, default=DEFAULT_FPS, help="default 30")
    sam.add_argument(
        "--max-cost-usd",
        type=_non_negative_decimal,
        default=DEFAULT_MAX_COST_USD,
        help="refuse above this estimated cost; default 0.50",
    )
    sam.add_argument("--inline", action="store_true", help="send the video as a data URL")
    sam.add_argument("--no-stream", action="store_true", help='send "stream": false')
    sam.add_argument("--yes", action="store_true", help="really send it")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    transport: Transport | None = None,
    out: TextIO | None = None,
) -> int:
    """Run the spike and return its exit code: 0 ok or dry run, 1 API failure, 2 refused.

    `settings` defaults to load_settings(), `transport` (the live side, used only with
    --yes) to a MetaHttpClient, and `out` to standard output.
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
    return _sam(args, settings, transport, report)


def _check_key(
    args: argparse.Namespace,
    settings: Settings,
    transport: Transport | None,
    report: _Reporter,
) -> int:
    request = check_key_request()
    if not args.yes:
        report.say("DRY RUN: nothing was sent. Add --yes to send this request.")
        report.say(f"POST {request.path}  (base URL {settings.api_base_url})")
        report.say(f"body: {json.dumps(request.json_body, indent=2)}")
        return EXIT_OK

    live = transport if transport is not None else MetaHttpClient(settings)
    try:
        reply = live.send(request)
    except (ConfigurationError, MetaError) as error:
        return _report_failure(error, report)
    return _report_check_reply(reply, report)


def _report_check_reply(reply: RawResponse, report: _Reporter) -> int:
    passed = 200 <= reply.status < 300
    report.say("PASS" if passed else "FAIL")
    report.say(f"HTTP status: {reply.status}")
    if not passed:
        report.say(f"hint: {_hint(reply.status)}")
    report.say(f"reply length: {len(reply.body)} characters")
    report.say(f"reply (first {CHECK_EXCERPT_CHARS} characters):")
    report.say(reply.body[:CHECK_EXCERPT_CHARS])
    return EXIT_OK if passed else EXIT_API_FAILURE


def _sam(
    args: argparse.Namespace,
    settings: Settings,
    transport: Transport | None,
    report: _Reporter,
) -> int:
    video: Path = args.video
    noun: str = args.object.strip()
    problem = _video_problem(video) or _noun_problem(noun)
    if problem is not None:
        report.say(f"INVALID: {problem}")
        return EXIT_REFUSED

    cost = estimate_cost_usd(args.duration_seconds, args.fps)
    for limit, name in (
        (args.max_cost_usd, "--max-cost-usd"),
        (settings.max_run_cost_usd, "MAX_RUN_COST_USD in the settings"),
    ):
        if cost > limit:
            report.say(f"REFUSED: estimated cost ${cost} is above {name} (${limit}).")
            return EXIT_REFUSED

    recordings = settings.data_dir / "recordings"
    stream = not args.no_stream
    if not args.yes:
        _report_sam_dry_run(video, noun, cost, recordings, args.inline, stream, report)
        return EXIT_OK

    live = transport if transport is not None else MetaHttpClient(settings)
    recorder = RecordingTransport(live, recordings)
    try:
        if args.inline:
            video_part = {"type": "input_video", "video_url": _data_url(video)}
        else:
            upload = recorder.send(MetaRequest("/files", upload=FileUpload(video, UPLOAD_PURPOSE)))
            file_id = _file_id(upload.body)
            if file_id is None:
                report.say("FAIL: the /files reply has no file id.")
                report.say(f"HTTP status: {upload.status}")
                report.say(f"reply (first {SAM_EXCERPT_CHARS} characters):")
                report.say(upload.body[:SAM_EXCERPT_CHARS])
                return EXIT_API_FAILURE
            video_part = {"type": "input_video", "file_id": file_id}
        request = sam_request(noun, video_part, stream=stream)
        recording = recordings / f"{fingerprint(request)}.json"
        replayed = recording.is_file()
        reply = recorder.send(request)
    except (ConfigurationError, MetaError, OSError) as error:
        # OSError: the video could not be read, or a recording could not be written.
        return _report_failure(error, report)

    report.say("OK" if 200 <= reply.status < 300 else "FAIL")
    report.say(f"estimated cost: ${cost}")
    report.say(
        "source: saved recording (nothing sent, no cost)" if replayed else "source: live call"
    )
    report.say(f"HTTP status: {reply.status}")
    report.say(f"reply length: {len(reply.body)} characters")
    report.say(f"lines: {len(reply.body.splitlines())}")
    report.say(f"reply (first {SAM_EXCERPT_CHARS} characters):")
    report.say(reply.body[:SAM_EXCERPT_CHARS])
    report.say(f"recording: {recording}")
    return EXIT_OK if 200 <= reply.status < 300 else EXIT_API_FAILURE


def _report_sam_dry_run(
    video: Path,
    noun: str,
    cost: Decimal,
    recordings: Path,
    inline: bool,
    stream: bool,
    report: _Reporter,
) -> None:
    size = video.stat().st_size
    report.say("DRY RUN: nothing was sent. Add --yes to send these requests.")
    report.say(f"estimated cost: ${cost}")
    if inline:
        media_type = VIDEO_TYPES[video.suffix.lower()]
        part = {
            "type": "input_video",
            "video_url": f"data:{media_type};base64,<{size} bytes of {video.name}, base64>",
        }
    else:
        report.say(
            f"POST /files  (multipart: file={video.name}, {size} bytes, purpose={UPLOAD_PURPOSE})"
        )
        part = {"type": "input_video", "file_id": "<id from the /files reply>"}
    request = sam_request(noun, part, stream=stream)
    report.say(f"POST {request.path}")
    report.say(f"body: {json.dumps(request.json_body, indent=2)}")
    report.say(f"replies would be recorded under: {recordings}")


def _report_failure(error: ConfigurationError | MetaError | OSError, report: _Reporter) -> int:
    if isinstance(error, ConfigurationError):  # includes a missing key; nothing was sent
        report.say(f"REFUSED: {error}")
        return EXIT_REFUSED
    report.say("FAIL")
    if isinstance(error, MetaApiError):
        report.say(f"HTTP status: {error.status}")
        report.say(f"hint: {_hint(error.status)}")
        report.say(f"reply length: {len(error.body_excerpt)} characters (excerpt)")
        report.say(f"reply (first {CHECK_EXCERPT_CHARS} characters):")
        report.say(error.body_excerpt[:CHECK_EXCERPT_CHARS])
    elif isinstance(error, MetaConnectionError):
        report.say(f"hint: {CONNECTION_HINT}")
        report.say(f"detail: {error}")
    elif isinstance(error, OSError):
        report.say(f"file error: {error}")
    else:
        report.say(f"detail: {error}")
    return EXIT_API_FAILURE


def _hint(status: int) -> str:
    return STATUS_HINTS.get(status, OTHER_STATUS_HINT)


def _video_problem(video: Path) -> str | None:
    if not video.is_file():
        return f"video {video} does not exist or is not a file"
    if video.suffix.lower() not in VIDEO_TYPES:
        return f"video {video.name} must be an .mp4 or .mov file"
    size = video.stat().st_size
    if size >= MAX_VIDEO_BYTES:
        return (
            f"video {video.name} is {size:,} bytes; "
            f"it must be under 100 MB ({MAX_VIDEO_BYTES:,} bytes)"
        )
    return None


def _noun_problem(noun: str) -> str | None:
    if not 1 <= len(noun) <= MAX_OBJECT_CHARS:
        return f"--object must be 1 to {MAX_OBJECT_CHARS} characters after trimming spaces"
    return None


def _data_url(video: Path) -> str:
    encoded = base64.b64encode(video.read_bytes()).decode("ascii")
    return f"data:{VIDEO_TYPES[video.suffix.lower()]};base64,{encoded}"


def _file_id(body: str) -> str | None:
    """The `id` field of a /files reply, or None if the reply has no usable one."""
    try:
        parsed: Any = json.loads(body)
    except json.JSONDecodeError:
        return None
    file_id = parsed.get("id") if isinstance(parsed, dict) else None
    return file_id if isinstance(file_id, str) and file_id else None


def _decimal(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not value.is_finite():
        raise argparse.ArgumentTypeError(f"{text!r} is not a finite number")
    return value


def _positive_decimal(text: str) -> Decimal:
    value = _decimal(text)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"{text!r} must be greater than 0")
    return value


def _non_negative_decimal(text: str) -> Decimal:
    value = _decimal(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"{text!r} must not be negative")
    return value


if __name__ == "__main__":
    sys.exit(main())
