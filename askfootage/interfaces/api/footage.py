"""Serving footage: which file plays for a recording, and a video response that seeks.

The file is always chosen by the server. No part of the request (not the id, not a
filename) is ever turned into a path.
"""

from __future__ import annotations

import os
from pathlib import Path

from starlette.datastructures import Headers
from starlette.responses import FileResponse, MalformedRangeHeader, RangeNotSatisfiable
from starlette.types import Receive, Scope, Send

from askfootage.ports.library_store import Recording

DEMO_VIDEO_NAME = "clip1.mp4"
"""In demo mode every recording plays this one file from the videos folder."""


class DemoFootageSource:
    """Demo mode: every known recording plays <videos_dir>/clip1.mp4, when that file exists."""

    def __init__(self, videos_dir: Path) -> None:
        self._video = videos_dir / DEMO_VIDEO_NAME

    def footage_for(self, recording: Recording) -> Path | None:
        """The demo video, or None when it is not there."""
        return self._video if self._video.is_file() else None


class VideoFileResponse(FileResponse):
    """An MP4 file response with Range support (206 for one range the file can serve).

    A Range header the file cannot serve (malformed, past the end, or asking for several
    ranges at once) is ignored and the whole file is sent with 200, as RFC 9110 allows.
    That keeps every response either video/mp4 or the standard JSON error: never
    Starlette's plain-text 400 or 416, and never a multipart/byteranges body.
    """

    media_type = "video/mp4"

    def __init__(self, path: Path, stat_result: os.stat_result) -> None:
        super().__init__(path, media_type="video/mp4", stat_result=stat_result)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Send the file, dropping a Range header that cannot be served."""
        range_header = Headers(scope=scope).get("range")
        if range_header is not None and not self._can_serve(range_header):
            scope = dict(scope)
            scope["headers"] = [
                (name, value) for name, value in scope["headers"] if name.lower() != b"range"
            ]
        await super().__call__(scope, receive, send)

    def _can_serve(self, range_header: str) -> bool:
        assert self.stat_result is not None
        try:
            ranges = self._parse_range_header(range_header, self.stat_result.st_size)
        except (MalformedRangeHeader, RangeNotSatisfiable):
            return False
        return len(ranges) == 1
