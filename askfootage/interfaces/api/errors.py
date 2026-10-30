"""One error shape for every failure: {"error": {"code": ..., "message": ...}}.

Codes: validation_error 422, not_found 404, method_not_allowed 405, already_saved and
zone_name_taken 409, file_too_large 413, unsupported_media_type 415, internal_error 500.
Messages are fixed or built from our own words: they name the field at fault but never
repeat the rejected input, an exception's text, a stack trace, a server path or a key.
"""

from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from askfootage.application.errors import (
    AlreadySavedError,
    ApplicationError,
    InvalidInputError,
    NotFoundError,
    ZoneNameTakenError,
)
from askfootage.interfaces.api.schemas import ID_PATTERN, Error, ErrorDetail

logger = logging.getLogger("askfootage.api")

INTERNAL_ERROR_MESSAGE = "Something went wrong."
_MAX_REPORTED_PROBLEMS = 5
_SAFE_FIELD_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")
_REQUEST_PARTS = {"body", "query", "path", "header", "cookie"}

RESPONSE_DESCRIPTIONS: dict[int, str] = {
    404: (
        "No such camera, recording, clip, zone or saved clip, or no footage file (code not_found)"
    ),
    409: "The change clashes with existing data (code already_saved or zone_name_taken)",
    413: "The upload is over 200 MiB (code file_too_large)",
    415: "The upload is not an MP4 video (code unsupported_media_type)",
    422: (
        "A parameter or body field is missing or breaks a rule (code validation_error); "
        "the message names the field"
    ),
    500: "Something went wrong on the server (code internal_error); no details are exposed",
}


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI entries for these error statuses, each with the Error body."""
    return {
        status: {"model": Error, "description": RESPONSE_DESCRIPTIONS[status]}
        for status in statuses
    }


def json_error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Like error_responses(), for a route whose success response is not JSON.

    FastAPI documents a `model` under the route's own media type, which for the video
    route would claim its errors are video/mp4. Errors are always application/json, so
    the Error body is written out under that media type instead. (The Error component is
    still generated, because the other routes use error_responses().)
    """
    error_ref = {"$ref": "#/components/schemas/Error"}
    return {
        status: {
            "description": RESPONSE_DESCRIPTIONS[status],
            "content": {"application/json": {"schema": dict(error_ref)}},
        }
        for status in statuses
    }


class ApiError(Exception):
    """An HTTP-level refusal with its status, code and safe message (e.g. a bad upload)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(
    status_code: int, code: str, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    """A JSON response with the standard error body."""
    body = Error(error=ErrorDetail(code=code, message=message))
    return JSONResponse(body.model_dump(mode="json"), status_code=status_code, headers=headers)


def describe_validation_problems(problems: Iterable[Mapping[str, Any]]) -> str:
    """One message for pydantic/FastAPI validation errors, naming each field at fault.

    Built from the error type and the rule's limits only, never from the rejected input.
    """
    messages: list[str] = []
    for problem in problems:
        message = _describe_problem(problem)
        if message not in messages:
            messages.append(message)
    if not messages:
        return "The request is not valid."
    return "; ".join(messages[:_MAX_REPORTED_PROBLEMS])


def _describe_problem(problem: Mapping[str, Any]) -> str:
    kind = str(problem.get("type", ""))
    context = problem.get("ctx") or {}
    field = _field_name(problem.get("loc", ()))
    if kind == "json_invalid":
        return "body: is not valid JSON"
    if kind == "extra_forbidden":
        name = field.rsplit(".", 1)[-1]
        if _SAFE_FIELD_NAME.fullmatch(name):
            return f"{field}: is not an accepted field"
        return "body: contains a field that is not accepted"
    return f"{field}: {_describe_rule(kind, context, str(problem.get('msg', '')))}"


def _describe_rule(kind: str, context: Mapping[str, Any], fallback: str) -> str:
    limit = context.get("min_length", context.get("max_length"))
    rules = {
        "missing": "is required",
        "string_too_short": f"must be at least {limit} character{'' if limit == 1 else 's'}",
        "string_too_long": f"must be at most {limit} characters",
        "too_short": f"must have at least {limit} item{'' if limit == 1 else 's'}",
        "too_long": f"must have at most {limit} items",
        "greater_than_equal": f"must be at least {_number(context.get('ge'))}",
        "less_than_equal": f"must be at most {_number(context.get('le'))}",
        "finite_number": "must be a finite number",
        "float_type": "must be a number",
        "string_type": "must be text",
        "list_type": "must be a list",
        "tuple_type": "must be a list",
        "model_attributes_type": "must be a JSON object",
        "dict_type": "must be a JSON object",
        "date_from_datetime_parsing": "must be a valid date written YYYY-MM-DD",
        "date_parsing": "must be a valid date written YYYY-MM-DD",
    }
    if kind == "string_pattern_mismatch":
        if context.get("pattern") == ID_PATTERN:
            return "must be 1 to 64 letters, digits, '-' or '_'"
        return "has the wrong format"
    if kind in rules:
        return rules[kind]
    # Our own validators raise ValueError with a safe message; pydantic prefixes it.
    if kind == "value_error":
        return fallback.removeprefix("Value error, ")
    return "is not valid"


def _number(value: object) -> str:
    """A rule's limit as people write it: 1 rather than 1.0."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _field_name(location: Sequence[Any]) -> str:
    parts = list(location)
    if len(parts) > 1 and parts[0] in _REQUEST_PARTS:
        parts = parts[1:]
    name = ""
    for part in parts:
        if isinstance(part, int):
            name += f"[{part}]"
        else:
            name += f".{part}" if name else str(part)
    return name or "body"


