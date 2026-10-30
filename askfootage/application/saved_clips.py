"""Use cases for saved clips: clips the user kept, each with a note."""

from __future__ import annotations

from datetime import UTC, date, datetime

from askfootage.application.errors import AlreadySavedError, InvalidInputError, NotFoundError
from askfootage.application.library import IdFactory, Library, new_id
from askfootage.ports.library_store import DuplicateError, MissingReferenceError, SavedClip

MAX_NOTE_LENGTH = 500
"""Longest note accepted, in characters."""

_ALREADY_SAVED = "This clip is already saved."


def check_note(note: str) -> str:
    """The note unchanged; raises InvalidInputError if it is too long."""
    if len(note) > MAX_NOTE_LENGTH:
        raise InvalidInputError("note", f"must be at most {MAX_NOTE_LENGTH} characters")
    return note


def list_saved_clips(library: Library, day: date | None = None) -> list[SavedClip]:
    """Saved clips, newest save first, then id; only clips from `day` when it is given."""
    saved = library.saved_clips.list_saved_clips(day)
    newest_first = sorted(saved, key=lambda item: item.id)
    newest_first.sort(key=lambda item: item.saved_at, reverse=True)
    return newest_first


def save_clip(
    library: Library,
    clip_id: str,
    note: str,
    now: datetime,
    *,
    make_id: IdFactory = new_id,
) -> SavedClip:
    """Save a clip with a note, stamped with `now` in UTC to the whole second.

    Raises InvalidInputError for a bad note, NotFoundError for an unknown clip and
    AlreadySavedError when the clip is already saved.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    note = check_note(note)
    if library.clips.get_clip(clip_id) is None:
        raise NotFoundError("Clip not found.")
    if _is_saved(library, clip_id):
        raise AlreadySavedError(_ALREADY_SAVED)
    saved_at = now.astimezone(UTC).replace(microsecond=0)
    try:
        return library.saved_clips.add_saved_clip(make_id("saved"), clip_id, note, saved_at)
    except MissingReferenceError:
        raise NotFoundError("Clip not found.") from None
    except DuplicateError:
        if _is_saved(library, clip_id):
            raise AlreadySavedError(_ALREADY_SAVED) from None
        raise


def update_note(library: Library, saved_id: str, note: str) -> SavedClip:
    """Change a saved clip's note; raises NotFoundError when it is not saved."""
    note = check_note(note)
    saved = library.saved_clips.update_note(saved_id, note)
    if saved is None:
        raise NotFoundError("Saved clip not found.")
    return saved


def delete_saved_clip(library: Library, saved_id: str) -> None:
    """Remove a clip from the saved list; raises NotFoundError when it is not saved."""
    if not library.saved_clips.delete_saved_clip(saved_id):
        raise NotFoundError("Saved clip not found.")


def _is_saved(library: Library, clip_id: str) -> bool:
    return any(saved.clip.id == clip_id for saved in library.saved_clips.list_saved_clips())
