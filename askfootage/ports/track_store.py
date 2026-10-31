"""Port for storing object tracks per video.

A video here is a recording: video_id is the recording's id. askfootage/adapters/sqlite
implements this Protocol; the application layer and tests use it through this interface.
Standard library and domain only.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from askfootage.domain.tracks import Track


class TrackStore(Protocol):
    """Tracks found in each video, grouped by the concept (object noun) they were found for."""

    def save_tracks(self, video_id: str, concept: str, tracks: Sequence[Track]) -> None:
        """Replace every track saved for this video and concept with `tracks`, atomically.

        Every track's label must equal `concept` and track ids must be unique, else
        ValueError (nothing is written). An empty `tracks` clears the concept. Raises
        askfootage.ports.library_store.MissingReferenceError if the video does not exist.
        """
        ...

    def tracks_for(self, video_id: str, label: str) -> list[Track]:
        """Tracks of this video with this label, ordered by track_id, points by frame.

        An unknown video or label returns an empty list.
        """
        ...

    def delete_video(self, video_id: str) -> int:
        """Remove every track of this video; returns how many tracks were removed."""
        ...
