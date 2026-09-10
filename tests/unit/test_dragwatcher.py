"""What :class:`DragWatcher` answers about a drag in progress."""
from typing import Tuple

import pytest

from OpenGLContext.move.dragwatcher import DragWatcher


class TestUniformFractions:
    def test_the_same_movement_gives_the_same_fraction_anywhere(self) -> None:
        left = DragWatcher(10, 10, 200, 100).uniformFractions(30, 30)
        right = DragWatcher(150, 70, 200, 100).uniformFractions(170, 90)
        assert left == pytest.approx(right)

    def test_a_window_with_no_extent_gives_no_movement(self) -> None:
        assert DragWatcher(0, 0, 0, 0).uniformFractions(5, 5) == (0.0, 0.0)


class TestFractions:
    def test_the_start_point_is_zero(self) -> None:
        assert DragWatcher(40, 30, 200, 100).fractions(40, 30) == (0.0, 0.0)

    def test_the_far_edge_is_one(self) -> None:
        assert DragWatcher(40, 30, 200, 100).fractions(200, 100) \
            == pytest.approx((1.0, 1.0))

    def test_the_near_edge_is_minus_one(self) -> None:
        assert DragWatcher(40, 30, 200, 100).fractions(0, 0) \
            == pytest.approx((-1.0, -1.0))

    @pytest.mark.parametrize('start,total,point', [
        ((0, 0), (200, 100), (-5, -5)),      # a drag begun on the near edge
        ((200, 100), (200, 100), (250, 150)),  # and on the far edge
    ])
    def test_a_drag_from_an_edge_answers_rather_than_dividing_by_nothing(
        self, start: Tuple[int, int], total: Tuple[int, int],
        point: Tuple[int, int],
    ) -> None:
        """There is no distance to that edge, so the fraction toward it is zero."""
        watcher = DragWatcher(start[0], start[1], total[0], total[1])
        assert watcher.fractions(point[0], point[1]) == (0.0, 0.0)


class TestDistances:
    def test_it_is_the_movement_in_pixels(self) -> None:
        assert DragWatcher(40, 30, 200, 100).distances(55, 20) == (15, -10)

    def test_the_start_point_has_not_moved(self) -> None:
        assert DragWatcher(40, 30, 200, 100).distances(40, 30) == (0, 0)
