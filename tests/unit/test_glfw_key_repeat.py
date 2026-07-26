"""Software key-repeat for the GLFW backend.

GLFW's Wayland platform (in a nested/container compositor) often never delivers
glfw.REPEAT, so holding a key would stop after the initial press -- breaking
camera navigation. EventHandlerMixin synthesises repeats from PRESS..RELEASE and
disables that the moment a native repeat proves the platform delivers its own.

These tests drive the dispatch stack headlessly (no GL context) with
delay/interval set to 0 so each pumpKeyRepeats() deterministically emits one
repeat -- no real-time sleeping.
"""
import glfw
import pytest

from OpenGLContext.events import glfwevents, keyboardevents


class _Ctx(glfwevents.EventHandlerMixin):
    currentPass = None
    drawing = False
    window = None
    keyRepeatDelay = 0.0
    keyRepeatInterval = 0.0

    def __init__(self):
        self._EventHandlerMixin__managers = {}
        self.addEventManager('keyboard', keyboardevents.KeyboardEventManager())

    def getViewPort(self):
        return (100, 100)


@pytest.fixture
def ctx():
    c = _Ctx()
    counts = {'down': 0, 'up': 0}
    # Held strongly: pydispatch connects handlers with weak references.
    handlers = [
        lambda e: counts.__setitem__('down', counts['down'] + 1),
        lambda e: counts.__setitem__('up', counts['up'] + 1),
    ]
    c.addEventHandler('keyboard', name='<right>', state=1, function=handlers[0])
    c.addEventHandler('keyboard', name='<right>', state=0, function=handlers[1])
    c._handlers = handlers
    c.counts = counts
    try:
        yield c
    finally:
        c.addEventHandler('keyboard', name='<right>', state=1, function=None)
        c.addEventHandler('keyboard', name='<right>', state=0, function=None)


def _press(c):
    c.glfwOnKey(None, glfw.KEY_RIGHT, 0, glfw.PRESS, 0)


def _release(c):
    c.glfwOnKey(None, glfw.KEY_RIGHT, 0, glfw.RELEASE, 0)


def test_press_emits_key_down(ctx):
    _press(ctx)
    assert ctx.counts['down'] == 1
    assert ctx.counts['up'] == 0


def test_software_repeat_fires_while_held(ctx):
    _press(ctx)
    for _ in range(5):
        ctx.pumpKeyRepeats()
    # 1 press + 5 synthetic repeats
    assert ctx.counts['down'] == 6


def test_release_stops_repeat(ctx):
    _press(ctx)
    ctx.pumpKeyRepeats()
    _release(ctx)
    assert ctx.counts['up'] == 1
    down_after_release = ctx.counts['down']
    for _ in range(5):
        ctx.pumpKeyRepeats()
    assert ctx.counts['down'] == down_after_release  # no repeats once released


def test_native_repeat_disables_software_repeat(ctx):
    _press(ctx)
    ctx.glfwOnKey(None, glfw.KEY_RIGHT, 0, glfw.REPEAT, 0)  # native repeat
    assert ctx._nativeRepeat is True
    down_before = ctx.counts['down']
    for _ in range(5):
        ctx.pumpKeyRepeats()
    assert ctx.counts['down'] == down_before  # software must not double up


def test_focus_loss_clears_held_keys(ctx):
    _press(ctx)
    ctx.clearHeldKeys()
    down_before = ctx.counts['down']
    for _ in range(5):
        ctx.pumpKeyRepeats()
    assert ctx.counts['down'] == down_before


def test_pump_is_noop_when_no_key_held(ctx):
    for _ in range(5):
        ctx.pumpKeyRepeats()
    assert ctx.counts['down'] == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


class TestSpecialKeysAreNotCharacters:
    """Where a function key can be bound, and where it cannot.

    GLFW reports character input and key transitions through different
    callbacks: ``glfwOnCharacter`` produces the ``keypress`` events, and a
    function key produces no character at all.  So a handler registered as
    ``addEventHandler('keypress', name='<F10>', ...)`` is silently dead -- the
    binding is accepted and never fires.  Special keys have to be bound on
    ``keyboard`` with an explicit state.
    """

    def test_a_function_key_has_a_name_in_the_key_mapping(self):
        from OpenGLContext.events import glfwevents
        assert glfwevents.keyboardMapping[glfw.KEY_F10] == '<F10>'

    def test_a_function_key_produces_a_keyboard_event(self):
        from OpenGLContext.events import glfwevents

        class Recorder(glfwevents.EventHandlerMixin):
            def __init__(self):
                self.events = []

            def ProcessEvent(self, event):
                self.events.append(event)

        recorder = Recorder()
        recorder.glfwOnKey(None, glfw.KEY_F10, 0, glfw.PRESS, 0)
        assert [(e.type, e.name, e.state) for e in recorder.events] == [
            ('keyboard', '<F10>', 1)]

    def test_the_overlay_demo_binds_its_screens_where_they_arrive(self):
        """The demo is the worked example, so its bindings have to be right."""
        import inspect
        from OpenGLContext.bin import ui_demo
        source = inspect.getsource(ui_demo.UIDemoContext.OnInit)
        assert "addEventHandler('keyboard'" in source
        assert "addEventHandler('keypress'" not in source
