"""Record-and-replay transports, so tests and demo mode run without a key or a network.

Each request is identified by its fingerprint: a SHA-256 of the request's path, its JSON
body and, for an upload, the uploaded file's content hash and purpose. Headers and the API
key are never part of it, so a recording made with one key replays with any key, or none.

- ReplayTransport answers from saved recordings only and never touches the network.
- RecordingTransport wraps a live transport. It answers from a saved recording when there
  is one; otherwise it calls the live side and saves a successful (2xx) reply for next time.

A recording is `<directory>/<fingerprint>.json`: UTF-8 JSON, indented by 2, with LF line
endings on every OS, holding the fields fingerprint, path, status and body.
"""

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from askfootage.adapters.meta.transport import (
    MetaRequest,
    RawResponse,
    RecordingCorruptError,
    RecordingNotFoundError,
    Transport,
)


def fingerprint(request: MetaRequest) -> str:
    """The SHA-256 hex digest that names `request`'s recording.

    It hashes compact, key-sorted JSON of the path, the JSON body and, for an upload, the
    SHA-256 of the file's bytes plus its purpose. Key order in the body and the file's name
    do not change it, and nothing else about a call, such as its headers, is an input.
    """
    upload: dict[str, str] | None = None
    if request.upload is not None:
        with request.upload.path.open("rb") as file:
            content_hash = hashlib.file_digest(file, "sha256").hexdigest()
        upload = {"sha256": content_hash, "purpose": request.upload.purpose}
    canonical = json.dumps(
        {"path": request.path, "json_body": request.json_body, "upload": upload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ReplayTransport:
    """Answers every request from `<directory>/<fingerprint>.json`; never uses the network.

    Raises RecordingNotFoundError for a request that was never recorded, and
    RecordingCorruptError when its recording cannot be read.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def send(self, request: MetaRequest) -> RawResponse:
        """Return the saved reply for `request`."""
        request_fingerprint = fingerprint(request)
        recording = self._directory / f"{request_fingerprint}.json"
        if not recording.is_file():
            raise RecordingNotFoundError(
                f"No recording of {request.path} request {request_fingerprint} in "
                f"{self._directory}. To record it, send the same request once through "
                f"RecordingTransport with a live key; that saves {recording.name} there."
            )
        return _load(recording, request_fingerprint)


class RecordingTransport:
    """Wraps a live transport and saves its successful replies for ReplayTransport.

    A request that already has a recording is answered from it without calling `inner`, so
    re-running costs nothing; pass refresh=True to call `inner` again and overwrite it.
    Only 2xx replies are saved: anything else is returned (or raised) as usual but never
    recorded, so a replay cannot repeat a failure. `redact(request, body)`, when given, turns
    a reply's body into what is saved while the caller still gets the full reply; the
    fingerprint is of the request, so a redacted recording replays like any other. If
    `redact` raises, nothing is saved and the error propagates. A damaged recording raises
    RecordingCorruptError rather than being silently paid for again: delete it, or refresh.
    """

    def __init__(
        self,
        inner: Transport,
        directory: Path,
        *,
        refresh: bool = False,
        redact: Callable[[MetaRequest, str], str] | None = None,
    ) -> None:
        self._inner = inner
        self._directory = directory
        self._refresh = refresh
        self._redact = redact

    def send(self, request: MetaRequest) -> RawResponse:
        """Return the saved reply for `request`, or get it from `inner` and save it if 2xx."""
        request_fingerprint = fingerprint(request)
        recording = self._directory / f"{request_fingerprint}.json"
        if recording.is_file() and not self._refresh:
            return _load(recording, request_fingerprint)
        reply = self._inner.send(request)
        if 200 <= reply.status < 300:
            body = reply.body if self._redact is None else self._redact(request, reply.body)
            record = {
                "fingerprint": request_fingerprint,
                "path": request.path,
                "status": reply.status,
                "body": body,
            }
            _save_atomically(recording, record)
        return reply


def _load(recording: Path, expected_fingerprint: str) -> RawResponse:
    try:
        record = json.loads(recording.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecordingCorruptError(
            f"Recording {recording} is not valid UTF-8 JSON ({error}); "
            "delete it or re-record with refresh=True"
        ) from error
    if not (
        isinstance(record, dict)
        and record.get("fingerprint") == expected_fingerprint
        and isinstance(record.get("status"), int)
        and isinstance(record.get("body"), str)
    ):
        raise RecordingCorruptError(
            f"Recording {recording} lacks a matching fingerprint, a whole-number status or a "
            "text body; delete it or re-record with refresh=True"
        )
    return RawResponse(record["status"], record["body"])


def _save_atomically(recording: Path, record: dict[str, object]) -> None:
    # Written to a temp file beside the target, then swapped in with os.replace, so a
    # reader sees the old recording or the new one, never half of one.
    recording.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=recording.parent, prefix=f".{recording.stem}.", suffix=".tmp"
    )
    try:
        with open(handle, "w", encoding="utf-8", newline="\n") as file:
            json.dump(record, file, indent=2)
            file.write("\n")
        os.replace(temp_name, recording)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
