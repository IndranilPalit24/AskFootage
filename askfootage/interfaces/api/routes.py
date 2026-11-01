"""The 22 operations of contract/openapi.yaml, all under /api.

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

Indexing is the one slow job: its route only claims the recording and replies 202; the
work itself is handed to context.schedule_after_reply, which by default runs it after the
reply in FastAPI's thread pool.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Path, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BeforeValidator

from askfootage.application import cameras, ingest_video, recordings, saved_clips, search, zones
from askfootage.application.errors import NotFoundError
from askfootage.interfaces.api.context import Context, snapshot_url_of
from askfootage.interfaces.api.errors import error_responses, json_error_responses
from askfootage.interfaces.api.footage import VideoFileResponse
from askfootage.interfaces.api.schemas import (
    ID_PATTERN,
    Camera,
    CameraCreate,
    CameraUpdate,
    Clip,
    Day,
    DaySummary,
    IndexAccepted,
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
OptionalCameraQuery = Annotated[
    str | None,
    Query(
        pattern=ID_PATTERN,
        description="A camera id; leave it out for all cameras",
        examples=["CAM-001"],
    ),
]


def _exactly_true_or_false(value: object) -> object:
    """Accept only the text true or false (pydantic would also take 1, yes, on, ...)."""
    if value is True or value is False or value in ("true", "false"):
        return value
    raise ValueError("must be true or false")


DeleteRecordingsQuery = Annotated[
    bool,
    BeforeValidator(_exactly_true_or_false),
    Query(
        alias="deleteRecordings",
        description=(
            "True to delete the camera together with its recordings, clips, saved clips and "
            "zones; false (the default) refuses when the camera has recordings"
        ),
        examples=[False],
    ),
]
DayQuery = Annotated[Day, Query(examples=["2026-10-29"])]
OptionalDayQuery = Annotated[Day | None, Query(examples=["2026-10-29"])]

_MP4_SCHEMA: dict[str, Any] = {"type": "string", "contentMediaType": "video/mp4"}
_JPEG_SCHEMA: dict[str, Any] = {"type": "string", "contentMediaType": "image/jpeg"}
_UPLOAD_LIMIT_MIB = MAX_UPLOAD_BYTES // (1024 * 1024)
_UPLOAD_BODY: dict[str, Any] = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["file", "day", "camera"],
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
                        "description": (
                            "The id of the camera that recorded it, for example CAM-001"
                        ),
                    },
                },
            }
        }
    },
}


# --- Status -----------------------------------------------------------------------------------


@router.get(
    "/status",
    operation_id="getStatus",
    response_description="Current status",
    summary="Whether the app serves demo data",
    responses=error_responses(500),
)
async def get_status() -> Status:
    """demoMode is always true in v1: the only data source is the seeded demo data."""
    return Status.from_status(recordings.get_status())


# --- Cameras ----------------------------------------------------------------------------------


@router.get(
    "/cameras",
    operation_id="listCameras",
    response_description="The cameras",
    summary="Every camera, in id order (creation order)",
    responses=error_responses(500),
)
async def list_cameras(context: Context) -> list[Camera]:
    """Every camera with its counts; never a password."""
    return [Camera.from_overview(found) for found in cameras.list_cameras(context.library)]


@router.post(
    "/cameras",
    operation_id="addCamera",
    response_description="The new camera",
    status_code=201,
    summary="Add a camera to the registry",
    description=(
        "The server gives the camera the next id (CAM-001, CAM-002, ...; a number is never "
        "reused, even after a delete) and status online. There is no limit on how many "
        "cameras can be added. The password is checked for length and then dropped: it is "
        "not stored, not returned and not logged. A name that another camera already has, "
        "ignoring case, returns 409 with code camera_name_taken."
    ),
    responses=error_responses(409, 422, 500),
)
async def add_camera(body: CameraCreate, context: Context) -> Camera:
    """Add a camera; its id, status and createdAt are set by the server."""
    added = cameras.add_camera(context.library, body.to_draft(), context.utc_now())
    return Camera.from_overview(added)


@router.get(
    "/cameras/{id}",
    operation_id="getCamera",
    response_description="The camera",
    summary="One camera",
    responses=error_responses(404, 422, 500),
)
async def get_camera(id: IdPath, context: Context) -> Camera:
    """One camera with its counts."""
    return Camera.from_overview(cameras.get_camera(context.library, id))


@router.patch(
    "/cameras/{id}",
    operation_id="updateCamera",
    response_description="The camera after the change",
    summary="Change a camera's status",
    responses=error_responses(404, 422, 500),
)
async def update_camera(id: IdPath, body: CameraUpdate, context: Context) -> Camera:
    """Change a camera's status; nothing else about it can change."""
    return Camera.from_overview(cameras.set_camera_status(context.library, id, body.status))


