"""Port for perception: find and follow every object matching a noun through a video.

The SAM adapter (askfootage/adapters/meta/sam.py) will implement it after the API gate;
until then the API wires a perception that raises PerceptionNotConfiguredError.
Standard library and domain only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from askfootage.domain.tracks import Track

NOT_CONFIGURED_MESSAGE = "Indexing is not configured in this build"


class PerceptionError(Exception):
    """Perception could not produce tracks. The message is safe to show: no keys, no paths."""


class PerceptionNotConfiguredError(PerceptionError):
    """No perception backend is wired into this build."""

    def __init__(self, message: str = NOT_CONFIGURED_MESSAGE) -> None:
        super().__init__(message)


class Perception(Protocol):
    """Detects and tracks objects named by a noun."""

    def detect_and_track(self, video_path: Path, noun: str) -> list[Track]:
        """Tracks of every object matching `noun` in the prepared video at `video_path`.

        Every returned track has label == noun. Frames index the prepared video. An empty
        list means nothing matched. Raises PerceptionError when it cannot answer.
        """
        ...


class PerceptionNotSentError(PerceptionError):
    """The call failed before anything was sent to the paid service, so nothing was billed.

    An adapter raises this only when it is certain no request left the machine (bad
    arguments, missing file, refused locally). Any other failure is treated as possibly
    billed by BudgetedPerception.
    """
