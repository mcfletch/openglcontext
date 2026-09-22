"""Pointer gestures that move the camera of the view they land in.

What :class:`~OpenGLContext.multiview.quad.QuadView` moves its four views with,
offered to an application that lays out views of its own: a plan camera, an
orthographic elevation and a perspective view each answer the pointer as their
kind does, and an application that drives one of its views itself keeps that
view out of the set.

Headless: views, cameras and arithmetic.
"""
import numpy as np
import pytest

from OpenGLContext.edit.mapview import MapView, MapViewPlatform
from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform
from OpenGLContext.multiview.gestures import ViewGestures
from OpenGLContext.multiview.views import View, ViewLayout

WINDOW = (800, 600)


def _views():
    """A plan view, an elevation and a perspective view, as an editor has them."""
    plan = View(MapViewPlatform(MapView(centre=(0.0, 0.0), span=400.0)), name='map')
    front = View(OrthoViewPlatform(OrthoView('front', centre=(0.0, 0.0, 0.0),
                                             span=400.0)), name='front')
    angled = View(OrbitViewPlatform(OrbitView(centre=(0.0, 0.0), distance=300.0)),
                  name='angled')
    return plan, front, angled


def _laid_out(**named):
    plan, front, angled = _views()
    layout = ViewLayout.quad(plan, front, angled, View(name='spare'))
    layout.arrange(*WINDOW)
    return ViewGestures(layout, **named), layout


def _centre_of(view):
    x, y, width, height = view.rect
    return x + width / 2.0, y + height / 2.0


class TestWhichViewsItDrives:
    def test_every_view_of_the_layout_by_default(self):
        gestures, layout = _laid_out()
        assert all(gestures.drives(view) for view in layout.views[:3])

    def test_a_view_the_application_moves_itself_is_left_alone(self):
        gestures, layout = _laid_out()
        gestures.views = layout.views[1:]
        plan = layout.views[0]
        centre = plan.camera.view.centre
        assert not gestures.drives(plan)
        assert not gestures.press(plan, *_centre_of(plan), 0)
        assert not gestures.wheel(plan, *_centre_of(plan), 1)
        assert plan.camera.view.centre == centre

    def test_a_view_of_another_layout_is_not_ours(self):
        gestures, _layout = _laid_out()
        assert not gestures.drives(View(name='elsewhere'))

    def test_a_view_with_no_camera_of_its_own_is_not_driven(self):
        gestures, layout = _laid_out()
        assert not gestures.press(layout.views[3], 10, 10, 0)


class TestThePlanView:
    def test_a_drag_carries_the_world_with_the_pointer(self):
        gestures, layout = _laid_out()
        plan = layout.views[0]
        x, y = _centre_of(plan)
        under = plan.camera.view.world_from_screen(*plan.local(x, y), plan.size)
        assert gestures.press(plan, x, y, 0)
        assert gestures.drag(plan, x + 30, y - 12)
        after = plan.camera.view.world_from_screen(*plan.local(x + 30, y - 12), plan.size)
        assert np.allclose(under, after)

    def test_the_pan_is_measured_in_the_views_own_pixels(self):
        """The view's rectangle, not the window's: the scales differ by four."""
        gestures, layout = _laid_out()
        plan = layout.views[0]
        assert plan.size != WINDOW
        metres = plan.camera.view.metres_per_pixel(plan.size)
        centre = plan.camera.view.centre
        gestures.press(plan, *_centre_of(plan), 0)
        gestures.drag(plan, _centre_of(plan)[0] + 10, _centre_of(plan)[1])
        assert centre[0] - plan.camera.view.centre[0] == pytest.approx(10.0 * metres)

    def test_a_notch_zooms_about_the_pointer(self):
        gestures, layout = _laid_out()
        plan = layout.views[0]
        x, y = plan.rect[0] + 20, plan.rect[1] + 30
        under = plan.camera.view.world_from_screen(*plan.local(x, y), plan.size)
        span = plan.camera.view.span
        assert gestures.wheel(plan, x, y, 1)
        assert plan.camera.view.span < span
        assert np.allclose(
            plan.camera.view.world_from_screen(*plan.local(x, y), plan.size), under)


