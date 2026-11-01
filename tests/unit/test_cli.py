"""The ingest, add-concept and evaluate command lines, run with --fake in a temp folder."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from askfootage.adapters.fake.perception import DemoPerception
from askfootage.adapters.storage.json_tracks import JsonTrackStore
from askfootage.adapters.storage.local_files import LocalVideoFiles
from askfootage.interfaces.cli import evaluate as evaluate_cli
from askfootage.interfaces.cli import ingest as ingest_cli
from askfootage.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, DATA_DIR=str(tmp_path / "data"), MAX_RUN_COST_USD="5")


def _run(module, argv, settings):
    out, err = io.StringIO(), io.StringIO()
    code = module.main(argv, settings=settings, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"not really a video")
    return path


def test_fake_ingest_then_rerun_skips(tmp_path: Path, video: Path) -> None:
    settings = _settings(tmp_path)
    code, out, _ = _run(ingest_cli, ["ingest", "vid-1", str(video), "--fake"], settings)
    assert code == 0 and "person: 1 track(s) stored" in out and "cardboard box: 1" in out
    code, out, _ = _run(ingest_cli, ["ingest", "vid-1", str(video), "--fake"], settings)
    assert code == 0 and "already stored, skipped" in out
    store = JsonTrackStore(LocalVideoFiles(settings.data_dir))
    assert len(store.tracks_for("vid-1", "person")) == 1


def test_fake_add_concept(tmp_path: Path, video: Path) -> None:
    settings = _settings(tmp_path)
    _run(ingest_cli, ["ingest", "vid-1", str(video), "-c", "person", "--fake"], settings)
    code, out, _ = _run(ingest_cli, ["add-concept", "vid-1", "forklift", "--fake"], settings)
    assert code == 0 and "forklift: 1 track(s) stored" in out


def test_add_concept_before_ingest_fails_cleanly(tmp_path: Path) -> None:
    code, _, err = _run(
        ingest_cli, ["add-concept", "nope", "forklift", "--fake"], _settings(tmp_path)
    )
    assert code == 1 and err.startswith("error: ") and "not been ingested" in err


def test_without_fake_says_not_configured(tmp_path: Path, video: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "askfootage.interfaces.cli.wiring.FfmpegVideoPreparer",
        lambda: _CopyOnly(),
    )
    code, _, err = _run(ingest_cli, ["ingest", "vid-1", str(video)], _settings(tmp_path))
    assert code == 1 and "not configured" in err


class _CopyOnly:
    def prepare(self, source, dest_dir):
        from askfootage.adapters.fake.perception import CopyPreparer

        return CopyPreparer().prepare(source, dest_dir)


def test_bad_command_line_exits_2(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        ingest_cli.main(["ingest"], settings=_settings(tmp_path))
    assert caught.value.code == 2


def test_fake_perception_is_deterministic_and_carries() -> None:
    from askfootage.domain.relations import carrying

    perception = DemoPerception()
    people = perception.detect_and_track(Path("x"), "person")
    boxes = perception.detect_and_track(Path("x"), "cardboard box")
    assert people == perception.detect_and_track(Path("x"), "person")
    assert len(carrying(people, boxes)) == 1


def test_evaluate_cli_end_to_end(tmp_path: Path, video: Path) -> None:
    settings = _settings(tmp_path)
    _run(ingest_cli, ["ingest", "vid-1", str(video), "--fake"], settings)
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {
                "video_id": "vid-1",
                "relations": [{"kind": "carrying", "start_frame": 0, "end_frame": 59}],
            }
        ),
        encoding="utf-8",
    )
    code, out, _ = _run(evaluate_cli, [str(labels), "--json"], settings)
    assert code == 0
    carrying = json.loads(out)["relations"]["carrying"]
    assert carrying["recall"] > 0.9 and carrying["precision"] > 0.9
    code, out, _ = _run(evaluate_cli, [str(labels)], settings)
    assert code == 0 and out.splitlines()[0].startswith("relation") and "carrying" in out


def test_evaluate_cli_errors(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    code, _, err = _run(evaluate_cli, [str(tmp_path / "missing.json")], settings)
    assert code == 1 and "not found" in err
    code, _, err = _run(evaluate_cli, ["x.json", "--iou", "0"], settings)
    assert code == 1 and "--iou" in err


# --- hardening -----------------------------------------------------------------------------


def test_real_path_cost_is_the_frame_estimate_and_the_override_cannot_lower_it(
    tmp_path: Path,
) -> None:
    from decimal import Decimal

    from askfootage.adapters.meta.budget import frames_cost
    from askfootage.interfaces.cli.wiring import build_services

    services = build_services(_settings(tmp_path), fake=False, cost_per_concept=Decimal("0.001"))
    assert services.estimate_cost is not None and services.estimate_cost(900) == frames_cost(900)
    assert services.cost_per_concept == Decimal("0.001")  # floor only: max() in the pipeline
    fake = build_services(_settings(tmp_path), fake=True, cost_per_concept=Decimal("0"))
    assert fake.estimate_cost is None


def test_cap_carries_over_between_cli_runs(tmp_path: Path, video: Path) -> None:
    settings = Settings(_env_file=None, DATA_DIR=str(tmp_path / "data"), MAX_RUN_COST_USD="1")
    args = ["--fake", "--cost-per-concept", "0.7"]
    code, _, _ = _run(ingest_cli, ["ingest", "a", str(video), "-c", "person", *args], settings)
    assert code == 0
    code, _, err = _run(ingest_cli, ["ingest", "b", str(video), "-c", "person", *args], settings)
    assert code == 1 and "cap" in err


def test_unknown_concept_warns_on_stderr_but_stores(tmp_path: Path, video: Path) -> None:
    code, out, err = _run(
        ingest_cli, ["ingest", "v", str(video), "-c", "Forklift", "--fake"], _settings(tmp_path)
    )
    assert code == 0 and "forklift: 1 track(s) stored" in out
    assert "warning" in err and "forklift" in err


@pytest.mark.parametrize("error", [ValueError("secret-path-marker"), OSError("secret-path-marker")])
def test_unexpected_errors_become_one_fixed_line(tmp_path: Path, video: Path, monkeypatch, error):
    def boom(*_a, **_k):
        raise error

    monkeypatch.setattr(ingest_cli, "build_services", boom)
    code, _, err = _run(ingest_cli, ["ingest", "v", str(video), "--fake"], _settings(tmp_path))
    assert code == 1 and err.count("\n") == 1 and err.startswith("error: ")
    assert "secret" not in err and "Traceback" not in err


def test_corrupt_tracks_and_bad_labels_json_are_fixed_messages(tmp_path: Path, video: Path) -> None:
    settings = _settings(tmp_path)
    _run(ingest_cli, ["ingest", "v", str(video), "--fake"], settings)
    (settings.data_dir / "v" / "tracks.json").write_text("{oops", encoding="utf-8")
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {"video_id": "v", "relations": [{"kind": "carrying", "start_frame": 0, "end_frame": 5}]}
        ),
        encoding="utf-8",
    )
    code, _, err = _run(evaluate_cli, [str(labels)], settings)
    assert code == 1 and "unreadable" in err and str(tmp_path) not in err
    labels.write_text("{oops", encoding="utf-8")
    code, _, err = _run(evaluate_cli, [str(labels)], settings)
    assert code == 1 and "Traceback" not in err and str(tmp_path) not in err


def test_evaluating_an_unknown_video_is_an_error_and_makes_no_folder(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {
                "video_id": "ghost",
                "relations": [{"kind": "carrying", "start_frame": 0, "end_frame": 5}],
            }
        ),
        encoding="utf-8",
    )
    code, out, err = _run(evaluate_cli, [str(labels)], settings)
    assert code == 1 and out == "" and "ingest" in err
    assert not (settings.data_dir / "ghost").exists()


def test_changed_source_needs_force_via_the_cli(tmp_path: Path, video: Path) -> None:
    settings = _settings(tmp_path)
    _run(ingest_cli, ["ingest", "v", str(video), "--fake"], settings)
    video.write_bytes(b"a different, longer video file")
    code, _, err = _run(ingest_cli, ["ingest", "v", str(video), "--fake"], settings)
    assert code == 1 and "--force" in err
    code, _, _ = _run(ingest_cli, ["ingest", "v", str(video), "--fake", "--force"], settings)
    assert code == 0