@router.delete(
    "/cameras/{id}",
    operation_id="deleteCamera",
    response_description="Deleted",
    status_code=204,
    response_class=Response,
    summary="Delete a camera and everything recorded on it",
    description=(
        "A camera with no recordings is deleted at once (204), whatever deleteRecordings "
        "says; its zones go with it. A camera with one or more recordings is not deleted "
        "unless deleteRecordings is true: the answer is 409 with code camera_has_recordings "
        "and a message that says how many recordings and saved clips it has, and nothing is "
        "changed. With deleteRecordings=true the camera is deleted together with its "
        "recordings, their clips, the saved clips and its zones. A second delete of the same "
        "camera returns 404. deleteRecordings must be exactly true or false; any other value "
        "returns 422."
    ),
    responses=error_responses(404, 409, 422, 500),
)
async def delete_camera(
    id: IdPath, context: Context, delete_recordings: DeleteRecordingsQuery = False
) -> Response:
    """Delete a camera; with recordings it needs deleteRecordings=true."""
    cameras.delete_camera(context.library, id, delete_recordings=delete_recordings)
    return Response(status_code=204)


# --- Days and recordings ----------------------------------------------------------------------


@router.get(
    "/days",
    operation_id="listDays",
    response_description="One entry per day",
    summary="Recording counts for the last 7 days, oldest first, ending today",
    description=(
        "Always returns exactly 7 entries; a day with no footage has recordings 0 and "
        "ready 0. Without camera, the counts cover all cameras. The last entry is today on "
        "the server's clock (in demo mode, the demo dataset's today), so a client can use it "
        "as the default day."
    ),
    responses=error_responses(404, 422, 500),
)
async def list_days(context: Context, camera: OptionalCameraQuery = None) -> list[DaySummary]:
    """Recording counts for the 7 days ending today, for one camera or all of them."""
    days = recordings.list_days(context.library, camera, context.today())
    return [DaySummary.from_port(day) for day in days]


@router.get(
    "/recordings",
    operation_id="listRecordings",
    response_description="Recordings ordered by startTime",
    summary="The recordings on one day, earliest first",
    description=(
        "Without camera, lists every camera's recordings, ordered by startTime, then camera, "
        "then id."
    ),
    responses=error_responses(404, 422, 500),
)
async def list_recordings(
    day: DayQuery, context: Context, camera: OptionalCameraQuery = None
) -> list[Recording]:
    """The recordings on one day, from one camera or all of them, ordered by startTime."""
    found = recordings.list_recordings(context.library, camera, day)
    return [Recording.from_port(recording) for recording in found]


