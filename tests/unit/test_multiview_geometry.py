"""One submission of the scene for every view, held to the view-at-a-time picture.

The ``geometry`` and ``vertex`` strategies draw each opaque shape once and send
it to every view that can see it -- through a geometry stage, or by instancing
the draw across the views and routing each copy from the vertex stage. They
must draw what ``sequential`` draws: these render one four-view scene each way
and compare the frames, and count the draws each needed.
"""
import numpy as np
import pytest

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes  # noqa: E402
from OpenGLContext.multiview.views import View, ViewLayout  # noqa: E402
from tests.unit.glrender import base_env, frames_of  # noqa: E402

WIDTH, HEIGHT = 240, 160


def _shape(geometry, colour, at, transparency=0.0):
    return basenodes.Transform(translation=at, children=[
        basenodes.Shape(
            geometry=geometry,
            appearance=basenodes.Appearance(material=basenodes.Material(
                diffuseColor=colour, transparency=transparency)))])


def _scene():
    return [
        basenodes.Background(skyColor=[(0.2, 0.3, 0.5)]),
        _shape(basenodes.Box(size=(10, 0.2, 10)), (0.8, 0.8, 0.8), (0, -1.1, 0)),
        _shape(basenodes.Box(size=(1, 1, 1)), (1, 0, 0), (-2, 0, 0)),
        _shape(basenodes.Sphere(radius=0.7), (0, 1, 0), (0, 0, 0)),
        _shape(basenodes.Cone(bottomRadius=0.6, height=1.4), (0, 0, 1), (2, 0, 0)),
        _shape(basenodes.Box(size=(1, 1, 1)), (1, 1, 0), (0, 0, 2), transparency=0.5),
        basenodes.DirectionalLight(direction=(-0.3, -1.0, -0.4), intensity=1.0),
    ]


def _looking(eye):
    from OpenGLContext.move.followcam import look_at_orientation
    from OpenGLContext.move.viewplatform import ViewPlatform
    return ViewPlatform(position=eye, orientation=look_at_orientation(eye, (0, 0, 0)))


def _layout(strategy):
    def build(context):
        context.contextDefinition.multiview = strategy
        return ViewLayout.quad(
            View(_looking((0.0, 6.0, 8.0)), name='front'),
            View(_looking((8.0, 5.0, 0.5)), name='side'),
            View(_looking((0.5, 12.0, 0.1)), name='top'),
            View(_looking((-6.0, 3.0, -6.0)), name='behind'),
        )
    return build


@pytest.fixture(params=['pbr', 'vrml97'])
def env(request, monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='1', OPENGLCONTEXT_SHADOW_CASCADES='2',
             OPENGLCONTEXT_INSTANCE_MIN='999')
    if request.param == 'vrml97':
        monkeypatch.delenv('OPENGLCONTEXT_RENDERER')
    return request.param


@pytest.fixture(params=['geometry', 'vertex'])
def shared(request, gl_context):
    """A strategy that draws once for every view, where this driver runs it."""
    from OpenGLContext.multiview import strategy as multiview
    multiview.reset_detected()
    if request.param not in multiview.MultiviewCapabilities.detect().available():
        pytest.skip('this driver cannot run the %s strategy' % request.param)
    multiview.reset_detected()
    return request.param


def _render(render_scene, strategy):
    from OpenGLContext.passes import renderpass
    draws = []
    frames = frames_of(render_scene, _scene(), frames=3, shadows=True,
                       size=(WIDTH, HEIGHT), layout=_layout(strategy))
    draws.append(renderpass.FLAT.stats.draws)
    return frames[-1], renderpass.FLAT, draws[-1]


def test_the_strategy_asked_for_is_the_one_drawn_with(render_scene, env, shared):
    _frame, flat, _draws = _render(render_scene, shared)
    assert flat.multiviewStrategy == shared


