"""A size limit for request bodies other than the upload, so no request can make the server
buffer much memory.

Every JSON body the contract accepts is small: a question of at most 300 characters, a
zone of at most 50 points, a note of at most 500 characters. MAX_JSON_BODY_BYTES (64 KiB)
fits all of them even written entirely in JSON escapes. A bigger body is refused with 422
validation_error ("body: is too large"), the status every JSON-body route already
documents, before the app parses any of it: a declared Content-Length over the limit is
refused without reading the body, and a body without one is cut off as soon as it passes
the limit.

The upload (POST /api/recordings) is left alone: upload.py streams it and enforces its own
200 MiB limit.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from askfootage.interfaces.api.errors import error_response

MAX_JSON_BODY_BYTES = 64 * 1024
"""Largest request body accepted on every route but the upload: 64 KiB."""
UPLOAD_PATH = "/api/recordings"
"""The upload route's path; a POST to it is limited by upload.py instead."""

_METHODS_WITH_BODY = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class BodyLimitMiddleware:
    """Refuse request bodies over a limit with the standard 422 body; let the rest through.

    A body within the limit is read here and handed to the app unchanged.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int = MAX_JSON_BODY_BYTES) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check the body's size, then serve the request with the body replayed."""
        if not self._is_limited(scope):
            await self.app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > self.max_body_bytes:
            await self._refuse(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return  # The client left; there is nobody to answer.
            body += message.get("body", b"")
            if len(body) > self.max_body_bytes:
                await self._refuse(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_body() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_body, send)

    @staticmethod
    def _is_limited(scope: Scope) -> bool:
        if scope["type"] != "http" or scope["method"] not in _METHODS_WITH_BODY:
            return False
        is_upload = scope["method"] == "POST" and scope["path"].rstrip("/") == UPLOAD_PATH
        return not is_upload

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send) -> None:
        response = error_response(422, "validation_error", "body: is too large")
        await response(scope, receive, send)
