"""A fresh clone works: prepare + ingest from demo/sam into an empty folder, then search.

Copies the repository's videos/ and demo/sam into a temporary root (the real data/ is never
touched), runs the steps that scripts.run_demo runs, and asks the real-clips app a question.
Skipped when the clips or ffmpeg are not available. No network, no key.
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from askfootage.interfaces.real_clips import create_app
from scripts import run_demo

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    not (ROOT / "videos" / "clip1.mp4").is_file()
    or not (ROOT / "videos" / "clip2.mp4").is_file()
    or shutil.which("ffmpeg") is None
    or shutil.which("ffprobe") is None,
    reason="videos/clip1.mp4, videos/clip2.mp4 and ffmpeg are needed",
)


def test_fresh_root_prepares_ingests_and_finds_clip2_only(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "videos", tmp_path / "videos")
    shutil.copytree(ROOT / "demo" / "sam", tmp_path / "demo" / "sam")
    out = io.StringIO()
    assert run_demo.check_videos(tmp_path, out) and run_demo.check_tools(out)
    assert run_demo.needs_ingest(tmp_path)

    assert run_demo.prepare_and_ingest(tmp_path, out), out.getvalue()
    assert not run_demo.needs_ingest(tmp_path)

    client = TestClient(create_app(tmp_path / "data" / "real", tmp_path / "videos"))
    body = client.post(
        "/api/search", json={"question": "person carrying a box", "day": "2026-10-30"}
    ).json()
    assert [clip["recordingId"] for clip in body["clips"]] == ["clip2"]
    assert body["proofs"]
    assert client.get("/api/recordings/clip2/boxes").status_code == 200
