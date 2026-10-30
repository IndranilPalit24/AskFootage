"""The 15 operations of contract/openapi.yaml, all under /api.

Each handler validates its input (path, query and body models), calls one application
use case and shapes the result into the contract's models. Failures are raised as
exceptions and turned into the standard error body by errors.py.

Handlers are async and call the store directly, on the event-loop thread. The store is a
small local SQLite file whose operations take about a millisecond, and running them one at
a time on the loop means no two of this process's writes ever wait on each other. The
SQLite store is also safe to share between threads, so moving the calls to a thread pool
(plain `def` handlers, or run_in_threadpool) is a safe change once any call can be slow,
for example when real video processing arrives. Until then, the only way a call waits is
another process holding the database's write lock (up to the store's busy timeout).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response

from askfootage.application import recordings, saved_clips, search, zones
from askfootage.application.errors import NotFoundError
from askfootage.interfaces.api.context import Context
from askfootage.interfaces.api.errors import error_responses, json_error_responses
from askfootage.interfaces.api.footage import VideoFileResponse
from askfootage.interfaces.api.schemas import (
    ID_PATTERN,
    Clip,
    Day,
    DaySummary,
    Recording,
    RecordingAccepted,
    SavedClip,
    SavedClipCreate,
    SavedClipUpdate,
    SearchRequest,
    SearchResponse,
    Status,
    Zone,
    ZoneCreate,
    ZoneUpdate,
)
from askfootage.interfaces.api.upload import MAX_UPLOAD_BYTES, read_upload

router = APIRouter(prefix="/api")

IdPath = Annotated[str, Path(pattern=ID_PATTERN)]
CameraQuery = Annotated[str, Query(pattern=ID_PATTERN, examples=["loading-dock"])]
OptionalCameraQuery = Annotated[str | None, Query(pattern=ID_PATTERN, examples=["loading-dock"])]
DayQuery = Annotated[Day, Query(examples=["2026-10-29"])]
OptionalDayQuery = Annotated[Day | None, Query(examples=["2026-10-29"])]

_MP4_SCHEMA: dict[str, Any] = {"type": "string", "contentMediaType": "video/mp4"}
_UPLOAD_LIMIT_MIB = MAX_UPLOAD_BYTES // (1024 * 1024)
_UPLOAD_BODY: dict[str, Any] = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["file", "day"],
                "properties": {
                    "file": {
                        **_MP4_SCHEMA,
                        "description": f"The video, MP4 only, at most {_UPLOAD_LIMIT_MIB} MiB",
                    },
                    "day": {
                        "type": "string",
                        "format": "date",
                        "description": "The day the footage was recorded",
                    },
                    "camera": {
                        "type": "string",
                        "pattern": ID_PATTERN,
                        "default": "loading-dock",
                        "description": "The camera that recorded it",
                    },
                },
            }
        }
    },
}


# --- Status, days and recordings --------------------------------------------------------------


@router.get(
    "/status",
    operation_id="getStatus",
    response_description="Current status",
    summary="Whether the app serves demo data, and the camera it covers",
    responses=error_responses(500),
)
async def get_status(context: Context) -> Status:
    """demoMode is always true in v1: the only data source is the seeded demo data."""
    return Status.from_status(recordings.get_status(context.library))


@router.get(
    "/days",
    operation_id="listDays",
    response_description="One entry per day",
    summary="Recording counts for the last 7 days, oldest first, ending today",
    description=(
        "Always returns exactly 7 entries; a day with no footage has recordings 0 and "
        "ready 0. The last entry is today (in demo mode, the demo dataset's today)."
    ),
    responses=error_responses(404, 422, 500),
)
async def list_days(camera: CameraQuery, context: Context) -> list[DaySummary]:
    """Recording counts for the 7 days ending today."""
    days = recordings.list_days(context.library, camera, context.today())
    return [DaySummary.from_port(day) for day in days]


@router.get(
    "/recordings",
    operation_id="listRecordings",
    response_description="Recordings ordered by startTime",
    summary="The recordings of one camera on one day, earliest first",
    responses=error_responses(404, 422, 500),
)
async def list_recordings(day: DayQuery, camera: CameraQuery, context: Context) -> list[Recording]:
    """One camera's recordings on one day, ordered by startTime."""
    found = recordings.list_recordings(context.library, camera, day)
    return [Recording.from_port(recording) for recording in found]


@router.post(
    "/recordings",
    operation_id="addRecording",
    response_description="Accepted; the recording now waits to be processed",
    status_code=202,
    summary="Upload a video file as a new recording",
    description=(
        f"Accepts one MP4 file of at most {_UPLOAD_LIMIT_MIB} MiB. The recording is "
        "registered with status waiting, startTime 00:00:00 and lengthSeconds 0. In v1 "
        "(demo mode) the file is checked and registered but not stored or processed. "
        "Not idempotent: sending the same file again registers another recording."
    ),
    responses=error_responses(404, 413, 415, 422, 500),
    openapi_extra={"requestBody": _UPLOAD_BODY},
)
async def add_recording(request: Request, context: Context) -> RecordingAccepted:
    """Check the uploaded MP4 while it streams in, drop it, and register the recording."""
    upload = await read_upload(request, context.max_upload_bytes)
    recording = recordings.register_upload(
        context.library, upload.fields.camera, upload.fields.day, make_id=context.make_id
    )
    return RecordingAccepted(id=recording.id, status="waiting")


