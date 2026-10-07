"""X3D's event utilities and KeySensor in the engine.

The behaviours are pyvrml97's (``vrml.x3d.runtime``); the engine registers
them, stamps ``TimeTrigger`` with its own clock, and tells a ``KeySensor`` of
every key its context receives.
"""
import pytest
from vrml.x3d import runtime

from OpenGLContext.events import keyboardevents, systemtime
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph import x3druntime


@pytest.mark.parametrize('name', ['BooleanFilter', 'BooleanToggle', 'BooleanTrigger',
                                  'IntegerTrigger', 'TimeTrigger', 'BooleanSequencer',
                                  'IntegerSequencer', 'KeySensor', 'StringSensor'])
def test_each_is_the_engines(name):
    assert issubclass(prototypes()[name], runtime.PROTOTYPES[name])


def test_a_time_trigger_sends_the_engines_time(monkeypatch):
    monkeypatch.setattr(systemtime, 'systemTime', lambda: 99.5)
    made = x3druntime.TimeTrigger()
    made.set_boolean = True
    assert made.triggerTime == 99.5


def test_an_engine_scenes_clock_is_the_engines(monkeypatch):
    """A node pyvrml97 times, rooted in an engine scene, is on the engine's clock"""
    from OpenGLContext.scenegraph.scenegraph import SceneGraph, X3DScene  # noqa: PLC0415 kept with its use
    monkeypatch.setattr(systemtime, 'systemTime', lambda: 12.25)
    for kind in (SceneGraph, X3DScene):
        made = runtime.TimeTrigger()
        scene = kind(children=[made])
        assert scene.clock() == 12.25
        assert made.now() == 12.25


def test_a_follower_set_and_stepped_under_a_fixed_step_clock_arrives():
    """The destination is stamped on the clock the steps are taken on"""
    from OpenGLContext.video.clock import FixedStepClock  # noqa: PLC0415 kept with its use
    with FixedStepClock(4, start=0.0) as clock:
        chaser = x3druntime.ScalarChaser(duration=1.0)
        context = QueueContext()
        chaser.bind(context)
        chaser.set_destination = 4.0
        for _ in range(3):
            clock.advance()
            context.renderQueue.run()
        assert 0.0 < chaser.value_changed < 4.0
        for _ in range(2):
            clock.advance()
            context.renderQueue.run()
        assert chaser.value_changed == pytest.approx(4.0)


@pytest.mark.parametrize('engine, x3d', [
    ('a', 'a'), ('<up>', 'UP'), ('<F4>', 'F4'), ('<pageup>', 'PGUP'), ('<pagedown>', 'PGDN'),
    ('<shift>', 'SHIFT'), ('<ctrl>', 'CONTROL'), ('<alt>', 'ALT'), ('<return>', '\n'),
    ('<numlock>', None),
])
def test_the_engines_key_names_are_x3ds(engine, x3d):
    assert x3druntime.x3d_key(engine) == x3d


class FakeContext:
    def __init__(self):
        self.observed = []

    def observeEvents(self, kind, function, stop=False):
        self.observed.append((kind, function, stop))


def keyboard(name, state):
    event = keyboardevents.KeyboardEvent()
    event.name = name
    event.state = state
    return event


def test_a_key_sensor_observes_its_contexts_keys():
    sensor = x3druntime.KeySensor()
    context = FakeContext()
    sensor.bind(context)
    (kind, function, stop), = context.observed
    assert kind == 'keyboard' and not stop
    function(keyboard('<up>', 1))
    assert sensor.actionKeyPress == runtime.ACTION_KEYS['UP']
    function(keyboard('x', 1))
    function(keyboard('x', 0))
    assert sensor.keyRelease == 'x'
    function(keyboard('<numlock>', 1))


def test_a_documents_key_sensor_hears_the_window(gl_context):
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'<X3D version="4.0"><Scene><KeySensor DEF="K"/></Scene></X3D>',
                         'scene.x3d')
    with scene_context(scene) as context:
        context.OnDraw(force=1)
        context.ProcessEvent(keyboard('g', 1))
        assert scene.getDEF('K').keyPress == 'g'


def keypress(name):
    event = keyboardevents.KeypressEvent()
    event.name = name
    return event


def test_a_string_sensor_observes_its_contexts_typing():
    sensor = x3druntime.StringSensor()
    context = FakeContext()
    sensor.bind(context)
    (kind, function, _stop), = context.observed
    assert kind == 'keypress'
    for name in ('H', 'i', 'x', '<backspace>', '<numlock>', '<return>'):
        function(keypress(name))
    assert sensor.finalText == 'Hi'


class QueueContext:
    """A context's render queue and redraw requests, with no window"""

    def __init__(self):
        from OpenGLContext.events.renderqueue import RenderQueue  # noqa: PLC0415 kept with its use
        self.renderQueue = RenderQueue()
        self.redraws = 0

    def triggerRedraw(self, force=0):
        self.redraws += 1


@pytest.mark.parametrize('name', sorted(x3druntime.followers.FOLLOWERS))
def test_each_follower_is_the_engines(name):
    assert prototypes()[name].__module__ == x3druntime.__name__


def test_a_follower_ticks_through_its_contexts_queue_until_it_rests(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(systemtime, 'systemTime', lambda: now[0])
    chaser = x3druntime.ScalarChaser(duration=1.0)
    context = QueueContext()
    chaser.bind(context)
    chaser.set_destination = 4.0
    assert len(context.renderQueue) == 1
    for _ in range(5):
        now[0] += 0.3
        context.renderQueue.run()
    assert chaser.value_changed == pytest.approx(4.0)
    assert len(context.renderQueue) == 0
    assert context.redraws >= 4


def test_a_follower_moving_before_it_is_bound_starts_when_bound(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(systemtime, 'systemTime', lambda: now[0])
    chaser = x3druntime.ScalarChaser(duration=1.0, initialValue=0.0, initialDestination=2.0)
    context = QueueContext()
    chaser.bind(context)
    assert len(context.renderQueue) == 1


def test_a_documents_chaser_moves_a_transform(gl_context, monkeypatch):
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    now = [50.0]
    monkeypatch.setattr(systemtime, 'systemTime', lambda: now[0])
    scene = Loader.loads(b'''<X3D version="4.0"><Scene>
      <PositionChaser DEF="C" duration="1" initialDestination="0 0 0"/>
      <Transform DEF="T"><Shape><Box/></Shape></Transform>
      <ROUTE fromNode="C" fromField="value_changed" toNode="T" toField="set_translation"/>
    </Scene></X3D>''', 'scene.x3d')
    with scene_context(scene) as context:
        context.OnDraw(force=1)
        scene.getDEF('C').set_destination = (3.0, 0.0, 0.0)
        for _ in range(4):
            now[0] += 0.4
            context.renderQueue.run()
            context.OnDraw(force=1)
        assert tuple(scene.getDEF('T').translation) == pytest.approx((3.0, 0.0, 0.0))


def test_a_follower_bound_to_a_context_that_draws_nothing_still_moves(monkeypatch):
    """A window that has stopped drawing does not hold up the follower for the others."""
    now = [10.0]
    monkeypatch.setattr(systemtime, 'systemTime', lambda: now[0])
    chaser = x3druntime.ScalarChaser(duration=1.0)
    idle, drawing = QueueContext(), QueueContext()
    chaser.bind(idle)
    chaser.bind(drawing)
    chaser.set_destination = 2.0
    for _ in range(5):
        now[0] += 0.3
        drawing.renderQueue.run()
    assert chaser.value_changed == pytest.approx(2.0)
    assert len(drawing.renderQueue) == 0
