"""What the routes need, wired once by create_app() and read per request."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Request

from askfootage.application.concepts import ConceptService
from askfootage.application.demo_access import CodeVerifier, FailedAttemptLimiter, no_valid_codes
from askfootage.application.ingest_video import IndexingPipeline
from askfootage.application.library import IdFactory, Library
from askfootage.application.posters import PosterStore, has_footage
from askfootage.application.recordings import FootageSource
from askfootage.application.search import Interpreter
from askfootage.application.search_relations import FrameSizeSource
from askfootage.application.snapshots import SnapshotStore
from askfootage.ports.language_model import QuestionParser
from askfootage.ports.track_store import TrackStore

Job = Callable[[], None]
"""Work to do once the reply has been sent."""
JobScheduler = Callable[[BackgroundTasks, Job], None]
"""Arranges for a job to run after this request's reply (tests may run it themselves)."""


def run_after_reply(tasks: BackgroundTasks, job: Job) -> None:
    """The default scheduler: FastAPI runs the job after sending the reply.

    A plain function job runs in the thread pool, so a slow one never blocks other requests.
    """
    tasks.add_task(job)


@dataclass(frozen=True, slots=True)
class ApiContext:
    """The stores, clock, interpreter and limits the routes hand to the use cases.

    indexing is None when the build has no way to find objects (POST .../index is 503).
    tracks, question_parser and frame_size feed search over stored tracks; with tracks
    None (or a recording without tracks) search uses the demo keyword matcher. snapshots,
    when set, makes and serves the evidence snapshot of each clip found from tracks.
    posters, when set, makes and serves a poster frame per recording (no store: no
    posterUrl and the poster route is 404).
    concepts is None when the build cannot search for a new object (POST /api/concepts is
    503, and search lists no needsIndexing).
    verify_demo_code checks a demo access code (default: none is valid); code_limiter counts
    wrong codes per client (in memory).
    """

    library: Library
    interpreter: Interpreter
    footage: FootageSource
    today: Callable[[], date]
    utc_now: Callable[[], datetime]
    make_id: IdFactory
    max_upload_bytes: int
    indexing: IndexingPipeline | None = None
    tracks: TrackStore | None = None
    question_parser: QuestionParser | None = None
    frame_size: FrameSizeSource | None = None
    snapshots: SnapshotStore | None = None
    concepts: ConceptService | None = None
    posters: PosterStore | None = None
    schedule_after_reply: JobScheduler = run_after_reply
    verify_demo_code: CodeVerifier = no_valid_codes
    code_limiter: FailedAttemptLimiter = field(default_factory=FailedAttemptLimiter)


def snapshot_url_of(context: ApiContext) -> Callable[[str], str | None]:
    """Clip id -> the URL of its evidence snapshot, or None when the clip has none."""
    snapshots = context.snapshots

    def url(clip_id: str) -> str | None:
        if snapshots is not None and snapshots.has(clip_id):
            return f"/api/clips/{clip_id}/snapshot"
        return None

    return url


def poster_url_of(context: ApiContext) -> Callable[[str, int | None], str | None]:
    """(recording id, second) -> the poster URL, or None when there is no footage to show.

    The answer for each recording is remembered for the one response this is made for.
    """
    known: dict[str, bool] = {}

    def url(recording_id: str, at_seconds: int | None = None) -> str | None:
        if context.posters is None:
            return None
        if recording_id not in known:
            known[recording_id] = has_footage(context.library, context.footage, recording_id)
        if not known[recording_id]:
            return None
        base = f"/api/recordings/{recording_id}/poster"
        return base if at_seconds is None else f"{base}?t={at_seconds}"

    return url


def get_context(request: Request) -> ApiContext:
    """The ApiContext of the app serving this request."""
    context = request.app.state.context
    assert isinstance(context, ApiContext)
    return context


Context = Annotated[ApiContext, Depends(get_context)]
"""Route parameter type that injects the ApiContext."""
