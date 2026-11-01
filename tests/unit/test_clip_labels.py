"""The seconds-based labels for the real clips (labels/clip1.json, labels/clip2.json)."""

import json
from pathlib import Path

import pytest

from askfootage.application.clip_labels import load_clip_labels
from askfootage.application.errors import InvalidInputError, NotFoundError

LABELS_DIR = Path(__file__).resolve().parents[2] / "labels"


def _write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "c.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _event(**changes: object) -> dict[str, object]:
    return {
        "type": "carrying",
        "object": "box",
        "start_s": 1,
        "end_s": 5,
        "status": "confirmed",
        **changes,
    }


def test_clip1_says_only_the_person_is_in_frame_and_nothing_is_confirmed() -> None:
    labels = load_clip_labels(LABELS_DIR / "clip1.json")
    assert labels.clip == "clip1"
    assert [(e.type, e.object, e.start_s, e.end_s) for e in labels.events] == [
        ("in_frame", "person", 1.0, 7.0)
    ]
    assert {e.status for e in labels.events} == {"unconfirmed"}
    assert not labels.has_confirmed("carrying")


def test_clip2_has_the_carry_and_the_box_leaving() -> None:
    labels = load_clip_labels(LABELS_DIR / "clip2.json")
    assert labels.clip == "clip2"
    assert [(e.type, e.object, e.start_s, e.end_s, e.status) for e in labels.events] == [
        ("carrying", "box", 1.0, 5.0, "confirmed"),
        ("leaves_room", "box", 6.0, 6.0, "confirmed"),
    ]
    assert labels.has_confirmed("carrying")


def test_no_zone_or_extra_fields_were_invented() -> None:
    for name in ("clip1", "clip2"):
        data = json.loads((LABELS_DIR / f"{name}.json").read_text(encoding="utf-8"))
        assert set(data) == {"clip", "events"}
        assert all(
            set(e) == {"type", "object", "start_s", "end_s", "status"} for e in data["events"]
        )


def test_missing_file_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        load_clip_labels(tmp_path / "nope.json")


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"clip": "", "events": []},
        {"clip": "c"},
        {"clip": "c", "events": {}},
        {"clip": "c", "events": [1]},
        {"clip": "c", "events": [_event(type="flying")]},
        {"clip": "c", "events": [_event(status="maybe")]},
        {"clip": "c", "events": [_event(object=" ")]},
        {"clip": "c", "events": [_event(start_s=-1)]},
        {"clip": "c", "events": [_event(start_s=True)]},
        {"clip": "c", "events": [_event(start_s=6, end_s=5)]},
        {"clip": "c", "events": [_event(extra=1)]},
        {"clip": "c", "events": [{"type": "carrying"}]},
        {"clip": "c", "events": [], "zone": "dock"},
    ],
)
def test_bad_files_are_rejected_without_echoing_them(tmp_path: Path, data: object) -> None:
    with pytest.raises(InvalidInputError):
        load_clip_labels(_write(tmp_path, data))


def test_file_that_is_not_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(InvalidInputError):
        load_clip_labels(path)
