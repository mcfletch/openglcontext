"""A world seen from straight above, at a scale rather than at a distance.

An editor's plan view. The projection is orthographic, so a metre is the same
number of pixels wherever it is on screen: what is drawn is a *map*, and a
route drawn on it with the pointer is the route the world gets.

Headless: a map view is a centre, a scale and two matrices.
"""
import numpy as np
import pytest

from OpenGLContext.edit.mapview import MapView, MapViewPlatform

VIEWPORT = (800, 600)


def _view(**named):
    named.setdefault('span', 600.0)
    return MapView(**named)


def _project(view, point, viewport=VIEWPORT):
    """Where a world point lands in normalised device coordinates."""
    model, projection = view.matrices(viewport)
    clip = np.append(np.asarray(point, 'd'), 1.0) @ model @ projection
    return clip[:3] / clip[3]


class TestWhatItLooksAt:
    def test_the_centre_of_the_screen_is_the_centre_of_the_view(self) -> None:
        view = _view(centre=(120.0, -40.0))
        assert np.allclose(_project(view, (120.0, 0.0, -40.0))[:2], (0, 0),
                           atol=1e-5)

    def test_north_is_up(self) -> None:
        """Decreasing z is up the screen, which is what a map does with north."""
        view = _view(centre=(0.0, 0.0))
        assert _project(view, (0.0, 0.0, -100.0))[1] > 0.0

    def test_east_is_right(self) -> None:
        view = _view(centre=(0.0, 0.0))
        assert _project(view, (100.0, 0.0, 0.0))[0] > 0.0

    def test_the_span_is_the_height_of_the_window(self) -> None:
        """Half a span above the centre is the top edge of the screen."""
        view = _view(centre=(0.0, 0.0), span=600.0)
        assert _project(view, (0.0, 0.0, -300.0))[1] == pytest.approx(1.0, abs=1e-5)

    def test_the_width_follows_the_shape_of_the_window(self) -> None:
        view = _view(centre=(0.0, 0.0), span=600.0)
        half = 600.0 * VIEWPORT[0] / VIEWPORT[1] / 2.0
        assert _project(view, (half, 0.0, 0.0))[0] == pytest.approx(1.0, abs=1e-5)

    def test_height_does_not_change_where_a_point_lands(self) -> None:
        """Which is what makes it a map and not a photograph."""
        view = _view(centre=(0.0, 0.0))
        low = _project(view, (100.0, 0.0, 50.0))[:2]
        high = _project(view, (100.0, 900.0, 50.0))[:2]
        assert np.allclose(low, high, atol=1e-6)

    def test_the_ground_is_between_the_clipping_planes(self) -> None:
        view = _view(centre=(0.0, 0.0), floor=-200.0, ceiling=800.0)
        for height in (-199.0, 0.0, 799.0):
            depth = _project(view, (0.0, height, 0.0))[2]
            assert -1.0 <= depth <= 1.0

    def test_higher_ground_is_nearer(self) -> None:
        view = _view(centre=(0.0, 0.0))
        assert _project(view, (0, 100.0, 0))[2] < _project(view, (0, 0.0, 0))[2]


class TestReadingThePointer:
    def test_the_middle_of_the_window_is_the_centre(self) -> None:
        view = _view(centre=(120.0, -40.0))
        x, z = view.world_from_screen(400, 300, VIEWPORT)
        assert (x, z) == pytest.approx((120.0, -40.0), abs=1e-6)

    def test_the_right_of_the_window_is_east_of_it(self) -> None:
        view = _view(centre=(0.0, 0.0))
        assert view.world_from_screen(700, 300, VIEWPORT)[0] > 0.0

    def test_the_top_of_the_window_is_north_of_it(self) -> None:
        view = _view(centre=(0.0, 0.0))
        assert view.world_from_screen(400, 550, VIEWPORT)[1] < 0.0

    def test_a_metre_is_the_same_size_everywhere(self) -> None:
        view = _view(centre=(0.0, 0.0), span=600.0)
        near = view.world_from_screen(401, 300, VIEWPORT)[0] \
            - view.world_from_screen(400, 300, VIEWPORT)[0]
        far = view.world_from_screen(11, 20, VIEWPORT)[0] \
            - view.world_from_screen(10, 20, VIEWPORT)[0]
        assert near == pytest.approx(far, abs=1e-9)

    def test_it_goes_back_the_way_it_came(self) -> None:
        view = _view(centre=(35.0, 190.0), span=420.0)
        for screen in ((0, 0), (400, 300), (799, 599), (123, 456)):
            world = view.world_from_screen(*screen, VIEWPORT)
            assert view.screen_from_world(
                (world[0], 0.0, world[1]), VIEWPORT) == pytest.approx(screen,
                                                                      abs=1e-6)

    def test_the_scale_is_metres_per_pixel(self) -> None:
        view = _view(span=600.0)
        assert view.metres_per_pixel(VIEWPORT) == pytest.approx(1.0)
        assert _view(span=1200.0).metres_per_pixel(VIEWPORT) \
            == pytest.approx(2.0)


