import pytest

from askfootage.domain.geometry import (
    containment,
    intersection_area,
    point_in_polygon,
    relative_offset,
)
from askfootage.domain.models import BoundingBox

DOORWAY = [(400.0, 0.0), (500.0, 0.0), (500.0, 400.0), (400.0, 400.0)]
L_SHAPE = [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (4.0, 4.0), (4.0, 10.0), (0.0, 10.0)]


def make_box(x1: float, y1: float, x2: float, y2: float) -> BoundingBox:
    return BoundingBox(x1, y1, x2, y2)


def test_intersection_area_of_overlapping_boxes() -> None:
    assert intersection_area(make_box(0, 0, 10, 10), make_box(5, 5, 15, 15)) == 25


@pytest.mark.parametrize("other", [make_box(10, 0, 20, 10), make_box(50, 50, 60, 60)])
def test_touching_or_separate_boxes_do_not_intersect(other: BoundingBox) -> None:
    assert intersection_area(make_box(0, 0, 10, 10), other) == 0.0


@pytest.mark.parametrize(
    ("outer", "expected"),
    [
        (make_box(-5, -5, 20, 20), 1.0),
        (make_box(5, 0, 20, 10), 0.5),
        (make_box(50, 50, 60, 60), 0.0),
    ],
)
def test_containment_fractions(outer: BoundingBox, expected: float) -> None:
    assert containment(make_box(0, 0, 10, 10), outer) == pytest.approx(expected)


def test_containment_of_a_zero_area_box_is_zero() -> None:
    assert containment(make_box(5, 5, 5, 5), make_box(0, 0, 10, 10)) == 0.0


def test_a_held_object_scores_fully_where_iou_would_not() -> None:
    person = make_box(0, 0, 60, 160)
    box_in_hands = make_box(15, 60, 45, 90)  # 900 of 9,600 px: IoU would be about 0.09
    assert containment(box_in_hands, person) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (make_box(20, 70, 40, 90), (0.0, 0.0)),
        (make_box(50, 70, 70, 90), (0.5, 0.0)),
        (make_box(20, 110, 40, 130), (0.0, 0.25)),
    ],
)
def test_relative_offset_is_measured_from_the_anchor_centre(
    target: BoundingBox, expected: tuple[float, float]
) -> None:
    assert relative_offset(make_box(0, 0, 60, 160), target) == pytest.approx(expected)


def test_relative_offset_ignores_scale_and_position() -> None:
    near = relative_offset(make_box(0, 0, 60, 160), make_box(45, 60, 75, 90))
    far_and_shifted = relative_offset(make_box(100, 50, 220, 370), make_box(190, 170, 250, 230))
    assert far_and_shifted == pytest.approx(near)


def test_relative_offset_of_a_zero_size_anchor_is_zero() -> None:
    assert relative_offset(make_box(5, 5, 5, 5), make_box(0, 0, 10, 10)) == (0.0, 0.0)


@pytest.mark.parametrize(
    ("point", "expected"),
    [((450.0, 200.0), True), ((300.0, 200.0), False), ((450.0, 500.0), False)],
)
def test_point_in_a_rectangle(point: tuple[float, float], expected: bool) -> None:
    assert point_in_polygon(point, DOORWAY) is expected


@pytest.mark.parametrize(
    ("point", "expected"),
    [((2.0, 7.0), True), ((7.0, 2.0), True), ((7.0, 7.0), False)],
)
def test_point_in_a_concave_polygon_respects_the_notch(
    point: tuple[float, float], expected: bool
) -> None:
    assert point_in_polygon(point, L_SHAPE) is expected


def test_vertex_order_does_not_matter() -> None:
    assert point_in_polygon((450.0, 200.0), list(reversed(DOORWAY))) is True


def test_rejects_a_polygon_with_fewer_than_three_vertices() -> None:
    with pytest.raises(ValueError, match="3 vertices"):
        point_in_polygon((0.0, 0.0), [(0.0, 0.0), (1.0, 1.0)])
