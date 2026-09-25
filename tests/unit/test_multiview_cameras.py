"""A world seen along one axis, at a scale rather than at a distance.

The top, front and side views of an editor. The projection is orthographic,
so a unit is the same number of pixels wherever it is on screen, and a point
dragged in one of these views moves in that view's plane.

Headless: an orthographic view is a direction, a centre, a scale and two
matrices.
"""
import numpy as np
import pytest

from OpenGLContext.multiview.cameras import DIRECTIONS, OrthoView, OrthoViewPlatform

VIEWPORT = (400, 300)


def _project(view, point, viewport=VIEWPORT):
    """Where a world point lands in normalised device coordinates."""
    model, projection = view.matrices(viewport)
    clip = np.append(np.asarray(point, 'd'), 1.0) @ model @ projection
    return clip[:3] / clip[3]


class TestTheDirections:
    @pytest.mark.parametrize('direction, right, up', [
        ('front', (1, 0, 0), (0, 1, 0)),
        ('back', (-1, 0, 0), (0, 1, 0)),
        ('right', (0, 0, -1), (0, 1, 0)),
        ('left', (0, 0, 1), (0, 1, 0)),
        ('top', (1, 0, 0), (0, 0, -1)),
        ('bottom', (1, 0, 0), (0, 0, 1)),
    ])
    def test_each_puts_its_axes_on_the_screen(self, direction, right, up):
        view = OrthoView(direction, span=10.0)
        assert _project(view, np.asarray(right, 'd'))[0] > 0.1
        assert abs(_project(view, np.asarray(right, 'd'))[1]) < 1e-6
        assert _project(view, np.asarray(up, 'd'))[1] > 0.1
        assert abs(_project(view, np.asarray(up, 'd'))[0]) < 1e-6

    def test_front_looks_down_minus_z_from_plus_z(self):
        """VRML's own default view, and glTF's front."""
        view = OrthoView('front', span=10.0)
        near, far = _project(view, (0, 0, 1))[2], _project(view, (0, 0, -1))[2]
        assert near < far

    def test_top_is_the_plan_view_a_map_draws(self):
        from OpenGLContext.edit.mapview import MapView
        ortho = OrthoView('top', centre=(5.0, 0.0, -3.0), span=40.0)
        plan = MapView(centre=(5.0, -3.0), span=40.0)
        for point in [(9.0, 2.0, -1.0), (0.0, -4.0, -12.0)]:
            assert np.allclose(_project(ortho, point)[:2], _project(plan, point)[:2],
                               atol=1e-6)

    def test_every_direction_is_listed(self):
        assert set(DIRECTIONS) == {'front', 'back', 'left', 'right', 'top', 'bottom'}

    def test_an_unknown_direction_is_refused(self):
        with pytest.raises(ValueError):
            OrthoView('sideways')


class TestWhatItHolds:
    def test_the_centre_is_the_middle_of_the_screen(self):
        view = OrthoView('right', centre=(1.0, 2.0, 3.0), span=10.0)
        assert np.allclose(_project(view, (1.0, 2.0, 3.0))[:2], (0, 0), atol=1e-6)

    def test_the_span_is_the_height_of_the_view(self):
        view = OrthoView('front', span=8.0)
        assert _project(view, (0.0, 4.0, 0.0))[1] == pytest.approx(1.0)

    def test_the_width_follows_the_shape_of_the_view(self):
        view = OrthoView('front', span=8.0)
        half = 4.0 * VIEWPORT[0] / VIEWPORT[1]
        assert _project(view, (half, 0.0, 0.0))[0] == pytest.approx(1.0)

    def test_depth_along_the_axis_does_not_move_a_point(self):
        view = OrthoView('left', span=8.0)
        assert np.allclose(_project(view, (-2.0, 1.0, 1.0))[:2],
                           _project(view, (2.0, 1.0, 1.0))[:2], atol=1e-6)

    def test_everything_within_the_depth_is_between_the_planes(self):
        view = OrthoView('top', centre=(0.0, 0.0, 0.0), span=8.0, depth=100.0)
        for height in (-49.0, 0.0, 49.0):
            assert -1.0 < _project(view, (0.0, height, 0.0))[2] < 1.0

    def test_the_span_is_held_to_its_limits(self):
        view = OrthoView('front', span=1.0, smallest=2.0, largest=5.0)
        assert view.span == 2.0
        view.span = 50.0
        assert view.span == 5.0


