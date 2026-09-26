"""Four views in any window that wants them.

What the mix-in gives a context: the arrangements, the views' furniture, and
the window's own camera left driving the perspective one. Headless -- a
stand-in context with no window at all, as the overlay's own cases use.
"""
import numpy as np
from OpenGLContext.events.inputstate import InputState
from OpenGLContext.multiview.mixin import MultiViewMixin
from OpenGLContext.multiview.views import ViewLayout
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.overlay import OverlayStackMixin
from OpenGLContext.passes import viewpointbinding
from OpenGLContext.passes.flatcore import FlatPass
from OpenGLContext.scenegraph.basenodes import sceneGraph, Viewpoint

VIEWPORT = (800, 600)
LOW, HIGH = (-10.0, 0.0, -10.0), (10.0, 6.0, 10.0)


class _Event:
    view = None

    def __init__(self, x, y, button=2, state=1, kind='mousebutton'):
        self.type, self.button, self.state = kind, button, state
        self._point = (x, y)

    def getPickPoint(self):
        return self._point

    def getModifiers(self):
        return (0, 0, 0)


class _World:
    """The rest of a context: what the mix-ins reach for, and nothing else."""

    def __init__(self):
        self.redraws = 0
        self.dispatched = []
        self.viewport = VIEWPORT
        self.cursors = []
        self.captureSuspended = None
        self.inputState = InputState()
        self.platform = object()

    def getViewPort(self):
        return self.viewport

    def getViewLayout(self):
        return ViewLayout.single()

    def getViewPlatform(self):
        return self.platform

    def triggerRedraw(self, force=0):  # noqa: ARG002 the signature of Context.triggerRedraw
        self.redraws += 1

    def hasMouseMoveHandlers(self):
        return False

    def setPointerShape(self, name):
        self.cursors.append(name)
        return True

    def suspendPointerCapture(self, suspend):
        self.captureSuspended = suspend

    def getInputState(self):
        return self.inputState

    def screenTrees(self, _metrics, now=None):  # noqa: ARG002 the signature of OverlayStackMixin.screenTrees
        return []

    def overlayMetrics(self):
        return FontMetrics(8, 16, 2)

    def ViewPort(self, width, height):
        self.viewport = (width, height)

    def ProcessEvent(self, event):
        self.dispatched.append(event)
        return event


class _Window(OverlayStackMixin, MultiViewMixin, _World):
    """The two mix-ins over a stand-in world, in the order they are used in."""


def _window(**named):
    window = _Window()
    window.startViews(bounds=(LOW, HIGH), **named)
    return window


class TestWhatItGivesAWindow:
    def test_it_opens_on_the_windows_own_view(self):
        window = _window()
        assert window.views.mode == 'single'
        assert [view.name for view in window.views.layout.views] == ['perspective']

    def test_and_can_open_on_the_four(self):
        window = _window(arrangement='quad')
        assert [view.name for view in window.views.layout.views] \
            == ['top', 'front', 'left', 'perspective']

    def test_the_layout_is_what_the_frame_draws(self):
        window = _window()
        assert window.getViewLayout() is window.views.layout

    def test_a_window_that_never_started_them_draws_its_own(self):
        window = _Window()
        assert window.getViewLayout().arrangement == 'single'

    def test_the_perspective_view_draws_through_the_windows_own_camera(self):
        """So the navigation, a bound Viewpoint and a swapped camera all still
        drive it."""
        window = _window(arrangement='quad')
        assert window.views.named('perspective').camera is None

    def test_the_elevations_are_the_mixins_own(self):
        window = _window(arrangement='quad')
        for name in ('top', 'front', 'left'):
            assert window.views.named(name).camera is not None

    def test_the_elevations_can_be_chosen(self):
        window = _window(arrangement='quad', elevations=('bottom', 'back', 'right'))
        assert [view.name for view in window.views.layout.views] \
            == ['bottom', 'back', 'right', 'perspective']


class TestSwitchingBetweenThem:
    def test_the_key_takes_them_in_turn(self):
        window = _window()
        window.toggleViews()
        assert window.views.mode == 'quad'
        window.toggleViews()
        assert window.views.mode == 'single'

    def test_the_furniture_follows_the_arrangement(self):
        window = _window()
        window.showViews('quad')
        assert window.viewChrome.layout_of is window.views.layout

    def test_one_view_can_be_given_the_window(self):
        window = _window(arrangement='quad')
        window.views.layout.activate(window.views.named('front'))
        window.maximiseView()
        assert window.views.layout.maximised is window.views.named('front')

    def test_the_window_is_drawn_again_when_it_changes(self):
        window = _window()
        drawn = window.redraws
        window.showViews('quad')
        assert window.redraws > drawn


