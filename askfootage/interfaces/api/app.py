"""The HTTP API's composition root: create_app() wires the stores, clock and routes.

Run it in demo mode (the factory is called with no arguments):

    python -m uvicorn askfootage.interfaces.api.app:create_app --factory --port 8000

There is deliberately no module-level `app = create_app()`: importing this module must
not open or create a database. This is the only module that imports the SQLite adapter,
and it does so lazily, inside open_demo_library(), so tests that inject in-memory stores
never load it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import FastAPI
from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.types import Receive, Scope, Send

from askfootage.application.ingest_video import IndexingPipeline
from askfootage.application.library import IdFactory, Library, new_id
from askfootage.application.search import Interpreter, QuestionInterpreter
from askfootage.application.search_relations import FrameSizeSource, frame_size_source_of
from askfootage.application.snapshots import SnapshotStore
from askfootage.interfaces.api.body_limit import BodyLimitMiddleware
from askfootage.interfaces.api.context import ApiContext, JobScheduler, run_after_reply
from askfootage.interfaces.api.errors import InternalErrorMiddleware, install_error_handlers
from askfootage.interfaces.api.footage import DemoFootageSource
from askfootage.interfaces.api.routes import router
from askfootage.interfaces.api.upload import MAX_UPLOAD_BYTES
from askfootage.ports.language_model import QuestionParser
from askfootage.ports.track_store import TrackStore
from askfootage.settings import Settings, load_settings

API_VERSION = "1.5.0"
"""The contract version this app serves (info.version in contract/openapi.yaml)."""
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VIDEOS_DIR = REPO_ROOT / "videos"
"""Where demo footage lives: <repo>/videos, worked out from this file, not the environment."""
DEMO_SEED_FILE = REPO_ROOT / "contract" / "examples" / "demo-seed.json"
"""The demo dataset, loaded into an empty database on start-up."""
DEMO_DATABASE_NAME = "demo.sqlite"
"""The demo database's file name inside settings.data_dir."""
UI_DEV_ORIGIN = "http://localhost:5173"
"""The UI's dev server: the only origin CORS lets in."""
CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
CORS_HEADERS = ["Content-Type", "Range"]


def create_app(
    settings: Settings | None = None,
    *,
    library: Library | None = None,
    today: Callable[[], date] | None = None,
    utc_now: Callable[[], datetime] | None = None,
    videos_dir: Path | None = None,
    interpreter: Interpreter | None = None,
    make_id: IdFactory = new_id,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
    indexing: IndexingPipeline | None = None,
    schedule_after_reply: JobScheduler = run_after_reply,
    tracks: TrackStore | None = None,
    question_parser: QuestionParser | None = None,
    frame_size: FrameSizeSource | None = None,
    snapshots: SnapshotStore | None = None,
) -> FastAPI:
    """Build the AskFootage API.

    With no arguments (as `uvicorn --factory` calls it) it serves demo mode: settings come
    from load_settings(), the demo database is settings.data_dir/demo.sqlite (seeded from
    contract/examples/demo-seed.json when empty), "today" is the demo dataset's today and
    footage is <repo>/videos/clip1.mp4.

    `tracks` is the store search reads object tracks from (default: the indexing
    pipeline's store, if any; in demo mode, the JSON track store under settings.data_dir,
    where a recording's tracks live in <data_dir>/<recording id>/tracks.json);
    `question_parser` reads questions before the keyword reader; `frame_size` gives a
    recording's pixel size so zone questions can run (default: the track store's own
    frame_size method, when it has one). Without tracks, search is the demo keyword matcher.

    `snapshots` makes and serves the evidence snapshot of each clip found from tracks (none in
    demo mode).

    `indexing` is the pipeline POST /api/recordings/{id}/index runs. It is None by
    default: this build has no perception yet, so that route answers 503
    indexing_not_configured and changes nothing. `schedule_after_reply` decides how the
    indexing work runs after the reply (FastAPI background tasks by default).

    Tests pass `library` (in-memory stores), and may pass `today`, `utc_now`,
    `videos_dir`, `interpreter`, `make_id`, a smaller `max_upload_bytes`, a fake
    `indexing` pipeline and a scheduler that runs the work when they say. `settings`
    gives the data directory (when no library is given) and the API key to keep out of
    the server log; the key is never used for anything else here and never sent.
    """
    if library is None:
        if settings is None:
            settings = load_settings()
        library = open_demo_library(settings)
        if tracks is None and indexing is None:
            tracks = open_track_store(settings)
    store_of_tracks = tracks if tracks is not None else (indexing.tracks if indexing else None)
    app = FastAPI(
        title="AskFootage API",
        version=API_VERSION,
        description=(
            "Ask a plain-English question about fixed-camera footage and get the matching "
            "clips with the evidence for each match. contract/openapi.yaml is the source "
            "of truth for this API."
        ),
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        separate_input_output_schemas=False,
    )
    app.state.context = ApiContext(
        library=library,
        interpreter=interpreter if interpreter is not None else QuestionInterpreter(),
        footage=DemoFootageSource(videos_dir if videos_dir is not None else DEFAULT_VIDEOS_DIR),
        today=today if today is not None else _fixed_day(read_demo_today()),
        utc_now=utc_now if utc_now is not None else _utc_now,
        make_id=make_id,
        max_upload_bytes=max_upload_bytes,
        indexing=indexing,
        schedule_after_reply=schedule_after_reply,
        tracks=store_of_tracks,
        question_parser=question_parser,
        frame_size=frame_size if frame_size is not None else frame_size_source_of(store_of_tracks),
        snapshots=snapshots,
    )
    install_error_handlers(app)
    app.include_router(router)
    # Each add_middleware wraps the ones before it, so requests pass CORS first, then the
    # 500 guard, then the body limit. Both sit inside CORS, so their error bodies still
    # carry the CORS headers and the UI can read them.
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(InternalErrorMiddleware, secrets=_secrets_to_redact(settings))
    app.add_middleware(
        UiOnlyCORSMiddleware,
        allow_origins=[UI_DEV_ORIGIN],
        allow_methods=CORS_METHODS,
        allow_headers=CORS_HEADERS,
        allow_credentials=False,
    )
    return app


