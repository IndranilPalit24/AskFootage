"""What every Meta API transport shares: the request, the raw reply and the errors.

A transport sends one MetaRequest and returns the reply as a RawResponse, unparsed. The
live client (client.py) and the record-and-replay transports (record_replay.py) all
implement the Transport protocol, so code that calls the Meta API can be handed any of
them: a replay in tests and demo mode, the live client for real runs.

This module uses only the standard library, so the replay side never imports httpx.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

BODY_EXCERPT_LIMIT = 300
"""Most characters of a reply body that a MetaApiError quotes."""


@dataclass(frozen=True, slots=True)
class FileUpload:
    """A local file for the Files API, and the `purpose` form field sent with it."""

    path: Path
    purpose: str


@dataclass(frozen=True, slots=True)
class MetaRequest:
    """One Meta API call: a path under the base URL, plus a JSON body or a file upload.

    `path` starts with "/", for example "/responses". Give exactly one of `json_body`
    (sent as JSON) and `upload` (sent as a multipart file upload).
    """

    path: str
    json_body: Mapping[str, Any] | None = None
    upload: FileUpload | None = None

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError(f"path must start with '/'; got {self.path!r}")
        if (self.json_body is None) == (self.upload is None):
            raise ValueError("give exactly one of json_body or upload")


@dataclass(frozen=True, slots=True)
class RawResponse:
    """A reply as the server sent it: the HTTP status and the whole body as text, unparsed."""

    status: int
    body: str


class Transport(Protocol):
    """Anything that sends a MetaRequest and returns the raw reply.

    Implementations raise a MetaError subclass when they cannot produce a usable reply.
    """

    def send(self, request: MetaRequest) -> RawResponse:
        """Send `request` and return the reply."""


class MetaError(Exception):
    """Base class for every failure to get a reply from the Meta API, live or replayed."""


class MetaApiError(MetaError):
    """The Meta API answered with an error status, or still answered 429 after every retry.

    `status` is the HTTP status and `body_excerpt` the start of the reply body, at most
    BODY_EXCERPT_LIMIT characters. Pass a body with the key already scrubbed out: the cut
    happens after scrubbing, so no fragment of a key can survive at the edge.
    """

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body_excerpt = body[:BODY_EXCERPT_LIMIT]
        super().__init__(f"Meta API returned HTTP {status}: {self.body_excerpt}")


class MetaConnectionError(MetaError):
    """The Meta API could not be reached, or the connection failed before a reply arrived."""


class RecordingNotFoundError(MetaError):
    """A replay was asked for a request that has never been recorded."""


class RecordingCorruptError(MetaError):
    """A recording exists but is not valid JSON or lacks a required field."""
