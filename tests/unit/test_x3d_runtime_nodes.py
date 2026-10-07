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
                                  'IntegerSequencer', 'KeySensor'])
def test_each_is_the_engines(name):
    assert issubclass(prototypes()[name], runtime.PROTOTYPES[name])


def test_a_time_trigger_sends_the_engines_time(monkeypatch):
    monkeypatch.setattr(systemtime, 'systemTime', lambda: 99.5)
    made = x3druntime.TimeTrigger()
    made.set_boolean = True
    assert made.triggerTime == 99.5


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