class TestWhatTheViewsAreFittedTo:
    def test_what_there_is_to_see_is_in_every_view(self):
        window = _window(arrangement='quad')
        corners = [(x, y, z) for x in (LOW[0], HIGH[0]) for y in (LOW[1], HIGH[1])
                   for z in (LOW[2], HIGH[2])]
        for view in window.views.layout.views:
            if view.camera is None:
                continue
            for corner in corners:
                clip = np.append(np.asarray(corner, 'd'), 1.0) @ view.camera.matrix()
                assert np.all(np.abs(clip[:3] / clip[3]) <= 1.0 + 1e-5), view.name

    def test_bounds_may_be_asked_for_rather_than_given(self):
        asked = []

        def bounds():
            asked.append(1)
            return (LOW, HIGH)

        window = _Window()
        window.startViews(bounds=bounds, arrangement='quad')
        assert asked

    def test_a_window_that_says_nothing_frames_nothing(self):
        window = _Window()
        window.startViews()
        assert not window.frameViews()


class TestThePointer:
    def test_a_drag_in_an_elevation_moves_that_view(self):
        window = _window(arrangement='quad')
        front = window.views.named('front')
        before = np.array(front.camera.view.centre)
        x, y, width, height = front.rect
        middle = (x + width // 2, y + height // 2)
        assert window.ProcessEvent(_Event(*middle)) is None
        assert window.ProcessEvent(_Event(middle[0] + 30, middle[1],
                                          kind='mousemove')) is None
        assert not np.allclose(front.camera.view.centre, before)

    def test_what_the_views_leave_reaches_the_window(self):
        window = _window(arrangement='quad')
        perspective = window.views.named('perspective')
        x, y, width, height = perspective.rect
        event = _Event(x + width // 2, y + height // 2)
        window.ProcessEvent(event)
        assert window.dispatched[-1] is event

    def test_the_pointers_movements_are_asked_for_during_a_drag(self):
        """The mix-in's own answer; the overlay beside it answers for hovering."""
        window = _window(arrangement='quad')

        def asks():
            return MultiViewMixin.hasMouseMoveHandlers(window)

        assert not asks()
        front = window.views.named('front')
        x, y, width, height = front.rect
        window.ProcessEvent(_Event(x + width // 2, y + height // 2))
        assert asks()
        window.ProcessEvent(_Event(x + width // 2, y + height // 2, state=0))
        assert not asks()

    def test_a_resize_tells_each_view_its_own_size(self):
        window = _window(arrangement='quad')
        window.ViewPort(1000, 800)
        assert window.views.named('front').size == (500, 400)


class TestWithoutAnOverlay:
    def test_the_furniture_is_left_out_where_it_is_not_wanted(self):
        window = _window(chrome=False)
        assert window.viewChrome is None

    def test_and_the_views_still_work(self):
        window = _window(chrome=False, arrangement='quad')
        window.toggleViews()
        assert window.views.mode == 'single'


class TestTheScenesCameras:
    """The cameras the window's scene carries reach every view's menu."""

    def test_the_views_menu_is_offered_the_scenes_cameras(self):
        window = _window(arrangement='quad')
        graph = sceneGraph(children=[Viewpoint(description='Porch')])
        window.getSceneGraph = lambda: graph
        viewpointbinding.publish_viewpoints(window, FlatPass(graph, []))
        assert [camera.name for camera in window.viewChrome.scene_cameras()] == ['Porch']

    def test_a_window_with_no_scene_offers_none(self):
        window = _window(arrangement='quad')
        assert window.viewChrome.scene_cameras() == []


class TestLosingFocusMidDrag:
    def test_the_drag_ends_and_the_pointer_is_free(self):
        """No release arrives for a button held as the window lost focus."""
        window = _window(arrangement='quad')
        window.emitKey = lambda *_args: None
        front = window.views.named('front')
        x, y, width, height = front.rect
        window.ProcessEvent(_Event(x + width // 2, y + height // 2))
        assert window.views.gestures.dragging
        window.clearHeldKeys()
        assert not window.views.gestures.dragging
        top = window.views.named('top')
        tx, ty, _w, _h = top.rect
        assert window.views.layout.route(_Event(tx + 1, ty + 1, kind='mousemove')) is top


class TestTheGrid:
    def test_the_orthographic_views_are_ruled(self):
        window = _window(arrangement='quad')
        for name in ('top', 'front', 'left'):
            assert window.views.named(name).style.grid, name

    def test_the_windows_own_view_is_not(self):
        assert not _window().views.named('perspective').style.grid
