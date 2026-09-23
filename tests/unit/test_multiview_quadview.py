"""An editor's four views: top, front and side orthographic, and a perspective one.

The layout, framing a box in all four, and the pointer gestures that move each
view's camera: a drag pans an orthographic view and orbits the perspective one,
and the wheel zooms whichever the pointer is over.

Headless: views, cameras and arithmetic.
"""
import numpy as np
import pytest

from OpenGLContext.edit.orbitview import OrbitViewPlatform
from OpenGLContext.multiview.cameras import OrthoViewPlatform
from OpenGLContext.multiview.quad import QuadView

WINDOW = (800, 600)
LOW, HIGH = (-0.3, 0.0, -0.2), (0.3, 1.8, 0.2)


def _quad(**named):
    quad = QuadView(**named)
    quad.layout.arrange(*WINDOW)
    quad.frame(LOW, HIGH)
    return quad


def _ndc(view, point):
    camera = view.camera
    clip = np.append(np.asarray(point, 'd'), 1.0) @ camera.matrix()
    return clip[:3] / clip[3]


def _centre_of(view):
    x, y, width, height = view.rect
    return x + width / 2.0, y + height / 2.0


class TestTheLayout:
    def test_three_orthographic_views_and_a_perspective_one(self):
        quad = QuadView()
        names = [view.name for view in quad.layout.views]
        assert names == ['top', 'front', 'left', 'perspective']
        assert quad.layout.arrangement == 'quad'
        for view in quad.layout.views[:3]:
            assert isinstance(view.camera, OrthoViewPlatform)
            assert view.camera.view.direction == view.name
        assert isinstance(quad.layout.views[3].camera, OrbitViewPlatform)

    def test_the_orthographic_views_can_be_chosen(self):
        quad = QuadView(directions=('front', 'right', 'bottom'))
        assert [view.name for view in quad.layout.views[:3]] == ['front', 'right', 'bottom']

    def test_the_orthographic_views_clear_to_a_flat_colour(self):
        quad = QuadView(background=(0.3, 0.3, 0.3))
        for view in quad.layout.views[:3]:
            assert view.style.background == (0.3, 0.3, 0.3)
        assert quad.layout.views[3].style.background is True

    def test_a_view_is_found_by_its_name(self):
        quad = QuadView()
        assert quad.view('front') is quad.layout.views[1]
        assert quad.view('nowhere') is None


class TestFraming:
    def test_the_box_is_on_screen_in_every_view(self):
        quad = _quad()
        corners = [(x, y, z) for x in (LOW[0], HIGH[0]) for y in (LOW[1], HIGH[1])
                   for z in (LOW[2], HIGH[2])]
        for view in quad.layout.views:
            for corner in corners:
                assert np.all(np.abs(_ndc(view, corner)) <= 1.0 + 1e-5), (view.name, corner)

    def test_framing_before_the_window_is_known_uses_a_square(self):
        quad = QuadView()
        quad.frame(LOW, HIGH)
        assert quad.view('front').camera.view.centre == pytest.approx((0.0, 0.9, 0.0))

    def test_the_perspective_view_may_come_as_close_as_a_small_model_needs(self):
        quad = _quad()
        assert quad.orbit.distance < 5.0