@router.post(
    "/recordings",
    operation_id="addRecording",
    response_description="Accepted; the recording now waits to be processed",
    status_code=202,
    summary="Upload a video file as a new recording of one camera",
    description=(
        f"Accepts one MP4 file of at most {_UPLOAD_LIMIT_MIB} MiB. The recording is "
        "registered with status waiting, startTime 00:00:00 and lengthSeconds 0; processing "
        "fills those in later. In v1 (demo mode) the file is checked and registered but not "
        "stored or processed. Not idempotent: sending the same file again registers another "
        "recording."
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
        "Streams the footage file (in demo mode, videos/clip1.mp4 for every recording). "
        "Supports HTTP Range requests so a player can seek. Returns 404 with the standard "
        "error body when the recording is unknown or no footage file is attached."
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


@router.post(
    "/recordings/{id}/index",
    operation_id="indexRecording",
    response_description="Accepted; the recording is now being prepared",
    status_code=202,
    summary="Start indexing a recording so it becomes searchable",
    description=(
        "Only a recording with status waiting can be indexed. On acceptance its status "
        "becomes preparing and the work continues after the reply: preparing (making the "
        "working copy), then indexing (finding objects), then ready. If the work fails, the "
        "status goes back to waiting so it can be retried. No request body. Not idempotent: "
        "a second call while the first is still running returns 409. When this build has no "
        "indexing backend, the reply is 503 with code indexing_not_configured and nothing "
        "changes."
    ),
    responses=error_responses(404, 409, 422, 500, 503),
)
async def index_recording(
    id: IdPath, context: Context, background: BackgroundTasks
) -> IndexAccepted:
    """Claim a waiting recording (now preparing) and index it after the reply."""
    job = ingest_video.start_indexing(context.library, context.indexing, id)
    context.schedule_after_reply(background, job.run)
    return IndexAccepted(id=job.recording.id, status="preparing")


# --- Search and clips ---------------------------------------------------------------------------


@router.post(
    "/search",
    operation_id="search",
    response_description="The matching clips, earliest first",
    summary="Answer a question about one day of footage, from one camera or all of them",
    description=(
        "Synchronous in v1. Without camera, every camera's footage is searched. Only ready "
        "recordings are searched; note explains anything the answer left out (for example a "
        "recording still being indexed), and is null when there is nothing to add. clips is "
        "empty when nothing matched. Clips found from stored object tracks have an entry in "
        "proofs (relation, interval, track ids, measures, boxes); the rest come from the "
        "demo keyword search and have none."
    ),
    responses=error_responses(404, 422, 500),
)
async def search_footage(body: SearchRequest, context: Context) -> SearchResponse:
    """The clips that answer the question, earliest first."""
    result = search.search_day(
        context.library,
        context.interpreter,
        body.question,
        body.day,
        body.camera,
        tracks=context.tracks,
        parser=context.question_parser,
        frame_size=context.frame_size,
        snapshots=context.snapshots,
    )
    return SearchResponse.from_result(result, snapshot_url_of(context))


@router.get(
    "/clips/{id}",
    operation_id="getClip",
    response_description="The clip",
    summary="One clip with its evidence",
    responses=error_responses(404, 422, 500),
)
async def get_clip(id: IdPath, context: Context) -> Clip:
    """One clip with its evidence and its camera."""
    found = recordings.get_clip(context.library, id)
    return Clip.from_port(found.clip, found.camera, snapshot_url_of(context))


@router.get(
    "/clips/{id}/snapshot",
    operation_id="getClipSnapshot",
    status_code=200,
    summary="The evidence snapshot of a clip",
    description=(
        "A JPEG of the frame where the match began, with the object's box drawn in red and "
        "the person's box in a neutral grey. Made when a search finds the clip from stored "
        "object tracks. Returns 404 with the standard error body when the clip is unknown or "
        "has no snapshot."
    ),
    response_class=FileResponse,
    responses={
        200: {"description": "The snapshot", "content": {"image/jpeg": {"schema": _JPEG_SCHEMA}}},
        **json_error_responses(404, 422, 500),
    },
)
async def get_clip_snapshot(id: IdPath, context: Context) -> FileResponse:
    """The clip's evidence snapshot; 404 when the clip or its snapshot does not exist."""
    recordings.get_clip(context.library, id)
    snapshots = context.snapshots
    if snapshots is None or not snapshots.has(id):
        raise NotFoundError("Snapshot not found.")
    return FileResponse(snapshots.path_for(id), media_type="image/jpeg")


# --- Zones ------------------------------------------------------------------------------------


@router.get(
    "/zones",
    operation_id="listZones",
    response_description="The zones",
    summary="All zones, or only one camera's, ordered by name",
    responses=error_responses(404, 422, 500),
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
    description=(
        "Zone names are unique per camera, ignoring case; sending the same request again "
        "returns 409 with code zone_name_taken."
    ),
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
    description="A second delete of the same zone returns 404.",
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
    return [SavedClip.from_found(saved, snapshot_url_of(context)) for saved in found]


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
    return SavedClip.from_found(saved, snapshot_url_of(context))


@router.patch(
    "/saved-clips/{id}",
    operation_id="updateSavedClip",
    response_description="The saved clip after the change",
    summary="Change a saved clip's note",
    responses=error_responses(404, 422, 500),
)
async def update_saved_clip(id: IdPath, body: SavedClipUpdate, context: Context) -> SavedClip:
    """Replace a saved clip's note."""
    updated = saved_clips.update_note(context.library, id, body.note)
    return SavedClip.from_found(updated, snapshot_url_of(context))


@router.delete(
    "/saved-clips/{id}",
    operation_id="deleteSavedClip",
    response_description="Removed",
    status_code=204,
    response_class=Response,
    summary="Remove a clip from the saved list",
    description=("The clip itself stays. A second delete of the same saved clip returns 404."),
    responses=error_responses(404, 422, 500),
)
async def delete_saved_clip(id: IdPath, context: Context) -> Response:
    """Remove a clip from the saved list (the clip itself stays)."""
    saved_clips.delete_saved_clip(context.library, id)
    return Response(status_code=204)