class TestReadingThePointer:
    def test_the_middle_pixel_is_the_centre(self):
        view = OrthoView('front', centre=(1.0, 2.0, 3.0), span=10.0)
        assert np.allclose(view.world_from_screen(200, 150, VIEWPORT), (1.0, 2.0, 3.0))

    def test_a_pixel_and_its_world_point_are_one_conversion_apart(self):
        for direction in DIRECTIONS:
            view = OrthoView(direction, centre=(1.0, -2.0, 0.5), span=12.0)
            point = view.world_from_screen(310.0, 42.0, VIEWPORT)
            assert np.allclose(view.screen_from_world(point, VIEWPORT), (310.0, 42.0))

    def test_the_point_found_is_where_the_camera_draws_it(self):
        view = OrthoView('right', centre=(0.0, 1.0, 0.0), span=6.0)
        point = view.world_from_screen(300.0, 225.0, VIEWPORT)
        ndc = _project(view, point)
        assert np.allclose(((ndc[0] + 1) * 200, (ndc[1] + 1) * 150), (300.0, 225.0))

    def test_the_scale_is_units_per_pixel_down_the_view(self):
        assert OrthoView('top', span=30.0).units_per_pixel(VIEWPORT) == pytest.approx(0.1)


class TestMovingAbout:
    def test_a_pan_keeps_the_point_under_the_pointer(self):
        view = OrthoView('front', span=10.0)
        before = view.world_from_screen(100.0, 100.0, VIEWPORT)
        view.pan(30.0, -20.0, VIEWPORT)
        after = view.world_from_screen(130.0, 80.0, VIEWPORT)
        assert np.allclose(before, after)

    def test_a_pan_stays_in_the_views_plane(self):
        view = OrthoView('left', centre=(2.0, 0.0, 0.0), span=10.0)
        view.pan(50.0, 50.0, VIEWPORT)
        assert view.centre[0] == pytest.approx(2.0)

    def test_a_zoom_about_the_pointer_keeps_it_in_place(self):
        view = OrthoView('top', span=10.0)
        before = view.world_from_screen(50.0, 250.0, VIEWPORT)
        view.zoom(0.5, at=(50.0, 250.0), viewport=VIEWPORT)
        assert view.span == pytest.approx(5.0)
        assert np.allclose(view.world_from_screen(50.0, 250.0, VIEWPORT), before)

    def test_a_zoom_with_no_pointer_zooms_about_the_centre(self):
        view = OrthoView('top', centre=(1.0, 1.0, 1.0), span=10.0)
        view.zoom(2.0)
        assert view.span == pytest.approx(20.0)
        assert view.centre == pytest.approx((1.0, 1.0, 1.0))

    @pytest.mark.parametrize('direction', DIRECTIONS)
    def test_framing_a_box_puts_all_of_it_on_screen(self, direction):
        view = OrthoView(direction)
        minimum, maximum = (-1.0, 0.0, -3.0), (3.0, 2.0, 1.0)
        view.frame(minimum, maximum, VIEWPORT)
        corners = [(x, y, z) for x in (-1.0, 3.0) for y in (0.0, 2.0) for z in (-3.0, 1.0)]
        ndc = np.array([_project(view, corner) for corner in corners])
        assert np.all(np.abs(ndc) <= 1.0 + 1e-6)
        # ... and fills the view in one of its two directions.
        assert np.isclose(np.abs(ndc[:, :2]).max(), 1.0, atol=1e-6)


