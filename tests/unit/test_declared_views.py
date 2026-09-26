"""The views a context shows, built from ``navigation.views``.

A context declares its views on its definition -- which cameras, which
gestures, the named arrangements and who may switch them -- and
:class:`~OpenGLContext.multiview.mixin.MultiViewMixin`, one of
:class:`~OpenGLContext.context.Context`'s bases, builds the
:class:`~OpenGLContext.multiview.viewset.ViewSet` from that as the context
completes.  ``startViews()`` makes the same set at run time and writes what it
made back into the definition.
"""
import pytest

from OpenGLContext.context import Context
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.edit.orbitview import OrbitViewPlatform
from OpenGLContext.events.inputstate import InputState
from OpenGLContext.move.navigationdefinition import (
    Arrangement, Navigation, ViewDefinition, Views)
from OpenGLContext.multiview.cameras import OrthoViewPlatform
from OpenGLContext.multiview.mixin import MultiViewMixin, viewSetFor
from OpenGLContext.multiview.quad import FLAT_BACKGROUND
from OpenGLContext.multiview.views import ViewLayout
from OpenGLContext.passes import viewpointbinding
from OpenGLContext.passes.flatcore import FlatPass
from OpenGLContext.scenegraph.basenodes import Viewpoint, sceneGraph
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import scene_context
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.overlay import OverlayMixin
from OpenGLContext.ui.viewchrome import ViewChrome

VIEWPORT = (800, 600)
LOW, HIGH = (-10.0, 0.0, -10.0), (10.0, 6.0, 10.0)


def _quad(**named):
    """The editor's four: plan, two elevations and the window's own camera."""
    return Views(
        views=[ViewDefinition(name='top', camera='top', gestures=['plan']),
               ViewDefinition(name='front', camera='front', gestures=['plan']),
               ViewDefinition(name='left', camera='left', gestures=['plan']),
               ViewDefinition(name='perspective')],
        arrangements=[Arrangement(name='single', views=['perspective']),
                      Arrangement(name='quad',
                                  views=['top', 'front', 'left', 'perspective'])],
        **named)


class TestTheSetADeclarationMakes:
    def test_the_views_are_the_ones_declared_in_order(self):
        views = viewSetFor(_quad())
        assert [view.name for view in views.views] == [
            'top', 'front', 'left', 'perspective']

    def test_the_arrangements_are_the_ones_declared(self):
        views = viewSetFor(_quad())
        assert list(views.arrangements) == ['single', 'quad']
        assert [view.name for view in views.arrangements['quad'].views] == [
            'top', 'front', 'left', 'perspective']

    def test_it_opens_on_the_first_arrangement_unless_one_is_named(self):
        assert viewSetFor(_quad()).mode == 'single'
        assert viewSetFor(_quad(arrangement='quad')).mode == 'quad'

    def test_undeclared_arrangements_are_offered_as_views_alone_and_together(self):
        views = viewSetFor(Views(views=[ViewDefinition(name='top', camera='top'),
                                        ViewDefinition(name='main')]))
        assert list(views.arrangements) == ['top', 'main', 'split']

    def test_a_perspective_view_draws_through_the_windows_own_camera(self):
        """So the movement modes, a bound Viewpoint and a swapped camera drive it."""
        assert viewSetFor(_quad()).named('perspective').camera is None

    def test_an_orthographic_view_looks_along_its_axis(self):
        views = viewSetFor(_quad())
        top = views.named('top').camera
        assert isinstance(top, OrthoViewPlatform)
        assert top.view.direction == 'top'

    def test_an_orthographic_view_is_flat_with_a_grid(self):
        style = viewSetFor(_quad()).named('front').style
        assert style.grid
        assert tuple(style.background) == FLAT_BACKGROUND

    def test_a_perspective_view_draws_the_scenes_background(self):
        style = viewSetFor(_quad()).named('perspective').style
        assert style.background is True
        assert not style.grid

    def test_a_declared_style_outranks_the_cameras(self):
        views = viewSetFor(Views(views=[
            ViewDefinition(name='top', camera='top', style='scene')]))
        assert views.named('top').style.background is True

    def test_the_pointer_moves_the_views_with_cameras_of_their_own(self):
        views = viewSetFor(_quad())
        assert [view.name for view in views.driven] == ['top', 'front', 'left']

    def test_the_declared_gestures_are_what_the_pointer_raises(self):
        views = viewSetFor(_quad())
        assert views.named('top').navigation.mode.name == 'plan'

    def test_several_gesture_sets_are_combined(self):
        views = viewSetFor(Views(views=[ViewDefinition(
            name='top', camera='top', gestures=['plan', 'examine'])]))
        mode = views.named('top').navigation.mode
        commands = {binding.command for binding in mode.bindings}
        assert {'pan', 'rotate'} <= commands

    def test_a_perspective_view_with_gestures_has_its_own_orbiting_camera(self):
        """The gestures move a camera, and the window's own belongs to the
        movement modes."""
        views = viewSetFor(Views(views=[
            ViewDefinition(name='model', camera='perspective', gestures=['examine'])]))
        model = views.named('model')
        assert isinstance(model.camera, OrbitViewPlatform)
        assert model in views.driven

    def test_a_scene_view_has_its_own_camera_for_the_scenes_to_stand_it_at(self):
        views = viewSetFor(Views(views=[ViewDefinition(name='cam', camera='scene')]))
        assert views.named('cam').camera is not None
        assert views.named('cam') in views.driven


