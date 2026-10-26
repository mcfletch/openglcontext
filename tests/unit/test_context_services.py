"""A context hosts physics and audio: made on first use, framed with the render queue, closed with the window."""
import threading
from types import SimpleNamespace

import pytest

from OpenGLContext import context as context_module
from OpenGLContext.audio.manager import Audio
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.events import systemtime
from OpenGLContext.events.renderqueue import RenderQueue
from OpenGLContext.physics import callbacks
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))


class _Context(context_module.Context):
    """A context with the window taken out: the parts the services use."""

    telemetry = None

    def __init__(self, physics=None, **definition):
        self.redrawRequest = threading.Event()
        self.renderQueue = RenderQueue(wake=self.redrawRequest.set)
        self.contextDefinition = ContextDefinition(
            physics=physics if physics is not None else PhysicsDefinition(mode='inline'),
            **definition)
        self._captureClock = None
        self.redraws = []
        self.windowsystem = SimpleNamespace(release=lambda: None)
        self.sceneLoader = None
        self.initializeEventManagers()

    def triggerRedraw(self, force=0):
        self.redraws.append(force)


class _Clock:
    """A time source the test advances."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    source = _Clock()
    previous = systemtime.setTimeSource(source)
    yield source
    systemtime.setTimeSource(previous)


@pytest.fixture
def ctx():
    made = _Context()
    yield made
    if '_physics' in made.__dict__ or '_audio' in made.__dict__:
        made.releaseWindow()


def ball(at=(0, 5, 0)):
    return surfaces.shape(surfaces.sphere(0.5), LOOK, translation=at)


def test_physics_is_made_on_first_use_and_is_the_same_each_time(ctx):
    assert isinstance(ctx.physics, Physics)
    assert ctx.physics is ctx.physics


def test_a_context_that_never_mentions_physics_makes_none(ctx):
    assert '_physics' not in ctx.__dict__


def test_physics_takes_its_definition_from_the_contexts(ctx):
    assert ctx.physics.definition is ctx.contextDefinition.physics


def test_the_render_queue_steps_the_world_each_frame(ctx, clock):
    node = ball()
    ctx.physics.add_dynamic(node)
    ctx.renderQueue.run()
    for _ in range(10):
        clock.now += 0.02
        ctx.renderQueue.run()
    assert node.translation[1] < 5.0


def test_a_frame_with_something_moving_asks_for_a_redraw(ctx, clock):
    ctx.physics.add_dynamic(ball())
    ctx.renderQueue.run()
    clock.now += 0.02
    ctx.renderQueue.run()
    assert ctx.redraws and ctx.redraws[-1] == 1


def test_a_frame_with_nothing_moving_asks_for_none(ctx, clock):
    ctx.physics.add_static(surfaces.shape(surfaces.block((1, 1, 1)), LOOK))
    ctx.renderQueue.run()
    clock.now += 0.02
    ctx.renderQueue.run()
    assert ctx.redraws == []


def test_a_stall_does_not_hand_the_world_one_huge_step(ctx, clock):
    node = ball(at=(0, 100, 0))
    ctx.physics.add_dynamic(node)
    ctx.renderQueue.run()
    clock.now += 30.0
    ctx.renderQueue.run()
    assert node.translation[1] > 99.0


def test_a_capture_runs_the_world_inline_whatever_the_definition_says():
    made = _Context(physics=PhysicsDefinition(mode='thread'))
    made._captureClock = object()
    try:
        assert made.physics.definition.mode == 'inline'
        assert made.contextDefinition.physics.mode == 'thread'
    finally:
        made.releaseWindow()


def test_physics_off_in_the_definition_leaves_bodies_where_they_were_put(clock):
    made = _Context(physics=PhysicsDefinition(enabled=False, mode='inline'))
    node = ball()
    made.physics.add_dynamic(node)
    made.renderQueue.run()
    clock.now += 0.5
    made.renderQueue.run()
    assert node.translation[1] == pytest.approx(5.0)
    assert made.redraws == []
    made.releaseWindow()


def test_releasing_the_window_stops_the_worker(clock):
    made = _Context(physics=PhysicsDefinition(mode='thread'))
    made.physics.add_dynamic(ball())
    assert made.physics.worker.thread_id is not None
    made.releaseWindow()
    assert made.physics.worker.thread_id is None


def test_physics_callback_is_on_the_context_class():
    assert context_module.Context.physics_callback is callbacks.physics_callback

    class Game(context_module.Context):
        @context_module.Context.physics_callback
        def OnHit(self, hit):
            return None

    assert callbacks.is_physics_callback(Game.OnHit)


def test_audio_is_made_on_first_use_and_is_the_same_each_time(ctx):
    assert isinstance(ctx.audio, Audio)
    assert ctx.audio is ctx.audio


def test_audio_is_framed_by_the_render_queue_once_a_frame(ctx, monkeypatch):
    frames = []
    audio = ctx.audio
    monkeypatch.setattr(audio, 'frame', lambda: frames.append(1) or 0)
    ctx.renderQueue.run()
    ctx.renderQueue.run()
    assert frames == [1, 1]


def test_releasing_the_window_closes_audio(ctx, monkeypatch):
    closed = []
    audio = ctx.audio
    monkeypatch.setattr(audio, 'close', lambda: closed.append(1))
    ctx.releaseWindow()
    assert closed == [1]


def test_the_services_cost_a_context_that_does_not_use_them_nothing(ctx):
    ctx.renderQueue.run()
    ctx.releaseWindow()
    assert '_physics' not in ctx.__dict__ and '_audio' not in ctx.__dict__


class _Listener:
    def __init__(self):
        self.heard = []

    def OnHit(self, hit):
        self.heard.append(hit)


def _land(made, clock, **options):
    made.physics.add_static(surfaces.shape(surfaces.block((20, 1, 20)), LOOK, translation=(0, -0.5, 0)))
    body = made.physics.add_dynamic(ball(at=(0, 1.5, 0)), restitution=0.0)
    return body


def test_physics_events_are_added_to_a_context_by_their_physics_names(ctx, clock):
    listener = _Listener()
    body = _land(ctx, clock)
    ctx.addEventHandler('physics-hit', body=body, function=listener.OnHit)
    ctx.renderQueue.run()
    for _ in range(40):
        clock.now += 0.02
        ctx.renderQueue.run()
    assert len(listener.heard) == 1 and listener.heard[0].body is body


def test_the_context_spelling_without_a_body_hears_every_body(ctx, clock):
    listener = _Listener()
    _land(ctx, clock)
    ctx.addEventHandler('physics-hit', function=listener.OnHit)
    ctx.renderQueue.run()
    for _ in range(40):
        clock.now += 0.02
        ctx.renderQueue.run()
    assert len(listener.heard) == 1


def test_every_physics_event_name_has_a_manager(ctx):
    for name in ('hit', 'touching', 'separate', 'enter', 'stay', 'exit', 'sleep', 'wake'):
        assert ctx.getEventManager('physics-' + name) is not None


def test_a_recorded_session_runs_the_world_inline_and_writes_its_events_to_the_journal(clock):
    marks = []
    made = _Context(physics=PhysicsDefinition(mode='thread', maxCatchUp=2.0))
    made.telemetry = SimpleNamespace(mark=lambda name, /, **fields: marks.append((name, fields)))
    try:
        listener = _Listener()
        body = _land(made, clock)
        body.addEventHandler('hit', function=listener.OnHit)
        assert made.physics.definition.mode == 'inline'
        made.renderQueue.run()
        for _ in range(40):
            clock.now += 0.02
            made.renderQueue.run()
        assert [name for name, _fields in marks] == ['physics-hit']
    finally:
        made.releaseWindow()


def test_a_frame_that_raises_is_logged_once_and_the_loop_goes_on(ctx, clock, caplog):
    def broken(dt):
        raise ValueError('the world fell over')

    ctx.physics.frame = broken
    clock.now += 0.02
    ctx.renderQueue.run()
    clock.now += 0.02
    ctx.renderQueue.run()
    assert sum(1 for record in caplog.records
               if record.exc_info and 'the world fell over' in str(record.exc_info[1])) == 1