class TestThePlatform:
    def test_it_draws_what_the_view_describes(self):
        view = OrthoView('front', centre=(1.0, 2.0, 0.0), span=4.0)
        platform = OrthoViewPlatform(view, VIEWPORT)
        model, projection = view.matrices(VIEWPORT)
        assert np.allclose(platform.modelMatrix(), model)
        assert np.allclose(platform.viewMatrix(), projection)
        assert np.allclose(platform.matrix(), model @ projection, atol=1e-6)

    def test_it_reads_the_view_rather_than_copying_it(self):
        view = OrthoView('front', span=4.0)
        platform = OrthoViewPlatform(view, VIEWPORT)
        view.pan(40.0, 0.0, VIEWPORT)
        assert np.allclose(platform.modelMatrix(), view.matrices(VIEWPORT)[0])

    def test_the_view_it_draws_into_sets_its_aspect(self):
        view = OrthoView('front', span=4.0)
        platform = OrthoViewPlatform(view)
        platform.setViewport(200, 100)
        assert np.allclose(platform.viewMatrix(), view.matrices((200, 100))[1])

    def test_the_inverses_undo_the_matrices(self):
        platform = OrthoViewPlatform(OrthoView('right', span=4.0), VIEWPORT)
        assert np.allclose(platform.matrix() @ platform.matrix(inverse=True),
                           np.identity(4), atol=1e-5)
        assert np.allclose(platform.modelMatrix() @ platform.modelMatrix(inverse=True),
                           np.identity(4), atol=1e-5)
        assert np.allclose(platform.viewMatrix() @ platform.viewMatrix(inverse=True),
                           np.identity(4), atol=1e-5)

    def test_the_camera_stands_back_along_the_axis(self):
        view = OrthoView('front', centre=(0.0, 0.0, 0.0), span=4.0, depth=20.0)
        position = OrthoViewPlatform(view, VIEWPORT).position
        assert position[2] > 0.0 and position[0] == 0.0 and position[1] == 0.0

    def test_placing_the_camera_moves_the_view_in_its_plane(self):
        view = OrthoView('front', centre=(0.0, 0.0, 0.0), span=4.0)
        platform = OrthoViewPlatform(view, VIEWPORT)
        platform.setPosition((3.0, -1.0, 50.0))
        assert view.centre == pytest.approx((3.0, -1.0, 0.0))


