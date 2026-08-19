"""Pulling a point onto an iso-height line.

A road held to a grade round a hillside runs *along* a contour, so an editor
that can put a point on one is the difference between drawing that road and
approximating it. Pure arithmetic over a height function.
"""
import numpy as np
import pytest

from OpenGLContext.edit.surface import height_gradient, snap_to_height


def _ramp(x, z):
    """Ground rising one in ten towards the east."""
    return np.asarray(x, dtype='d') * 0.1


def _bowl(x, z):
    return 0.001 * (np.asarray(x, 'd') ** 2 + np.asarray(z, 'd') ** 2)


class TestWhichWayTheGroundRises:
    def test_it_points_up_the_slope(self) -> None:
        east, north = height_gradient(_ramp, 100.0, 0.0)
        assert east > 0.0
        assert north == pytest.approx(0.0, abs=1e-6)

    def test_it_is_the_rate_the_ground_rises_at(self) -> None:
        east, _north = height_gradient(_ramp, 0.0, 0.0)
        assert east == pytest.approx(0.1, rel=1e-3)

    def test_flat_ground_rises_nowhere(self) -> None:
        east, north = height_gradient(lambda x, z: np.zeros(np.shape(x)),
                                      5.0, 5.0)
        assert (east, north) == pytest.approx((0.0, 0.0))


class TestPullingAPointOntoAContour:
    def test_it_lands_on_the_height_asked_for(self) -> None:
        x, z = snap_to_height(_ramp, 137.0, 40.0, 20.0)
        assert float(_ramp(np.asarray([x]), np.asarray([z]))[0]) \
            == pytest.approx(20.0, abs=0.01)

    def test_it_moves_across_the_slope_and_not_along_it(self) -> None:
        """The shortest way to a contour is straight up or down the hill."""
        x, z = snap_to_height(_ramp, 137.0, 40.0, 20.0)
        assert z == pytest.approx(40.0, abs=1e-6)

    def test_a_point_already_on_it_does_not_move(self) -> None:
        x, z = snap_to_height(_ramp, 200.0, -60.0, 20.0)
        assert (x, z) == pytest.approx((200.0, -60.0), abs=1e-6)

    def test_it_works_on_curved_ground(self) -> None:
        x, z = snap_to_height(_bowl, 300.0, 300.0, 100.0)
        assert float(_bowl(np.asarray([x]), np.asarray([z]))[0]) \
            == pytest.approx(100.0, abs=0.5)

    def test_it_will_not_be_dragged_across_the_map(self) -> None:
        """A contour a kilometre away is not what the pointer meant."""
        x, z = snap_to_height(_ramp, 0.0, 0.0, 500.0, reach=50.0)
        assert np.hypot(x, z) <= 50.0 + 1e-6

    def test_flat_ground_leaves_the_point_where_it_is(self) -> None:
        """There is no nearest contour on a plain, and guessing one would move
        the point somewhere the designer did not click."""
        flat = lambda x, z: np.zeros(np.shape(x))
        assert snap_to_height(flat, 12.0, 34.0, 5.0) == pytest.approx((12.0, 34.0))


class TestChoosingTheContour:
    def test_with_no_height_asked_for_it_takes_the_nearest_round_one(self) -> None:
        x, z = snap_to_height(_ramp, 137.0, 0.0, None, interval=25.0)
        height = float(_ramp(np.asarray([x]), np.asarray([z]))[0])
        assert height == pytest.approx(25.0, abs=0.05)

    def test_a_finer_interval_moves_the_point_less(self) -> None:
        coarse = snap_to_height(_ramp, 137.0, 0.0, None, interval=100.0)
        fine = snap_to_height(_ramp, 137.0, 0.0, None, interval=5.0)
        assert abs(fine[0] - 137.0) < abs(coarse[0] - 137.0)