class TestTheElevation:
    def test_a_drag_pans_it(self):
        gestures, layout = _laid_out()
        front = layout.views[1]
        centre = np.array(front.camera.view.centre)
        gestures.press(front, *_centre_of(front), 0)
        gestures.drag(front, _centre_of(front)[0] + 15, _centre_of(front)[1])
        assert not np.allclose(front.camera.view.centre, centre)


class TestThePerspectiveView:
    def test_the_left_button_orbits_and_another_pans(self):
        gestures, layout = _laid_out()
        angled = layout.views[2]
        camera = angled.camera.view
        heading, target = camera.heading, camera.target().copy()
        gestures.press(angled, *_centre_of(angled), 0)
        gestures.drag(angled, _centre_of(angled)[0] + 40, _centre_of(angled)[1])
        assert camera.heading != heading
        assert np.allclose(camera.target(), target)
        gestures.release(angled, 0, 0)
        gestures.press(angled, *_centre_of(angled), 2)
        gestures.drag(angled, _centre_of(angled)[0] + 40, _centre_of(angled)[1])
        assert not np.allclose(camera.target(), target)

    def test_a_notch_dollies_it(self):
        gestures, layout = _laid_out()
        angled = layout.views[2]
        distance = angled.camera.view.distance
        assert gestures.wheel(angled, *_centre_of(angled), 1)
        assert angled.camera.view.distance < distance


class TestAGestureStaysWithItsView:
    def test_a_drag_that_leaves_the_view_keeps_moving_it(self):
        gestures, layout = _laid_out()
        front, plan = layout.views[1], layout.views[0]
        plan_centre = plan.camera.view.centre
        gestures.press(front, *_centre_of(front), 0)
        # The pointer is over the plan view now; the gesture began in the
        # elevation and the elevation is what moves.
        assert gestures.drag(plan, *_centre_of(plan))
        assert plan.camera.view.centre == plan_centre

    def test_nothing_moves_after_the_release(self):
        gestures, layout = _laid_out()
        front = layout.views[1]
        gestures.press(front, *_centre_of(front), 0)
        assert gestures.release(front, *_centre_of(front))
        centre = np.array(front.camera.view.centre)
        assert not gestures.drag(front, _centre_of(front)[0] + 50, _centre_of(front)[1])
        assert np.allclose(front.camera.view.centre, centre)


class TestReadingTheContextsEvents:
    def _button(self, x, y, button, state):
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

    def test_an_unrouted_event_is_routed_through_the_layout(self):
        gestures, layout = _laid_out()
        front = layout.views[1]
        centre = np.array(front.camera.view.centre)
        assert gestures.handle(self._button(*_centre_of(front), 0, 1))
        assert gestures.handle(self._move(_centre_of(front)[0] + 20, _centre_of(front)[1]))
        assert not np.allclose(front.camera.view.centre, centre)

    def test_an_event_in_a_view_it_does_not_drive_is_left_for_the_application(self):
        gestures, layout = _laid_out()
        gestures.views = layout.views[1:]
        assert not gestures.handle(self._button(*_centre_of(layout.views[0]), 0, 1))

    def test_a_key_is_none_of_its_business(self):
        from OpenGLContext.events.keyboardevents import KeypressEvent
        gestures, _layout = _laid_out()
        assert not gestures.handle(KeypressEvent())

    def test_the_layout_it_reads_can_be_replaced(self):
        """A window that changes its arrangement hands the gestures the new one."""
        gestures, layout = _laid_out()
        plan, front, angled = _views()
        other = ViewLayout.split(plan, angled)
        other.arrange(*WINDOW)
        gestures.layout = other
        assert gestures.drives(plan)
        assert not gestures.drives(layout.views[1])
        assert gestures.handle(self._button(*_centre_of(plan), 0, 1))