class TestPointingAViewSomewhereElse:
    """What the view-name menu does: the kinds a view can be switched to."""

    def _views(self):
        from OpenGLContext.edit.mapview import MapView, MapViewPlatform
        from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
        from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform
        from OpenGLContext.multiview.views import View
        plan = View(MapViewPlatform(MapView(centre=(10.0, -4.0), span=200.0),
                                    (400, 300)), name='plan')
        front = View(OrthoViewPlatform(OrthoView('front', centre=(1.0, 2.0, 3.0),
                                                 span=50.0), (400, 300)),
                     name='front')
        angled = View(OrbitViewPlatform(OrbitView(centre=(5.0, 6.0), ground=1.0,
                                                  distance=80.0), (400, 300)),
                      name='angled')
        return plan, front, angled

    def test_it_says_what_kind_a_view_is(self):
        from OpenGLContext.multiview.cameras import view_kind
        plan, front, angled = self._views()
        assert view_kind(plan) == 'top'
        assert view_kind(front) == 'front'
        assert view_kind(angled) == 'perspective'
        angled.camera.view.orthographic = True
        assert view_kind(angled) == 'ortho'

    def test_an_elevation_turns_to_another_axis_in_place(self):
        """The camera is the same object, so whatever holds it keeps working."""
        from OpenGLContext.multiview.cameras import point_view, view_kind
        _plan, front, _angled = self._views()
        camera = front.camera
        assert point_view(front, 'left')
        assert front.camera is camera
        assert view_kind(front) == 'left'
        assert camera.view.centre == pytest.approx((1.0, 2.0, 3.0))
        assert camera.view.span == pytest.approx(50.0)

    def test_a_turning_camera_becomes_an_elevation_looking_at_the_same_place(self):
        from OpenGLContext.multiview.cameras import point_view, view_kind
        from OpenGLContext.multiview.cameras import OrthoViewPlatform
        _plan, _front, angled = self._views()
        target = angled.camera.view.target()
        assert point_view(angled, 'front')
        assert isinstance(angled.camera, OrthoViewPlatform)
        assert view_kind(angled) == 'front'
        assert angled.camera.view.centre == pytest.approx(tuple(target))
        assert angled.camera.viewport == (400, 300)

    def test_an_elevation_becomes_a_turning_camera_on_the_same_subject(self):
        from OpenGLContext.edit.orbitview import OrbitViewPlatform
        from OpenGLContext.multiview.cameras import point_view, view_kind
        _plan, front, _angled = self._views()
        assert point_view(front, 'perspective')
        assert isinstance(front.camera, OrbitViewPlatform)
        assert view_kind(front) == 'perspective'
        assert front.camera.view.target() == pytest.approx((1.0, 2.0, 3.0))

    def test_how_much_it_shows_survives_the_switch(self):
        """A view of a 50-unit subject stays a view of a 50-unit subject."""
        import math
        from OpenGLContext.multiview.cameras import point_view
        _plan, front, _angled = self._views()
        point_view(front, 'perspective')
        orbit = front.camera.view
        shown = 2.0 * orbit.distance * math.tan(math.radians(orbit.fov) / 2.0)
        assert shown == pytest.approx(50.0, rel=1e-6)

    def test_flat_and_perspective_are_the_same_camera_switched(self):
        from OpenGLContext.multiview.cameras import point_view, view_kind
        _plan, _front, angled = self._views()
        camera = angled.camera
        assert point_view(angled, 'ortho')
        assert angled.camera is camera
        assert camera.view.orthographic
        assert view_kind(angled) == 'ortho'
        assert point_view(angled, 'perspective')
        assert not camera.view.orthographic

    def test_a_plan_view_of_an_editor_turns_like_any_other(self):
        """A MapView is the top view; pointing it elsewhere gives it a camera."""
        from OpenGLContext.multiview.cameras import point_view, view_kind
        plan, _front, _angled = self._views()
        assert point_view(plan, 'right')
        assert view_kind(plan) == 'right'
        assert plan.camera.view.centre == pytest.approx((10.0, 0.0, -4.0))

    def test_a_kind_nobody_has_is_refused(self):
        from OpenGLContext.multiview.cameras import point_view
        _plan, front, _angled = self._views()
        with pytest.raises(ValueError):
            point_view(front, 'sideways')

    def test_a_view_with_no_camera_cannot_be_pointed(self):
        from OpenGLContext.multiview.cameras import point_view, view_kind
        from OpenGLContext.multiview.views import View
        plain = View(name='plain')
        assert not point_view(plain, 'top')
        assert view_kind(plain) is None


class TestASmallSubjectAcrossASwitch:
    """A view of a two-unit object stays a view of a two-unit object."""

    def _front(self):
        from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform
        from OpenGLContext.multiview.views import View
        return View(OrthoViewPlatform(OrthoView('front', span=2.0), (400, 300)),
                    name='front')

    def test_a_round_trip_keeps_what_the_view_shows(self):
        from OpenGLContext.multiview.cameras import point_view, shown_by
        view = self._front()
        before = shown_by(view.camera.view)
        point_view(view, 'perspective')
        assert shown_by(view.camera.view)[1] == pytest.approx(before[1])
        point_view(view, 'front')
        after = shown_by(view.camera.view)
        assert after[0] == pytest.approx(before[0])
        assert after[1] == pytest.approx(before[1])

    def test_the_turning_camera_can_be_dollied_closer(self):
        from OpenGLContext.multiview.cameras import point_view
        view = self._front()
        point_view(view, 'perspective')
        orbit = view.camera.view
        distance = orbit.distance
        orbit.dolly(0.5)
        assert orbit.distance == pytest.approx(distance * 0.5)

    def test_the_turning_camera_can_look_up_from_below(self):
        from OpenGLContext.multiview.cameras import point_view
        view = self._front()
        point_view(view, 'perspective')
        orbit = view.camera.view
        orbit.orbit(0.0, -90.0 - orbit.pitch)
        assert orbit.pitch < 0.0
