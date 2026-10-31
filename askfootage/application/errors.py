"""Errors the use cases raise. Each message is plain English, safe to show to a person.

No message ever repeats the rejected input, a server path or a key: the HTTP layer passes
them to clients as they are.
"""

from __future__ import annotations

from askfootage.ports.perception import NOT_CONFIGURED_MESSAGE


class ApplicationError(Exception):
    """A use case refused a request; `message` is safe to show to a person."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(ApplicationError):
    """The camera, recording, clip, zone, saved clip or footage file does not exist."""


class ConflictError(ApplicationError):
    """The change clashes with data that already exists."""


class AlreadySavedError(ConflictError):
    """The clip is already in the saved list; a clip can be saved once."""


class ZoneNameTakenError(ConflictError):
    """The camera already has a zone with this name (names are compared ignoring case)."""


class CameraNameTakenError(ConflictError):
    """Another camera already has this name (names are compared ignoring case)."""


class RecordingNotWaitingError(ConflictError):
    """Only a recording with status waiting can be indexed; this one is busy or done."""

    def __init__(self, message: str = "The recording is not waiting to be indexed.") -> None:
        super().__init__(message)


class RecordingNotReadyError(ConflictError):
    """The recording must be ready (indexed) first."""

    def __init__(self, message: str = "The recording is not ready yet.") -> None:
        super().__init__(message)


class IndexingNotConfiguredError(ApplicationError):
    """This build has no way to find objects in video, so indexing cannot start."""

    def __init__(self, message: str = NOT_CONFIGURED_MESSAGE) -> None:
        super().__init__(message)


class IndexingFailedError(ApplicationError):
    """Finding or saving objects failed; the message is a fixed phrase, never the cause's text."""


class InvalidInputError(ApplicationError):
    """An input broke a rule; `field` names it and the message says which rule."""

    def __init__(self, field: str, problem: str) -> None:
        super().__init__(f"{field}: {problem}")
        self.field = field
        self.problem = problem