class _World:
    """The rest of a context: what the mix-ins reach for, and nothing else."""

    def __init__(self, navigation):
        self.contextDefinition = ContextDefinition(navigation=navigation)
        self.bound = []
        self.states = []
        self.redraws = 0
        self.viewport = VIEWPORT
        self.inputState = InputState()
        self.platform = object()
        self.graph = None

    def getViewPort(self):
        return self.viewport

    def getViewLayout(self):
        return ViewLayout.single()

    def getViewPlatform(self):
        return self.platform

    def getSceneGraph(self):
        return self.graph

    def triggerRedraw(self, force=0):  # noqa: ARG002 the signature of Context.triggerRedraw
        self.redraws += 1

    def hasMouseMoveHandlers(self):
        return False

    def setPointerShape(self, name):  # noqa: ARG002 the signature of Context.setPointerShape
        return True

    def suspendPointerCapture(self, suspend):
        pass

    def getInputState(self):
        return self.inputState

    def screenTrees(self, _metrics, now=None):  # noqa: ARG002 the signature of OverlayMixin.screenTrees
        return []

    def overlayMetrics(self):
        return FontMetrics(8, 16, 2)

    def ViewPort(self, width, height):
        self.viewport = (width, height)

    def ProcessEvent(self, event):
        return event

    def addEventHandler(self, eventType, *arguments, **named):  # noqa: ARG002 the signature of EventHandlerMixin.addEventHandler
        self.bound.append((eventType, named.get('name'), named.get('function')))
        self.states.append(named.get('state'))

    def setupDefaultEventCallbacks(self):
        pass

    def completeInit(self):
        return True


class _Bare(MultiViewMixin, _World):
    """The mix-in with no overlay stack."""


class _Overlaid(OverlayMixin, MultiViewMixin, _World):
    """The mix-in under an overlay stack, the order a context uses them in."""


def _completed(cls, views):
    window = cls(Navigation(views=views))
    window.setupDefaultEventCallbacks()
    window.completeInit()
    return window


def _keysBound(window, name):
    return [function for kind, key, function in window.bound
            if kind == 'keyboard' and key == name]


class TestAContextBuildsItsDeclaredViews:
    def test_it_is_one_of_contexts_bases(self):
        assert issubclass(Context, MultiViewMixin)

    def test_no_declared_views_builds_nothing(self):
        window = _completed(_Bare, None)
        assert window.views is None
        assert window.getViewLayout().arrangement == 'single'

    def test_a_null_navigation_builds_nothing(self):
        window = _Bare(None)
        window.setupDefaultEventCallbacks()
        window.completeInit()
        assert window.views is None

    def test_declared_views_are_built_as_it_completes(self):
        window = _completed(_Bare, _quad(arrangement='quad'))
        assert window.views.mode == 'quad'
        assert window.getViewLayout() is window.views.layout

    def test_they_are_placed_in_the_window(self):
        window = _completed(_Bare, _quad(arrangement='quad'))
        assert window.views.window == VIEWPORT

    def test_they_are_framed_on_the_scene(self):
        window = _Bare(Navigation(views=_quad(arrangement='quad')))
        window.sceneBounds = lambda: ((0.0, 3.0, 0.0), 10.0)
        window.completeInit()
        assert window.views.named('top').camera.view.span != 10.0

    def test_a_scene_view_looks_through_the_scenes_first_camera(self):
        window = _Bare(Navigation(views=Views(views=[
            ViewDefinition(name='cam', camera='scene')])))
        window.graph = sceneGraph(children=[Viewpoint(
            description='Porch', position=(1.0, 2.0, 30.0))])
        viewpointbinding.publish_viewpoints(window, FlatPass(window.graph, []))
        window.completeInit()
        orbit = window.views.named('cam').camera.view
        assert orbit.position() == pytest.approx((1.0, 2.0, 30.0), abs=1e-4)


