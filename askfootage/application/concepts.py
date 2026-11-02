"""Any object: find a new noun in the ready recordings that lack it, one pass per noun.

Search never spends. When a question names an object that a ready recording has no stored
tracks for, search_day() lists it as a need (noun, estimated cost, recordings, state) and does
nothing else. Only request_concept() starts work, and only when the caller says confirm=True:

- One pass per noun. While a pass for a noun is queued or running, asking again returns that
  pass; no second one starts. The claim is made under a lock, so concurrent requests cannot
  both start it.
- The estimate is the sum over the recordings of estimate_cost(frames), frames being the
  recording's length at the analysis rate (askfootage.adapters.meta.budget.frames_cost, which
  prices at least 50 frames per request, is what the app passes in). If the budget could not
  pay for it, with the passes already waiting counted, the request is refused (409) and
  nothing starts.
- run() does the work after the reply: for each recording it asks the perception (behind
  BudgetedPerception when there is a budget) and saves the tracks with find_concept(), the
  add_concept path, so the search that follows finds them. It never raises; a failure ends
  the pass as failed with a fixed message, and tracks saved before it stay saved.

Passes are remembered in memory only. After a restart the tracks that were saved are still
there, so search stops listing them; a pass that was waiting is simply gone and can be asked
for again. Messages are fixed phrases or amounts: never a path, a key or a cause's text.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from math import ceil
from typing import Literal

from askfootage.application.add_concept import find_concept
from askfootage.application.budgeted_perception import BudgetedPerception
from askfootage.application.errors import (
    BudgetRefusedError,
    IndexingFailedError,
    IndexingNotConfiguredError,
    InvalidInputError,
    NoRecordedResultError,
    NotFoundError,
    RecordingNotReadyError,
)
from askfootage.application.ingest_video import (
    FAILED_NOTE,
    NOT_CONFIGURED_NOTE,
    IngestBudgetError,
)
from askfootage.application.library import Library, require_camera_filter
from askfootage.application.nouns import check_noun, nouns_in_question
from askfootage.domain.timebase import DEFAULT_ANALYSIS_FPS
from askfootage.ports.budget import Budget, format_dollars
from askfootage.ports.library_store import Recording
from askfootage.ports.perception import Perception
from askfootage.ports.track_store import TrackDataError, TrackStore
from askfootage.ports.video_store import VideoFileLayout

logger = logging.getLogger("askfootage.indexing")

JobState = Literal["queued", "running", "done", "failed"]
NeedState = Literal["not_indexed", "queued", "running"]
WINDOW_DAYS = 7
"""Days (ending today) a request without a day covers, the same window as GET /api/days."""
BUDGET_STOPPED_NOTE = "Stopped before the spending cap was passed."
_ACTIVE: frozenset[JobState] = frozenset({"queued", "running"})
_UNREADABLE = (TrackDataError, ValueError, KeyError, TypeError, OSError)


@dataclass(frozen=True, slots=True)
class ConceptBackend:
    """What a pass works with: perception, where the working copies are, the track store.

    estimate_cost(frames) is the dollars one request over that many frames costs. budget is
    None when nothing is ever spent (replay): then no cap is checked. fps is the analysis
    frame rate recordings are priced at.
    """

    perception: Perception
    layout: VideoFileLayout
    tracks: TrackStore
    estimate_cost: Callable[[int], Decimal]
    budget: Budget | None = None
    fps: float = DEFAULT_ANALYSIS_FPS


@dataclass(frozen=True, slots=True)
class ConceptJob:
    """One pass for one noun: where it is, which recordings it covers and what it costs."""

    noun: str
    state: JobState
    recording_ids: tuple[str, ...]
    estimated_cost: Decimal
    message: str | None = None
    """A fixed sentence for a failed pass; None otherwise."""


@dataclass(frozen=True, slots=True)
class IndexingNeed:
    """An object a question names that some ready recordings have no tracks for yet."""

    noun: str
    estimated_cost: Decimal
    recording_ids: tuple[str, ...]
    state: NeedState


@dataclass(frozen=True, slots=True)
class ConceptRequestResult:
    """The pass for a request, whether this request started it, and its work to run."""

    job: ConceptJob
    started: bool
    run: Callable[[], None] | None
    """Call it once the reply is sent (only when started); None otherwise."""


class ConceptService:
    """The passes of one app, over its library and backend. Safe to share between threads."""

    def __init__(self, library: Library, backend: ConceptBackend) -> None:
        self._library = library
        self._backend = backend
        self._lock = threading.Lock()
        self._jobs: dict[str, ConceptJob] = {}

    # --- what is missing -------------------------------------------------------------------

    def is_indexed(self, recording_id: str, noun: str) -> bool:
        """True when the noun was searched for in the recording, even with no result.

        A store that cannot be read counts as indexed, so nothing is offered (or spent) on
        data that cannot be judged.
        """
        tracks = self._backend.tracks
        try:
            marker = getattr(tracks, "concept_done", None)
            if marker is not None and marker(recording_id, noun):
                return True
            return bool(tracks.tracks_for(recording_id, noun))
        except _UNREADABLE:
            return True

    def estimate(self, recordings: Sequence[Recording]) -> Decimal:
        """What one pass over these recordings is estimated to cost, in dollars."""
        fps = self._backend.fps
        return sum(
            (self._backend.estimate_cost(ceil(r.length_seconds * fps)) for r in recordings),
            start=Decimal(0),
        )

    def needs_indexing(
        self, question: str, zone_names: Sequence[str], ready: Sequence[Recording]
    ) -> tuple[IndexingNeed, ...]:
        """The nouns of the question that some of these ready recordings lack, with the cost.

        Reads nothing but the track store; never starts work.
        """
        needs: list[IndexingNeed] = []
        for noun in nouns_in_question(question, zone_names):
            lacking = [r for r in ready if not self.is_indexed(r.id, noun)]
            if not lacking:
                continue
            with self._lock:
                job = self._jobs.get(noun)
            state: NeedState = "not_indexed"
            if job is not None and job.state == "queued":
                state = "queued"
            elif job is not None and job.state == "running":
                state = "running"
            needs.append(
                IndexingNeed(noun, self.estimate(lacking), tuple(r.id for r in lacking), state)
            )
        return tuple(needs)

    # --- asking for a pass -----------------------------------------------------------------

    def request(
        self,
        noun: str,
        *,
        confirm: bool,
        day: date | None,
        camera: str | None,
        today: date,
    ) -> ConceptRequestResult:
        """Queue the pass for `noun` over the ready recordings that lack it, or return its pass.

        The recordings are those of `day` (every day of the 7 ending `today` without one),
        from `camera` or every camera. Raises InvalidInputError for a bad noun or confirm
        not true, NotFoundError for an unknown camera and BudgetRefusedError when the budget
        could not pay for it.
        """
        wanted = check_noun(noun)
        if confirm is not True:
            raise InvalidInputError("confirm", "must be true")
        require_camera_filter(self._library, camera)
        ready = self._ready_recordings(day, camera, today)
        with self._lock:
            existing = self._jobs.get(wanted)
            if existing is not None and existing.state in _ACTIVE:
                return ConceptRequestResult(existing, False, None)
            lacking = [r for r in ready if not self.is_indexed(r.id, wanted)]
            if not lacking:
                if existing is not None and existing.state == "done":
                    return ConceptRequestResult(existing, False, None)
                return ConceptRequestResult(ConceptJob(wanted, "done", (), Decimal(0)), False, None)
            estimate = self.estimate(lacking)
            self._check_budget(estimate)
            job = ConceptJob(wanted, "queued", tuple(r.id for r in lacking), estimate)
            self._jobs[wanted] = job
        return ConceptRequestResult(job, True, lambda: self.run(wanted))

    def get(self, noun: str) -> ConceptJob:
        """The pass for `noun`; NotFoundError when none was asked for since the app started."""
        wanted = check_noun(noun)
        with self._lock:
            job = self._jobs.get(wanted)
        if job is None:
            raise NotFoundError("No pass has been requested for this object.")
        return job

    def _ready_recordings(
        self, day: date | None, camera: str | None, today: date
    ) -> list[Recording]:
        days = (
            [day] if day is not None else [today - timedelta(n) for n in range(WINDOW_DAYS)][::-1]
        )
        found = [
            recording
            for each in days
            for recording in self._library.recordings.list_recordings(camera, each)
            if recording.status == "ready"
        ]
        return sorted(found, key=lambda r: (r.day, r.start_time, r.id))

    def _check_budget(self, estimate: Decimal) -> None:
        """Refuse when the budget could not pay for this and the passes already waiting.

        Called with the lock held. The sum of the waiting passes' estimates is counted in
        full even where part is already reserved, so the check errs towards refusing.
        """
        budget = self._backend.budget
        if budget is None:
            return
        waiting = sum(
            (j.estimated_cost for j in self._jobs.values() if j.state in _ACTIVE), Decimal(0)
        )
        if budget.remaining < estimate + waiting:
            raise BudgetRefusedError(
                f"Not started: about {format_dollars(estimate)} is needed but only "
                f"{format_dollars(max(budget.remaining - waiting, Decimal(0)))} of the "
                "spending cap is left."
            )

    # --- the work --------------------------------------------------------------------------

    def run(self, noun: str) -> None:
        """Do a queued pass: each recording in turn, then done or failed. Never raises."""
        with self._lock:
            job = self._jobs.get(noun)
            if job is None or job.state != "queued":
                return
            self._jobs[noun] = replace(job, state="running")
        message: str | None = None
        try:
            for recording_id in job.recording_ids:
                self._find_in(recording_id, noun)
        except Exception as error:  # every failure must end the pass, not the thread
            message = _failure_message(error)
            logger.error("Pass for a new object failed (%s)", type(error).__name__)
        with self._lock:
            now = self._jobs.get(noun, job)
            state: JobState = "failed" if message else "done"
            self._jobs[noun] = replace(now, state=state, message=message)

    def _find_in(self, recording_id: str, noun: str) -> None:
        """One recording's part of a pass; a recording that vanished or is not ready is skipped."""
        backend = self._backend
        recording = self._library.recordings.get_recording(recording_id)
        if recording is None:
            return
        perception = backend.perception
        if backend.budget is not None:
            cost = backend.estimate_cost(ceil(recording.length_seconds * backend.fps))
            perception = BudgetedPerception(perception, backend.budget, cost)
        try:
            find_concept(
                self._library, perception, backend.layout, backend.tracks, recording_id, noun
            )
        except (NotFoundError, RecordingNotReadyError):
            return


def _failure_message(error: Exception) -> str:
    """A fixed sentence for why a pass failed."""
    if isinstance(error, NoRecordedResultError):
        return error.args[0] if error.args else FAILED_NOTE
    if isinstance(error, IndexingNotConfiguredError):
        return NOT_CONFIGURED_NOTE
    if isinstance(error, IngestBudgetError):
        return BUDGET_STOPPED_NOTE
    if isinstance(error, IndexingFailedError):
        return error.message
    return FAILED_NOTE


# --- the use cases the routes call -----------------------------------------------------------


def request_concept(
    service: ConceptService | None,
    noun: str,
    *,
    confirm: bool,
    day: date | None,
    camera: str | None,
    today: date,
) -> ConceptRequestResult:
    """ConceptService.request(); IndexingNotConfiguredError when the build has no service."""
    if service is None:
        raise IndexingNotConfiguredError()
    return service.request(noun, confirm=confirm, day=day, camera=camera, today=today)


def get_concept(service: ConceptService | None, noun: str) -> ConceptJob:
    """ConceptService.get(); IndexingNotConfiguredError when the build has no service."""
    if service is None:
        raise IndexingNotConfiguredError()
    return service.get(noun)