class TestDragging:
    def test_a_drag_in_an_orthographic_view_pans_only_that_view(self):
        quad = _quad()
        front, top = quad.view('front'), quad.view('top')
        before_top = top.camera.view.centre
        x, y = _centre_of(front)
        under = front.camera.view.world_from_screen(*front.local(x, y), front.size)
        assert quad.press(front, x, y, 2)
        assert quad.drag(front, x + 25, y - 10)
        after = front.camera.view.world_from_screen(*front.local(x + 25, y - 10), front.size)
        assert np.allclose(under, after)
        assert top.camera.view.centre == before_top

    def test_a_right_drag_in_the_perspective_view_orbits_it(self):
        quad = _quad()
        view = quad.view('perspective')
        target = quad.orbit.target().copy()
        heading = quad.orbit.heading
        x, y = _centre_of(view)
        quad.press(view, x, y, 2)
        quad.drag(view, x + 40, y)
        assert quad.orbit.heading != heading
        assert np.allclose(quad.orbit.target(), target)

    @pytest.mark.parametrize('button', [1])
    def test_another_button_pans_the_perspective_view(self, button):
        quad = _quad()
        view = quad.view('perspective')
        target = quad.orbit.target().copy()
        heading = quad.orbit.heading
        x, y = _centre_of(view)
        quad.press(view, x, y, button)
        quad.drag(view, x + 40, y + 10)
        assert quad.orbit.heading == heading
        assert not np.allclose(quad.orbit.target(), target)

    def test_a_perspective_pan_carries_the_target_with_the_pointer(self):
        quad = _quad()
        view = quad.view('perspective')
        before = quad.orbit.target().copy()
        x, y = _centre_of(view)
        quad.press(view, x, y, 1)
        quad.drag(view, x + 30, y)
        ndc = _ndc(view, before)
        assert ndc[0] * view.size[0] / 2.0 == pytest.approx(30.0, abs=0.01)
        assert ndc[1] == pytest.approx(0.0, abs=1e-5)

    def test_after_the_release_a_drag_moves_nothing(self):
        quad = _quad()
        front = quad.view('front')
        x, y = _centre_of(front)
        quad.press(front, x, y, 2)
        quad.release(front, x, y)
        centre = front.camera.view.centre
        assert not quad.drag(front, x + 50, y)
        assert front.camera.view.centre == centre

    def test_a_view_that_is_not_the_quads_is_left_alone(self):
        from OpenGLContext.multiview.views import View
        quad = _quad()
        assert not quad.press(View(), 10, 10, 2)
        assert not quad.wheel(View(), 10, 10, 1)


class TestTheWheel:
    def test_a_notch_over_an_orthographic_view_zooms_about_the_pointer(self):
        quad = _quad()
        top = quad.view('top')
        x, y = top.rect[0] + 30, top.rect[1] + 40
        under = top.camera.view.world_from_screen(*top.local(x, y), top.size)
        span = top.camera.view.span
        assert quad.wheel(top, x, y, 1)
        assert top.camera.view.span < span
        assert np.allclose(top.camera.view.world_from_screen(*top.local(x, y), top.size), under)

    def test_a_notch_over_the_perspective_view_dollies_it(self):
        quad = _quad()
        view = quad.view('perspective')
        distance = quad.orbit.distance
        quad.wheel(view, *_centre_of(view), 1)
        assert quad.orbit.distance < distance
        quad.wheel(view, *_centre_of(view), -2)
        assert quad.orbit.distance > distance



class TestEngineEvents:
    """``handle`` reads the context's own events and routes them through the layout."""

    def _button(self, quad, x, y, button, state):
        from OpenGLContext.events.mouseevents import MouseButtonEvent
        event = MouseButtonEvent()
        event.button, event.state, event.modifiers = button, state, (0, 0, 0)
        event.pickPoint = (x, y)
        return event

    def _move(self, x, y):
        from OpenGLContext.events.mouseevents import MouseMoveEvent
        event = MouseMoveEvent()
        event.pickPoint = (x, y)
        event.modifiers = (0, 0, 0)
        return event

    def test_a_press_a_move_and_a_release_pan_an_orthographic_view(self):
        quad = _quad()
        front = quad.view('front')
        x, y = _centre_of(front)
        centre = front.camera.view.centre
        assert quad.handle(self._button(quad, x, y, 2, 1))
        assert quad.handle(self._move(x + 20, y))
        assert front.camera.view.centre != centre
        assert quad.handle(self._button(quad, x + 20, y, 2, 0))
        moved = front.camera.view.centre
        assert not quad.handle(self._move(x + 60, y))
        assert front.camera.view.centre == moved

    def test_a_wheel_notch_zooms_the_view_under_the_pointer(self):
        from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP
        quad = _quad()
        top = quad.view('top')
        span = top.camera.view.span
        assert quad.handle(self._button(quad, *_centre_of(top), WHEEL_UP, 1))
        assert top.camera.view.span < span
        # The notch's release is part of the same notch.
        assert quad.handle(self._button(quad, *_centre_of(top), WHEEL_UP, 0))
        quad.handle(self._button(quad, *_centre_of(top), WHEEL_DOWN, 1))
        assert top.camera.view.span == pytest.approx(span)

    def test_an_event_it_has_no_use_for_is_left_for_others(self):
        from OpenGLContext.events.keyboardevents import KeypressEvent
        quad = _quad()
        assert not quad.handle(KeypressEvent())


