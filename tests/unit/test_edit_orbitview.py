"""An orbiting camera over a point of interest: an editor's three-quarter view.

Arithmetic, so none of it needs a window: where the camera stands for a
heading, a pitch and a distance, and what orbiting, dollying and framing do to
that.
"""
import numpy as np
import pytest

from OpenGLContext.edit.orbitview import DEFAULT_PITCH, OrbitView, OrbitViewPlatform

VIEWPORT = (800, 600)


def _view(**named):
    named.setdefault('centre', (0.0, 0.0))
    named.setdefault('distance', 500.0)
    return OrbitView(**named)


class TestWhereTheCameraStands:
    def test_it_stands_off_by_the_distance_it_was_given(self) -> None:
        view = _view(distance=400.0)
        where = view.position()
        assert float(np.linalg.norm(where - view.target())) \
            == pytest.approx(400.0)

    def test_it_stands_above_the_ground_it_looks_at(self) -> None:
        assert _view().position()[1] > _view().target()[1]

    def test_the_default_is_a_three_quarter_view(self) -> None:
        """High enough to read the plan, low enough to read the relief."""
        assert 20.0 < DEFAULT_PITCH < 60.0

    def test_looking_straight_down_puts_it_overhead(self) -> None:
        view = _view(pitch=90.0)
        where = view.position()
        assert (float(where[0]), float(where[2])) == pytest.approx((0.0, 0.0),
                                                                   abs=1e-6)

    def test_a_heading_of_nothing_puts_it_to_the_south(self) -> None:
        """Looking north, which is what a map has at the top of the screen."""
        assert _view(pitch=0.0).position()[2] > 0.0

    def test_turning_ninety_degrees_puts_it_to_the_west(self) -> None:
        assert _view(pitch=0.0, heading=90.0).position()[0] < 0.0

    def test_it_looks_at_the_point_it_was_given(self) -> None:
        view = _view(centre=(120.0, -60.0), ground=25.0)
        assert view.target() == pytest.approx((120.0, 25.0, -60.0))


class TestMovingAbout:
    def test_orbiting_turns_the_camera_round_the_point(self) -> None:
        view = _view()
        target = view.target().copy()
        view.orbit(45.0, 0.0)
        assert view.target() == pytest.approx(target)
        assert float(np.linalg.norm(view.position() - view.target())) \
            == pytest.approx(500.0)

    def test_orbiting_up_raises_the_camera(self) -> None:
        view = _view(pitch=30.0)
        low = view.position()[1]
        view.orbit(0.0, 20.0)
        assert view.position()[1] > low

    def test_it_cannot_be_tipped_past_overhead(self) -> None:
        view = _view()
        view.orbit(0.0, 500.0)
        assert view.pitch <= 89.0

    def test_it_cannot_be_tipped_under_the_ground(self) -> None:
        view = _view()
        view.orbit(0.0, -500.0)
        assert view.pitch >= 1.0

    def test_dollying_in_brings_it_closer(self) -> None:
        view = _view(distance=500.0)
        view.dolly(0.5)
        assert view.distance == pytest.approx(250.0)

    def test_it_cannot_be_dollied_into_the_ground(self) -> None:
        view = _view()
        for _ in range(50):
            view.dolly(0.5)
        assert view.distance >= OrbitView.NEAREST

    def test_it_cannot_be_dollied_out_of_the_world(self) -> None:
        view = _view()
        for _ in range(50):
            view.dolly(2.0)
        assert view.distance <= OrbitView.FURTHEST


class TestFramingARegion:
    def test_it_looks_at_the_middle_of_what_it_was_given(self) -> None:
        view = _view()
        view.frame((-1000.0, -600.0), (200.0, 400.0), VIEWPORT)
        assert (view.centre[0], view.centre[1]) == pytest.approx((-400.0, -100.0))

    def test_a_bigger_region_is_looked_at_from_further_off(self) -> None:
        near, far = _view(), _view()
        near.frame((-100.0, -100.0), (100.0, 100.0), VIEWPORT)
        far.frame((-2000.0, -2000.0), (2000.0, 2000.0), VIEWPORT)
        assert far.distance > near.distance


class TestAsACamera:
    def _platform(self, **named):
        view = _view(**named)
        platform = OrbitViewPlatform(view, VIEWPORT)
        platform.setViewport(*VIEWPORT)
        return view, platform

    def test_it_reads_the_view_rather_than_copying_it(self) -> None:
        """Orbiting is what moves the camera; there is no second copy of where
        the editor is looking to fall out of step with the first."""
        view, platform = self._platform()
        before = np.asarray(platform.position, dtype='d')[:3].copy()
        view.orbit(90.0, 0.0)
        assert not np.allclose(np.asarray(platform.position, 'd')[:3], before)

    def test_the_matrices_are_the_shape_a_pass_wants(self) -> None:
        _view_, platform = self._platform()
        assert platform.modelMatrix().shape == (4, 4)
        assert platform.viewMatrix().shape == (4, 4)

    def test_the_projection_has_perspective_in_it(self) -> None:
        """Which is the whole difference from the plan view: things further
        away are smaller, so the land has depth."""
        _view_, platform = self._platform()
        assert platform.viewMatrix()[2][3] != 0.0

    def test_the_point_it_looks_at_lands_in_the_middle_of_the_screen(self) -> None:
        view, platform = self._platform(centre=(50.0, -30.0), ground=10.0)
        matrix = platform.modelMatrix() @ platform.viewMatrix()
        target = np.append(view.target(), 1.0)
        clip = target @ matrix
        assert (clip[0] / clip[3], clip[1] / clip[3]) == pytest.approx((0.0, 0.0),
                                                                       abs=1e-4)

    def test_its_inverse_is_an_inverse(self) -> None:
        _view_, platform = self._platform()
        product = platform.modelMatrix() @ platform.modelMatrix(inverse=True)
        assert np.allclose(product, np.eye(4), atol=1e-4)