# --- Exception handlers ---------------------------------------------------------------------

_HTTP_CODES = {
    404: ("not_found", "Not found."),
    405: ("method_not_allowed", "Method not allowed."),
    413: ("file_too_large", "The request is too large."),
    415: ("unsupported_media_type", "The request's media type is not supported."),
}


async def _on_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code >= 500:
        logger.error(
            "HTTP %s while serving %s %s", exc.status_code, request.method, request.url.path
        )
        return error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)
    code, message = _HTTP_CODES.get(
        exc.status_code, ("validation_error", "The request could not be processed.")
    )
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def _on_request_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(422, "validation_error", describe_validation_problems(exc.errors()))


async def _on_application_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApplicationError)
    if isinstance(exc, NotFoundError):
        return error_response(404, "not_found", exc.message)
    if isinstance(exc, InvalidInputError):
        return error_response(422, "validation_error", exc.message)
    if isinstance(exc, AlreadySavedError):
        return error_response(409, "already_saved", exc.message)
    if isinstance(exc, ZoneNameTakenError):
        return error_response(409, "zone_name_taken", exc.message)
    logger.error("Unmapped application error %s", type(exc).__name__)
    return error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)


async def _on_api_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return error_response(exc.status_code, exc.code, exc.message)


def install_error_handlers(app: FastAPI) -> None:
    """Map every expected failure to the standard error body."""
    app.add_exception_handler(StarletteHTTPException, _on_http_exception)
    app.add_exception_handler(RequestValidationError, _on_request_validation)
    app.add_exception_handler(ApplicationError, _on_application_error)
    app.add_exception_handler(ApiError, _on_api_error)


REDACTED = "[redacted]"


def redact(text: str, secrets: Iterable[str]) -> str:
    """The text with every secret in it replaced by [redacted]."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


class InternalErrorMiddleware:
    """Turn any unexpected exception into a 500 with the standard body, and log it here.

    It sits inside the CORS middleware, so the UI can read the 500 body too. The exception
    is logged server-side (type, message and traceback, never sent to the client) with
    every value in `secrets` (the API key) replaced by [redacted], and is not re-raised,
    so the response is never a stack trace.
    """

    def __init__(self, app: ASGIApp, secrets: Sequence[str] = ()) -> None:
        self.app = app
        self.secrets = tuple(secret for secret in secrets if secret)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve the request, answering 500 if the app raises before it starts a response."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_tracking_start(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking_start)
        except Exception as error:
            details = redact("".join(traceback.format_exception(error)), self.secrets)
            logger.error(
                "Unhandled error while serving %s %s\n%s",
                scope.get("method"),
                scope.get("path"),
                details,
            )
            if response_started:
                raise
            response = error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)
            await response(scope, receive, send)
