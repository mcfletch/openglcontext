"""Several arrangements of one set of views, shown by name.

A window that offers more than one way to look at a scene -- a plan alone, the
plan beside a perspective view, all four at once -- keeps one set of cameras
and changes which of them are on screen, so a switch shows what was already
being looked at. ``ViewSet`` holds the views, the arrangements, the pointer
gestures and the framing.

Headless: views, cameras and arithmetic.
"""
import numpy as np
import pytest

from OpenGLContext.edit.mapview import MapView, MapViewPlatform
from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform
from OpenGLContext.multiview.views import View
from OpenGLContext.multiview.viewset import ViewSet

WINDOW = (800, 600)
LOW, HIGH = (-200.0, 0.0, -200.0), (200.0, 60.0, 200.0)


def _views():
    plan = View(MapViewPlatform(MapView(span=400.0)), name='plan')
    front = View(OrthoViewPlatform(OrthoView('front')), name='front')
    left = View(OrthoViewPlatform(OrthoView('left')), name='left')
    angled = View(OrbitViewPlatform(OrbitView()), name='angled')
    return [plan, front, left, angled]


def _set(**named):
    views = ViewSet(_views(), **named)
    views.arrange(*WINDOW)
    return views


def _centre_of(view):
    x, y, width, height = view.rect
    return x + width / 2.0, y + height / 2.0


def _ndc(view, point):
    clip = np.append(np.asarray(point, 'd'), 1.0) @ view.camera.matrix()
    return clip[:3] / clip[3]


class _Event:
    view = None

    def __init__(self, x, y, button=0, state=1, kind='mousebutton'):
        self.type, self.button, self.state = kind, button, state
        self._point = (x, y)

    def getPickPoint(self):
        return self._point

    def getModifiers(self):
        return (0, 0, 0)


class TestTheArrangementsItOffers:
    def test_each_view_on_its_own_and_the_split_and_the_quad(self):
        views = _set()
        assert list(views.arrangements) == ['plan', 'front', 'left', 'angled',
                                            'split', 'quad']

    def test_it_opens_on_the_first_one(self):
        views = _set()
        assert views.mode == 'plan'
        assert views.layout.views == [views.view('plan')]

    def test_the_arrangements_can_be_named(self):
        views = _set(arrangements={'map': ('plan',),
                                   'both': ('plan', 'angled')})
        assert list(views.arrangements) == ['map', 'both']
        assert views.mode == 'map'
        views.show('both')
        assert [view.name for view in views.layout.views] == ['plan', 'angled']

    def test_it_opens_on_the_arrangement_asked_for(self):
        views = _set(mode='quad')
        assert views.mode == 'quad'
        assert len(views.layout.views) == 4

    def test_two_views_go_side_by_side_and_four_around_a_centre(self):
        views = _set()
        assert views.show('split').arrangement == 'split'
        assert views.show('quad').arrangement == 'quad'
        assert views.show('plan').arrangement == 'single'

    def test_an_arrangement_of_three_says_what_it_can_place(self):
        with pytest.raises(ValueError) as raised:
            ViewSet(_views(), arrangements={'three': ('plan', 'front', 'left')})
        assert '3' in str(raised.value)

    def test_an_arrangement_naming_a_view_it_has_not_got(self):
        with pytest.raises(ValueError) as raised:
            ViewSet(_views(), arrangements={'odd': ('plan', 'nowhere')})
        assert 'nowhere' in str(raised.value)

    def test_an_arrangement_nobody_has_is_a_usage_error(self):
        views = _set()
        with pytest.raises(ValueError) as raised:
            views.show('hexagonal')
        assert 'hexagonal' in str(raised.value)

    def test_the_views_are_found_by_name(self):
        views = _set()
        assert views.view('front').name == 'front'
        assert views.view('nowhere') is None