@router.get(
    "/recordings/{id}/video",
    operation_id="getRecordingVideo",
    status_code=200,
    summary="Stream the recording's video",
    description=(
        "Streams the footage file (in demo mode, videos/clip1.mp4 for every recording), "
        "with HTTP Range support so a player can seek."
    ),
    response_class=VideoFileResponse,
    responses={
        200: {"description": "The video", "content": {"video/mp4": {"schema": _MP4_SCHEMA}}},
        206: {
            "description": "Part of the video, for a Range request",
            "content": {"video/mp4": {"schema": _MP4_SCHEMA}},
        },
        **json_error_responses(404, 422, 500),
    },
)
async def get_recording_video(id: IdPath, context: Context) -> VideoFileResponse:
    """The recording's footage file; 404 when the recording or its file is missing."""
    path = recordings.find_footage(context.library, context.footage, id)
    try:
        stat_result = path.stat()
    except OSError:
        raise NotFoundError("Footage file not attached.") from None
    return VideoFileResponse(path, stat_result)


# --- Search and clips ---------------------------------------------------------------------------


@router.post(
    "/search",
    operation_id="search",
    response_description="The matching clips, earliest first",
    summary="Answer a question about one day of one camera's footage",
    description=(
        "Synchronous in v1. Only ready recordings are searched; note explains anything the "
        "answer left out, and is null when there is nothing to add."
    ),
    responses=error_responses(404, 422, 500),
)
async def search_footage(body: SearchRequest, context: Context) -> SearchResponse:
    """The clips that answer the question, earliest first."""
    result = search.search_day(
        context.library, context.interpreter, body.question, body.day, body.camera
    )
    return SearchResponse.from_result(result)


@router.get(
    "/clips/{id}",
    operation_id="getClip",
    response_description="The clip",
    summary="One clip with its evidence",
    responses=error_responses(404, 422, 500),
)
async def get_clip(id: IdPath, context: Context) -> Clip:
    """One clip with its evidence."""
    return Clip.from_port(recordings.get_clip(context.library, id))


# --- Zones ------------------------------------------------------------------------------------


@router.get(
    "/zones",
    operation_id="listZones",
    response_description="The zones",
    summary="All zones, or only one camera's, ordered by name",
    responses=error_responses(422, 500),
)
async def list_zones(context: Context, camera: OptionalCameraQuery = None) -> list[Zone]:
    """All zones, or only one camera's, ordered by name."""
    return [Zone.from_port(zone) for zone in zones.list_zones(context.library, camera)]


@router.post(
    "/zones",
    operation_id="createZone",
    response_description="The new zone",
    status_code=201,
    summary="Draw a new zone on a camera's view",
    responses=error_responses(404, 409, 422, 500),
)
async def create_zone(body: ZoneCreate, context: Context) -> Zone:
    """Create a zone; its id is chosen by the server."""
    zone = zones.create_zone(
        context.library, body.camera, body.name, body.points, make_id=context.make_id
    )
    return Zone.from_port(zone)


@router.put(
    "/zones/{id}",
    operation_id="replaceZone",
    response_description="The zone after the change",
    summary="Rename or redraw a zone",
    responses=error_responses(404, 409, 422, 500),
)
async def replace_zone(id: IdPath, body: ZoneUpdate, context: Context) -> Zone:
    """Replace a zone's name and points."""
    return Zone.from_port(zones.replace_zone(context.library, id, body.name, body.points))


@router.delete(
    "/zones/{id}",
    operation_id="deleteZone",
    response_description="Deleted",
    status_code=204,
    response_class=Response,
    summary="Delete a zone",
    responses=error_responses(404, 422, 500),
)
async def delete_zone(id: IdPath, context: Context) -> Response:
    """Delete a zone."""
    zones.delete_zone(context.library, id)
    return Response(status_code=204)


# --- Saved clips ------------------------------------------------------------------------------


@router.get(
    "/saved-clips",
    operation_id="listSavedClips",
    response_description="The saved clips",
    summary="Saved clips, newest save first, optionally only those from one day",
    responses=error_responses(422, 500),
)
async def list_saved_clips(context: Context, day: OptionalDayQuery = None) -> list[SavedClip]:
    """Saved clips, newest save first."""
    found = saved_clips.list_saved_clips(context.library, day)
    return [SavedClip.from_port(saved) for saved in found]


@router.post(
    "/saved-clips",
    operation_id="saveClip",
    response_description="The saved clip",
    status_code=201,
    summary="Save a clip with a note",
    description="A clip can be saved once; saving it again returns 409 with code already_saved.",
    responses=error_responses(404, 409, 422, 500),
)
async def save_clip(body: SavedClipCreate, context: Context) -> SavedClip:
    """Save a clip; its id and savedAt are set by the server."""
    saved = saved_clips.save_clip(
        context.library, body.clip_id, body.note, context.utc_now(), make_id=context.make_id
    )
    return SavedClip.from_port(saved)


@router.patch(
    "/saved-clips/{id}",
    operation_id="updateSavedClip",
    response_description="The saved clip after the change",
    summary="Change a saved clip's note",
    responses=error_responses(404, 422, 500),
)
async def update_saved_clip(id: IdPath, body: SavedClipUpdate, context: Context) -> SavedClip:
    """Replace a saved clip's note."""
    return SavedClip.from_port(saved_clips.update_note(context.library, id, body.note))


@router.delete(
    "/saved-clips/{id}",
    operation_id="deleteSavedClip",
    response_description="Removed",
    status_code=204,
    response_class=Response,
    summary="Remove a clip from the saved list",
    responses=error_responses(404, 422, 500),
)
async def delete_saved_clip(id: IdPath, context: Context) -> Response:
    """Remove a clip from the saved list (the clip itself stays)."""
    saved_clips.delete_saved_clip(context.library, id)
    return Response(status_code=204)