class TestWhatThePerspectiveViewOpensOn:
    """Thirty degrees round from the front, or the scene's own camera."""

    def _camera(self, name='cam', position=(3.0, 1.0, 4.0)):
        from OpenGLContext.multiview.viewpoints import SceneCamera
        forward = -np.asarray(position, 'd') / np.linalg.norm(position)
        return SceneCamera(name=name, position=position, forward=tuple(forward),
                           up=(0.0, 1.0, 0.0), fov=0.8)

    def test_with_no_cameras_it_looks_from_thirty_degrees_off_the_front(self):
        orbit = _quad().orbit
        eye = orbit.position() - orbit.target()
        across = np.degrees(np.arctan2(eye[0], eye[2]))
        assert across == pytest.approx(30.0)

    def test_it_is_not_looking_along_an_axis_the_other_views_show(self):
        orbit = _quad().orbit
        eye = orbit.position() - orbit.target()
        assert abs(eye[0]) > 0.1 * np.linalg.norm(eye)
        assert eye[1] > 0.1 * np.linalg.norm(eye)

    def test_the_first_camera_found_is_the_one_it_opens_on(self):
        quad = _quad()
        chosen = quad.cameras_found([self._camera('a'), self._camera('b', (0, 2, 5))])
        assert chosen.name == 'a'
        assert quad.orbit.position() == pytest.approx((3.0, 1.0, 4.0))

    def test_what_the_camera_looks_at_is_what_it_orbits(self):
        quad = _quad()
        quad.cameras_found([self._camera()])
        assert _ndc(quad.view('perspective'), (0.0, 0.0, 0.0))[:2] == \
            pytest.approx((0.0, 0.0), abs=1e-5)

    def test_the_application_chooses_which_one(self):
        quad = _quad(choose_camera=lambda cameras: cameras[-1])
        chosen = quad.cameras_found([self._camera('a'), self._camera('b', (0, 2, 5))])
        assert chosen.name == 'b'
        assert quad.orbit.position() == pytest.approx((0.0, 2.0, 5.0))

    def test_the_application_can_choose_none_of_them(self):
        quad = _quad(choose_camera=lambda cameras: None)
        before = quad.orbit.position().copy()
        assert quad.cameras_found([self._camera()]) is None
        assert quad.orbit.position() == pytest.approx(before)

    def test_cameras_found_again_do_not_move_the_view(self):
        quad = _quad()
        quad.cameras_found([self._camera()])
        quad.orbit.orbit(40.0, 0.0)
        moved = quad.orbit.position().copy()
        assert quad.cameras_found([self._camera(), self._camera('b')]) is None
        assert quad.orbit.position() == pytest.approx(moved)
        assert [camera.name for camera in quad.cameras] == ['cam', 'b']

    def test_a_camera_can_be_looked_through_later(self):
        quad = _quad()
        assert quad.look_through(self._camera('b', (0.0, 2.0, 5.0)))
        assert quad.orbit.position() == pytest.approx((0.0, 2.0, 5.0))

    def test_a_model_can_be_looked_up_at(self):
        quad = _quad()
        quad.orbit.orbit(0.0, -120.0)
        assert quad.orbit.pitch < 0.0
