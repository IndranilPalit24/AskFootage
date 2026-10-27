import dataclasses

import pytest

from askfootage.domain.models import BoundingBox


@pytest.fixture
def box() -> BoundingBox:
    return BoundingBox(x1=10, y1=20, x2=50, y2=100)


def test_size_properties(box: BoundingBox) -> None:
    assert (box.width, box.height, box.area) == (40, 80, 3200)


def test_center_and_foot(box: BoundingBox) -> None:
    assert box.center == (30, 60)
    assert box.foot == (30, 100)


def test_a_zero_area_box_is_allowed() -> None:
    assert BoundingBox(5, 5, 5, 5).area == 0


@pytest.mark.parametrize(
    "corners",
    [(5, 0, 1, 1), (0, 5, 1, 1), (0, 0, float("nan"), 1), (0, 0, float("inf"), 1)],
)
def test_rejects_invalid_boxes(corners: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValueError, match="box"):
        BoundingBox(*corners)


def test_is_immutable(box: BoundingBox) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        box.x1 = 0  # type: ignore[misc]
