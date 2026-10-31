"""Builds the services the command-line tools use. Settings arrive as an argument; this
module never reads the environment itself (only askfootage/settings.py does)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from askfootage.adapters.fake.perception import CopyPreparer, DemoPerception
from askfootage.adapters.media.ffmpeg import FfmpegVideoPreparer
from askfootage.adapters.meta.budget import HardCapBudget, frames_cost
from askfootage.adapters.storage.json_tracks import JsonTrackStore
from askfootage.adapters.storage.local_files import LocalVideoFiles
from askfootage.application.ingest_video import IngestServices
from askfootage.domain.tracks import Track
from askfootage.ports.perception import Perception, PerceptionNotConfiguredError
from askfootage.settings import Settings

LEDGER_DIR_NAME = "ledger"


class UnconfiguredPerception:
    """Perception for a build without the SAM adapter: every call says it is not configured."""

    configured = False  # lets ingest refuse before it runs ffmpeg

    def detect_and_track(self, video_path: Path, noun: str) -> list[Track]:
        raise PerceptionNotConfiguredError()


def build_track_store(settings: Settings) -> JsonTrackStore:
    """The JSON track store under settings.data_dir."""
    return JsonTrackStore(LocalVideoFiles(settings.data_dir))


def build_services(
    settings: Settings, *, fake: bool, cost_per_concept: Decimal | None = None
) -> IngestServices:
    """Ingest services: fake perception and a copying preparer with --fake (no key, no
    ffmpeg, no spend), else ffmpeg and the real perception, which this build lacks.

    Cost. Real path: each call is priced from the prepared video's frame count with
    frames_cost(); cost_per_concept can only raise that (it is a floor, never an
    override). Fake path: a fixed cost_per_concept, default 0, so the cap can be tried.
    The budget reads the spend ledger in DATA_DIR/ledger, so the cap covers every run."""
    layout = LocalVideoFiles(settings.data_dir)
    budget = HardCapBudget(settings.max_run_cost_usd, settings.data_dir / LEDGER_DIR_NAME)
    perception: Perception = DemoPerception() if fake else UnconfiguredPerception()
    return IngestServices(
        perception=perception,
        preparer=CopyPreparer() if fake else FfmpegVideoPreparer(),
        layout=layout,
        tracks=JsonTrackStore(layout),
        budget=budget,
        cost_per_concept=Decimal(0) if cost_per_concept is None else cost_per_concept,
        estimate_cost=None if fake else frames_cost,
    )