def open_demo_library(settings: Settings) -> Library:
    """Open (and seed, when empty) the demo database in settings.data_dir.

    The SQLite adapter owns the database file, its schema version and any migration.
    """
    # The one place the SQLite adapter is imported: lazily, so tests never need it.
    from askfootage.adapters.sqlite.store import SqliteLibraryStore, seed_demo_data

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = SqliteLibraryStore(settings.data_dir / DEMO_DATABASE_NAME)
    seed_demo_data(store, DEMO_SEED_FILE)
    return Library.from_store(store)


def open_track_store(settings: Settings) -> TrackStore:
    """The JSON track store the command-line tools write, rooted at settings.data_dir.

    Imported lazily, like the SQLite adapter, so tests that inject stores never load it.
    """
    from askfootage.adapters.storage.json_tracks import JsonTrackStore
    from askfootage.adapters.storage.local_files import LocalVideoFiles

    return JsonTrackStore(LocalVideoFiles(settings.data_dir))


def read_demo_today(seed_file: Path = DEMO_SEED_FILE) -> date:
    """The demo dataset's "today" (2026-10-30), which demo mode uses as the current day."""
    seed = json.loads(seed_file.read_text(encoding="utf-8"))
    return date.fromisoformat(seed["today"])


def _secrets_to_redact(settings: Settings | None) -> tuple[str, ...]:
    """Values the server log must never show: the API key, when one is configured."""
    if settings is None or settings.api_key is None:
        return ()
    return (settings.require_api_key(),)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _fixed_day(day: date) -> Callable[[], date]:
    return lambda: day


class UiOnlyCORSMiddleware(CORSMiddleware):
    """CORS for the UI's dev origin only; everyone else gets no CORS headers at all.

    Starlette answers a refused preflight with a plain-text 400 that still carries some
    Access-Control-* headers. Here a refused preflight is passed to the app as an ordinary
    OPTIONS request instead, so it gets the standard JSON error (405, or 404 for an
    unknown path) and no CORS headers.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Answer allowed preflights; hand everything else to Starlette's CORS handling."""
        if scope["type"] == "http" and scope["method"] == "OPTIONS":
            headers = Headers(scope=scope)
            if "origin" in headers and "access-control-request-method" in headers:
                preflight = self.preflight_response(request_headers=headers)
                if preflight.status_code == 200:
                    await preflight(scope, receive, send)
                else:
                    await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)