class TestPlacingThem:
    def test_a_camera_is_told_the_size_of_its_own_tile(self):
        views = _set(mode='quad')
        plan = views.view('plan')
        assert views.size(plan) == (WINDOW[0] // 2, WINDOW[1] // 2)
        assert plan.camera.viewport == views.size(plan)

    def test_a_view_the_arrangement_hides_is_measured_by_the_window(self):
        views = _set()
        assert views.size(views.view('front')) == WINDOW

    def test_a_window_pixel_reads_in_a_views_own_pixels(self):
        views = _set(mode='quad')
        front = views.view('front')
        left, bottom = front.rect[:2]
        assert views.local(front, left + 9, bottom + 4) == (9.0, 4.0)

    def test_one_view_can_have_the_window_to_itself(self):
        views = _set(mode='quad')
        front = views.view('front')
        views.maximise(front)
        views.arrange(*WINDOW)
        assert views.size(front) == WINDOW
        assert not views.showing(views.view('plan'))
        views.maximise(front)
        views.arrange(*WINDOW)
        assert views.showing(views.view('plan'))

    def test_the_cameras_keep_where_they_were_looking(self):
        views = _set(mode='quad')
        plan = views.view('plan')
        plan.camera.view.pan(30.0, 0.0, views.size(plan))
        centre = plan.camera.view.centre
        views.show('plan')
        assert plan.camera.view.centre == centre


class TestFramingABox:
    def test_the_box_is_on_screen_in_every_view(self):
        views = _set(mode='quad')
        views.frame(LOW, HIGH)
        corners = [(x, y, z) for x in (LOW[0], HIGH[0]) for y in (LOW[1], HIGH[1])
                   for z in (LOW[2], HIGH[2])]
        for view in views.layout.views:
            for corner in corners:
                assert np.all(np.abs(_ndc(view, corner)) <= 1.0 + 1e-5), (view.name, corner)

    def test_a_plan_camera_is_framed_in_its_own_two_axes(self):
        """A ``MapView`` is told where the ground is, not where the box is."""
        views = _set()
        views.frame(LOW, HIGH)
        assert views.view('plan').camera.view.centre == pytest.approx((0.0, 0.0))

    @pytest.mark.parametrize('size', [1e-3, 1e6])
    def test_a_turning_view_frames_a_box_of_any_size(self, size):
        """How near and far it may dolly follows the box, so neither a model
        in millimetres nor a world of a thousand kilometres is clamped away."""
        views = _set(mode='quad')
        low, high = (-size, -size, -size), (size, size, size)
        views.frame(low, high)
        view = views.view('angled')
        for corner in (low, high):
            assert np.all(np.abs(_ndc(view, corner)) <= 1.0 + 1e-5), size

    def test_a_view_that_is_not_on_screen_is_framed_for_the_window(self):
        views = _set()
        views.frame(LOW, HIGH)
        front = views.view('front')
        assert front.camera.view.span > 0.0
        views.show('front')
        for corner in ((LOW[0], LOW[1], 0.0), (HIGH[0], HIGH[1], 0.0)):
            assert np.all(np.abs(_ndc(front, corner)) <= 1.0 + 1e-5)


class TestThePointer:
    def test_a_drag_moves_the_camera_of_the_view_it_is_in(self):
        views = _set(mode='quad')
        front = views.view('front')
        before = np.array(front.camera.view.centre)
        x, y = _centre_of(front)
        assert views.handle(_Event(x, y, button=2))
        assert views.handle(_Event(x + 25, y, kind='mousemove'))
        assert not np.allclose(front.camera.view.centre, before)

    def test_a_view_the_application_drives_is_left_alone(self):
        views = _set(mode='quad', driven=('front', 'left', 'angled'))
        plan = views.view('plan')
        centre = plan.camera.view.centre
        event = _Event(*_centre_of(plan), button=2)
        assert views.view_for(event) is plan
        assert not views.handle(event)
        assert plan.camera.view.centre == centre

    def test_the_view_an_event_belongs_to_follows_the_arrangement(self):
        views = _set(mode='quad')
        under = _centre_of(views.view('angled'))
        assert views.view_for(_Event(*under)) is views.view('angled')
        views.show('plan')
        assert views.view_for(_Event(*under)) is views.view('plan')



class TestSwitchingArrangementMidDrag:
    def test_a_drag_does_not_carry_over_to_another_arrangement(self):
        """The v key during a drag: the hidden view stops panning."""
        plan, front, left, angled = _views()
        views = ViewSet([plan, front, left, angled], mode='quad')
        views.arrange(800, 600)
        x, y, width, height = front.rect
        assert views.gestures.press(front, x + width / 2, y + height / 2, 2)
        views.layout.route(_Event(x + width / 2, y + height / 2, button=2))
        quad = views.layout
        views.show('split')
        assert not views.gestures.dragging
        centre = front.camera.view.centre
        assert not views.gestures.drag(front, x, y)
        assert front.camera.view.centre == centre
        # The arrangement put away holds the pointer for nothing either.
        assert quad.route(_Event(1, 1, kind='mousemove')) is not front