class TestSwitchingArrangements:
    def test_no_switching_binds_no_keys(self):
        window = _completed(_Bare, _quad())
        assert not _keysBound(window, window.viewsCycleKey)
        assert not _keysBound(window, window.viewMaximiseKey)

    def test_keys_bind_the_arrangement_and_maximise_keys(self):
        window = _completed(_Bare, _quad(switching=['keys']))
        assert _keysBound(window, window.viewsCycleKey)[-1] == window.toggleViews
        assert _keysBound(window, window.viewMaximiseKey)[-1] == window.maximiseView

    def test_they_fire_on_the_release(self):
        """A held key repeats; stepping through arrangements at that rate would
        leave the user wherever the repeat happened to stop."""
        window = _completed(_Bare, _quad(switching=['keys']))
        assert window.states == [0, 0]

    def test_the_arrangement_key_takes_the_declared_ones_in_turn(self):
        window = _completed(_Bare, Views(
            views=[ViewDefinition(name='top', camera='top'),
                   ViewDefinition(name='front', camera='front'),
                   ViewDefinition(name='left', camera='left'),
                   ViewDefinition(name='main')],
            arrangements=[Arrangement(name='one', views=['main']),
                          Arrangement(name='two', views=['top', 'main']),
                          Arrangement(name='four',
                                      views=['top', 'front', 'left', 'main'])]))
        seen = []
        for _step in range(3):
            window.toggleViews()
            seen.append(window.views.mode)
        assert seen == ['two', 'four', 'one']

    def test_the_application_can_show_any_arrangement_whatever_switching_says(self):
        window = _completed(_Bare, _quad())
        window.showViews('quad')
        assert window.views.mode == 'quad'

    def test_controls_put_the_views_furniture_up(self):
        window = _completed(_Overlaid, _quad(switching=['controls']))
        assert isinstance(window.viewChrome, ViewChrome)
        assert window.viewChrome in window.overlays.panels

    def test_no_controls_puts_none_up(self):
        window = _completed(_Overlaid, _quad())
        assert window.viewChrome is None

    def test_controls_need_the_overlay(self):
        """Raised as the context is built, naming what to mix in."""
        window = _Bare(Navigation(views=_quad(switching=['controls'])))
        with pytest.raises(TypeError, match='OverlayMixin'):
            window.setupDefaultEventCallbacks()


class TestStartingViewsAtRunTime:
    def test_it_writes_what_it_made_into_the_definition(self):
        window = _Overlaid(Navigation(modes=['examine']))
        window.startViews(bounds=(LOW, HIGH), arrangement='quad')
        declared = window.contextDefinition.navigation.views
        assert [view.name for view in declared.views] == [
            'top', 'front', 'left', 'perspective']
        assert declared.arrangement == 'quad'
        assert declared.switching == ['controls']

    def test_what_it_wrote_builds_the_same_set(self):
        window = _Overlaid(Navigation(modes=['examine']))
        started = window.startViews(bounds=(LOW, HIGH), arrangement='quad')
        rebuilt = viewSetFor(window.contextDefinition.navigation.views)
        assert list(rebuilt.arrangements) == list(started.arrangements)
        assert [view.name for view in rebuilt.driven] == [
            view.name for view in started.driven]
        assert rebuilt.mode == started.mode

    def test_it_keeps_the_modes_declared_beside_it(self):
        window = _Overlaid(Navigation(modes=['examine', 'fly']))
        window.startViews(bounds=(LOW, HIGH))
        assert [mode.name for mode in window.contextDefinition.navigation.modes] == [
            'examine', 'fly']

    def test_without_chrome_it_declares_no_controls(self):
        window = _Overlaid(Navigation(modes=['examine']))
        window.startViews(bounds=(LOW, HIGH), chrome=False)
        assert window.contextDefinition.navigation.views.switching == []


class TestAWindowedContext:
    def test_a_context_opens_on_its_declared_views(self):
        refused = profile_unavailable('core')
        if refused:
            pytest.skip(refused)
        views = _quad(arrangement='quad')
        with scene_context([], navigation=Navigation(
                modes=['examine'], views=views)) as context:
            mode = context.views.mode
            width, height = context.getViewPort()
            placed = context.views.window
        assert mode == 'quad'
        assert placed == (width, height)