class TestMovingAbout:
    def test_panning_moves_the_centre_by_what_the_pointer_moved(self) -> None:
        view = _view(centre=(0.0, 0.0), span=600.0)
        view.pan(10, 0, VIEWPORT)
        assert view.centre[0] == pytest.approx(-10.0)

    def test_dragging_up_moves_the_view_south(self) -> None:
        view = _view(centre=(0.0, 0.0), span=600.0)
        view.pan(0, 10, VIEWPORT)
        assert view.centre[1] == pytest.approx(10.0)

    def test_zooming_in_shrinks_the_span(self) -> None:
        view = _view(span=600.0)
        view.zoom(0.5)
        assert view.span == pytest.approx(300.0)

    def test_zooming_holds_the_point_under_the_cursor(self) -> None:
        """A map that slides out from under the pointer while you zoom is
        unusable; the point you are looking at is the point you keep."""
        view = _view(centre=(0.0, 0.0), span=600.0)
        under = view.world_from_screen(700, 500, VIEWPORT)
        view.zoom(0.5, at=(700, 500), viewport=VIEWPORT)
        assert view.world_from_screen(700, 500, VIEWPORT) \
            == pytest.approx(under, abs=1e-6)

    def test_zooming_without_a_cursor_holds_the_centre(self) -> None:
        view = _view(centre=(15.0, -25.0), span=600.0)
        view.zoom(2.0)
        assert view.centre == pytest.approx((15.0, -25.0))

    def test_it_will_not_zoom_past_its_limits(self) -> None:
        view = _view(span=600.0, smallest=50.0, largest=4000.0)
        view.zoom(0.001)
        assert view.span == pytest.approx(50.0)
        view.zoom(1000.0)
        assert view.span == pytest.approx(4000.0)

    def test_it_can_be_framed_on_a_region(self) -> None:
        view = _view()
        view.frame((-500.0, -200.0), (500.0, 200.0), VIEWPORT)
        assert view.centre == pytest.approx((0.0, 0.0))
        # 1000 m across a 800-pixel window is 1.25 m/pixel; 400 m down 600
        # pixels is 0.67. The wider one decides, so everything fits.
        assert view.span == pytest.approx(1000.0 * VIEWPORT[1] / VIEWPORT[0])


class TestTheCameraItMakes:
    def test_the_platform_reports_the_map_s_matrices(self) -> None:
        view = _view(centre=(10.0, 20.0))
        platform = MapViewPlatform(view)
        platform.setViewport(*VIEWPORT)
        model, projection = view.matrices(VIEWPORT)
        assert np.allclose(platform.viewMatrix(), projection, atol=1e-6)
        assert np.allclose(platform.matrix(), model @ projection, atol=1e-6)

    def test_it_follows_the_map_when_the_map_moves(self) -> None:
        view = _view(centre=(0.0, 0.0))
        platform = MapViewPlatform(view)
        platform.setViewport(*VIEWPORT)
        before = np.array(platform.matrix())
        view.pan(50, 0, VIEWPORT)
        assert not np.allclose(before, platform.matrix())

    def test_it_sits_above_what_it_looks_at(self) -> None:
        """So a frustum test and a near plane both mean something."""
        view = _view(centre=(10.0, 20.0), ceiling=900.0)
        platform = MapViewPlatform(view)
        assert platform.position[1] >= 900.0
        assert tuple(platform.position[:3:2]) == pytest.approx((10.0, 20.0))


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
