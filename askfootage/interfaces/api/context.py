"""What the routes need, wired once by create_app() and read per request."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Request

from askfootage.application.ingest_video import IndexingPipeline
from askfootage.application.library import IdFactory, Library
from askfootage.application.recordings import FootageSource
from askfootage.application.search import Interpreter

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
    """

    library: Library
    interpreter: Interpreter
    footage: FootageSource
    today: Callable[[], date]
    utc_now: Callable[[], datetime]
    make_id: IdFactory
    max_upload_bytes: int
    indexing: IndexingPipeline | None = None
    schedule_after_reply: JobScheduler = run_after_reply


def get_context(request: Request) -> ApiContext:
    """The ApiContext of the app serving this request."""
    context = request.app.state.context
    assert isinstance(context, ApiContext)
    return context


Context = Annotated[ApiContext, Depends(get_context)]
"""Route parameter type that injects the ApiContext."""