def test_one_submission_draws_what_views_in_turn_draw(render_scene, env,
                                                      shared):
    once, _flat, _ = _render(render_scene, shared)
    sequential, _flat, _ = _render(render_scene, 'sequential')
    differing = (abs(once.astype(int) - sequential.astype(int)).max(axis=-1) > 24)
    assert differing.mean() < 0.005, differing.sum()
    # Every view has something in it.
    for rows in (slice(0, HEIGHT // 2), slice(HEIGHT // 2, HEIGHT)):
        for columns in (slice(0, WIDTH // 2), slice(WIDTH // 2, WIDTH)):
            assert len(np.unique(once[rows, columns].reshape(-1, 3), axis=0)) > 20


def test_a_shape_seen_by_every_view_is_drawn_once(render_scene, env, shared):
    _frame, _flat, once = _render(render_scene, shared)
    _frame, _flat, sequential = _render(render_scene, 'sequential')
    assert once < sequential
    # Four opaque shapes drawn once each; the transparent box once per view.
    assert once <= 4 + 4


def test_the_single_view_programs_are_back_after_the_frame(render_scene, env,
                                                           shared):
    _frame, flat, _ = _render(render_scene, shared)
    assert flat.shader_program.program_set == 0


def test_a_click_in_a_shared_view_picks_through_that_view(render_scene, env,
                                                          shared):
    from OpenGLContext.events.mouseevents import MouseButtonEvent
    rendered = render_scene(_scene(), frames=2, picks=[], shadows=True,
                            size=(WIDTH, HEIGHT), layout=_layout(shared))
    context = rendered.context
    # The middle of the top view looks straight down on the sphere.
    at = (WIDTH // 4, HEIGHT // 4)
    for _warm in range(2):
        press = MouseButtonEvent()
        press.button, press.state, press.modifiers = 0, 1, (0, 0, 0)
        press.pickPoint = at
        context.addPickEvent(press)
        context.triggerPick()
        context.OnDraw(force=1)
        release = MouseButtonEvent()
        release.button, release.state, release.modifiers = 0, 0, (0, 0, 0)
        release.pickPoint = at
        context.routeEvent(release)
    assert press.view.name == 'top'
    paths = press.getObjectPaths()
    assert paths and paths[0]
    assert isinstance(paths[0][-1].geometry, basenodes.Sphere)


def test_an_instanced_crowd_is_drawn_once_for_every_view(render_scene, env,
                                                         shared, monkeypatch):
    """Copies collapsed into one instanced draw share that draw across views too."""
    monkeypatch.setenv('OPENGLCONTEXT_INSTANCE_MIN', '2')
    # One geometry and one appearance, which is what both passes group by.
    sphere = basenodes.Sphere(radius=0.3)
    look = basenodes.Appearance(material=basenodes.Material(diffuseColor=(0.9, 0.5, 0.1)))
    crowd = [basenodes.Transform(translation=(x, 0.8, z), children=[
                 basenodes.Shape(geometry=sphere, appearance=look)])
             for x in (-1.5, -0.5, 0.5, 1.5) for z in (-1.0, 1.0)]

    def render(strategy):
        from OpenGLContext.passes import renderpass
        frames = frames_of(render_scene, _scene() + crowd, frames=3, shadows=True,
                           size=(WIDTH, HEIGHT), layout=_layout(strategy))
        return frames[-1], renderpass.FLAT.stats

    once, stats = render(shared)
    assert stats.instanceGroups >= 1
    sequential, _stats = render('sequential')
    differing = (abs(once.astype(int) - sequential.astype(int)).max(axis=-1) > 24)
    assert differing.mean() < 0.005, differing.sum()


def test_programs_that_will_not_compile_leave_the_views_drawn_in_turn(
        render_scene, env, shared, monkeypatch):
    """A driver that offers a strategy and then fails to build it still draws."""
    from OpenGLContext.passes.pbrpass import PBRShaderProgram
    from OpenGLContext.passes.shaderpass import VRML97ShaderProgram
    attempts = []

    def refuse(self, views, strategy='geometry'):
        attempts.append(strategy)
        return {name: None for name in self.MULTIVIEW_PROGRAMS}

    monkeypatch.setattr(VRML97ShaderProgram, '_compile_program_set', refuse)
    monkeypatch.setattr(PBRShaderProgram, '_compile_program_set', refuse)
    from OpenGLContext.passes import renderpass
    frames = frames_of(render_scene, _scene(), frames=5, shadows=True,
                       size=(WIDTH, HEIGHT), layout=_layout(shared))
    assert renderpass.FLAT.multiviewStrategy == 'sequential'
    # Each strategy is tried once, never again for every frame after.
    assert sorted(attempts) == sorted(set(attempts))
    assert shared in attempts
    sequential, _flat, _ = _render(render_scene, 'sequential')
    for frame in frames:
        differing = (abs(frame.astype(int) - sequential.astype(int)).max(axis=-1) > 24)
        assert differing.mean() < 0.005, differing.sum()


def test_more_views_than_the_driver_has_viewports_are_drawn_in_turn(
        render_scene, env, shared, monkeypatch):
    from OpenGLContext.multiview.strategy import MultiviewCapabilities
    monkeypatch.setattr(MultiviewCapabilities, 'max_views', property(lambda self: 2))
    _frame, _flat, draws = _render(render_scene, shared)
    _frame, _flat, sequential = _render(render_scene, 'sequential')
    assert draws == sequential


def test_a_wireframe_view_beside_shared_ones_draws_its_own_lines(render_scene, env, shared):
    """Polygon mode holds for every viewport, so a wireframe view is drawn apart."""
    from OpenGLContext.multiview.views import ViewStyle

    def build(context):
        layout = _layout(shared)(context)
        layout.views[1].style = ViewStyle(wireframe=True)
        return layout

    frames = frames_of(render_scene, _scene(), frames=3, shadows=True,
                       size=(WIDTH, HEIGHT), layout=build)
    frame = frames[-1]
    sky = np.array([0.2 * 255, 0.3 * 255, 0.5 * 255])
    drawn = lambda tile: (abs(tile.astype(int) - sky).max(axis=-1) > 30).mean()  # noqa: E731
    front = drawn(frame[:HEIGHT // 2, :WIDTH // 2])
    side = drawn(frame[:HEIGHT // 2, WIDTH // 2:])
    assert side > 0
    assert side < front / 2, (side, front)
