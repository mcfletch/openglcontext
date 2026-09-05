"""Every backend offers the same window, whichever toolkit opened it.

OpenGLContext is meant to be the choice a thick-client project makes for its 3D,
which means the GUI toolkit the project already uses must not decide what the
engine can do. The capabilities below are the window-level ones -- the ones a
backend rather than the renderer has to provide -- and this is where they are
demanded of every backend at once, the way
`test_backend_context_lifecycle.py` demands the context-loss contract.

A backend that genuinely cannot do something answers ``False`` rather than not
having the method, so a caller can tell "this platform will not" from "nobody
implemented this" and offer the user something else. Where a platform limit is
real it is named here, once, with what it is.

See `plans/BACKEND-PARITY.md`.
"""
import ast
import os

import pytest

from OpenGLContext import plugins
from OpenGLContext.context import Context

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(os.path.dirname(HERE))

#: Every backend that owns a window, and the module its Context lives in.  A
#: backend missing from here is a backend nothing holds to the contract.
BACKENDS = (
    ('glfw', 'OpenGLContext/glfwcontext.py'),
    ('glut', 'OpenGLContext/glutcontext.py'),
    ('pygame', 'OpenGLContext/pygamecontext.py'),
    ('wx', 'OpenGLContext/wxcontext.py'),
)

#: The three plug-in kinds a backend registers under: the bare window, the one
#: with navigation, and the one that can open a scene file.
KINDS = (plugins.Context, plugins.InteractiveContext, plugins.VRMLContext)

#: What a backend has to define beyond the base class, and why.
CAPABILITIES = (
    ('setPointerCapture',
     'mouse-look needs a hidden pointer reporting unbounded motion'),
    ('setFullscreen',
     'a player has to be able to leave full screen without restarting'),
    ('applyVSync',
     'the settings screen writes the field; something has to read it'),
)


def _source(path):
    with open(os.path.join(PACKAGE, path), encoding='utf-8') as handle:
        return handle.read()


def _defines(path, name):
    """Whether the module at ``path`` defines a method called ``name``"""
    for node in ast.walk(ast.parse(_source(path))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return True
    return False


class TestEveryBackendIsRegistered:
    """A name that does not resolve is a backend nobody can select."""

    @pytest.mark.parametrize('name', [backend[0] for backend in BACKENDS])
    @pytest.mark.parametrize('kind', KINDS, ids=[k.__name__ for k in KINDS])
    def test_the_registered_name_resolves_to_a_class(self, name, kind):
        registered = [plugin for plugin in kind.registry if plugin.name == name]
        assert registered, '%s is not registered as a %s' % (name, kind.__name__)
        try:
            found = Context.getContextType(name, kind)
        except Exception as error:              # pragma: no cover - a typo
            pytest.fail('%s %s: %r' % (name, kind.__name__, error))
        if found is None:
            pytest.skip('%s is registered but its toolkit is not installed'
                        % (name,))
        assert isinstance(found, type)


class TestEveryBackendOffersTheWindowCapabilities:
    @pytest.mark.parametrize('name,path', BACKENDS,
                             ids=[b[0] for b in BACKENDS])
    @pytest.mark.parametrize('capability,why', CAPABILITIES,
                             ids=[c[0] for c in CAPABILITIES])
    def test_it_defines_the_capability(self, name, path, capability, why):
        assert _defines(path, capability), '%s has no %s: %s' % (
            name, capability, why)


class TestTheAnswerIsAlwaysAnAnswer:
    """Each capability answers True or False, never None.

    False is what a caller acts on -- "this platform will not, offer something
    else" -- and a method that trails off the end without returning says
    nothing at all while looking like a refusal.
    """

    @pytest.mark.parametrize('name,path', BACKENDS,
                             ids=[b[0] for b in BACKENDS])
    @pytest.mark.parametrize('capability,why', CAPABILITIES,
                             ids=[c[0] for c in CAPABILITIES])
    def test_every_path_out_returns_something(self, name, path, capability, why):
        for node in ast.walk(ast.parse(_source(path))):
            if isinstance(node, ast.FunctionDef) and node.name == capability:
                returns = [child for child in ast.walk(node)
                           if isinstance(child, ast.Return)]
                assert returns, '%s.%s answers nothing' % (name, capability)
                assert all(child.value is not None for child in returns), (
                    '%s.%s has a bare return' % (name, capability))
                assert isinstance(node.body[-1], (ast.Return, ast.Try)), (
                    '%s.%s can fall off the end and answer None'
                    % (name, capability))


class TestEveryBackendReportsPointerMotionAsItHappens:
    """Mouse-look is not picking.

    A move delivered as a *pick* event arrives only once the selection buffer
    has resolved it, is dropped when the pointer is over nothing, and never
    arrives at all with picking switched off -- none of which has anything to do
    with turning the view. A backend that knows where the pointer went says so
    directly.
    """

    EVENTS = {
        'glfw': 'OpenGLContext/events/glfwevents.py',
        'glut': 'OpenGLContext/events/glutevents.py',
        'pygame': 'OpenGLContext/events/pygameevents.py',
        'wx': 'OpenGLContext/events/wxevents.py',
    }

    @pytest.mark.parametrize('name', sorted(EVENTS))
    def test_it_calls_record_pointer_motion(self, name):
        assert 'recordPointerMotion' in _source(self.EVENTS[name]), (
            '%s never reports pointer motion to the sampler, so a mouse-look '
            'mode grabs the pointer and the view never turns' % (name,))


class TestEveryBackendLetsGoOfHeldKeys:
    """No key-up arrives for a key that was down when the window lost focus.

    Without something to say so, that key stays held for the rest of the
    session -- the camera keeps walking with nobody touching the keyboard.
    """

    @pytest.mark.parametrize('name,path', BACKENDS,
                             ids=[b[0] for b in BACKENDS])
    def test_it_clears_held_keys(self, name, path):
        events = 'OpenGLContext/events/%sevents.py' % (name,)
        assert ('clearHeldKeys' in _source(path)
                or 'clearHeldKeys' in _source(events)), (
            '%s never releases held keys' % (name,))


class TestTheContractIsStatedOnce:
    """A new backend should inherit the contract rather than have to know it."""

    @pytest.mark.parametrize('capability,why', CAPABILITIES,
                             ids=[c[0] for c in CAPABILITIES])
    def test_the_base_context_declares_it(self, capability, why):
        assert callable(getattr(Context, capability, None)), why

    def test_a_backend_that_cannot_says_so_rather_than_raising(self):
        """`False` is an answer a caller can act on; an AttributeError is not."""
        bare = Context.__new__(Context)
        assert Context.setFullscreen(bare, True) is False
        assert Context.setPointerCapture(bare, True) is False

    def test_held_key_tracking_is_shared(self):
        from OpenGLContext.events.eventhandlermixin import HeldKeyMixin

        for name in ('noteKeyDown', 'noteKeyUp', 'pumpKeyRepeats',
                     'clearHeldKeys'):
            assert callable(getattr(HeldKeyMixin, name, None)), name


class TestTheSharedHeldKeyTracking:
    """The map, the synthetic repeat, and letting go on focus loss."""

    def _held(self):
        from OpenGLContext.events.eventhandlermixin import HeldKeyMixin

        class _Keys(HeldKeyMixin):
            def __init__(self):
                self.emitted = []

            def emitKey(self, key, state, modifiers):
                self.emitted.append((key, state, modifiers))

        return _Keys()

    def test_a_key_that_is_down_is_remembered(self):
        keys = self._held()
        keys.noteKeyDown('w', (0, 0, 0))
        assert keys.heldKeys() == {'w': (0, 0, 0)}

    def test_a_key_that_comes_up_is_forgotten(self):
        keys = self._held()
        keys.noteKeyDown('w', (0, 0, 0))
        keys.noteKeyUp('w')
        assert keys.heldKeys() == {}

    def test_losing_focus_releases_what_was_held(self):
        keys = self._held()
        keys.noteKeyDown('w', (0, 0, 0))
        keys.noteKeyDown('a', (1, 0, 0))
        keys.clearHeldKeys()
        assert sorted(keys.emitted) == [('a', 0, (1, 0, 0)), ('w', 0, (0, 0, 0))]
        assert keys.heldKeys() == {}

    def test_releasing_twice_releases_once(self):
        keys = self._held()
        keys.noteKeyDown('w', (0, 0, 0))
        keys.clearHeldKeys()
        keys.clearHeldKeys()
        assert keys.emitted == [('w', 0, (0, 0, 0))]

    def test_a_held_key_repeats_once_the_delay_has_passed(self):
        keys = self._held()
        keys.noteKeyDown('w', (0, 0, 0), now=0.0)
        keys.pumpKeyRepeats(now=0.0)
        assert keys.emitted == []
        keys.pumpKeyRepeats(now=keys.keyRepeatDelay + 0.001)
        assert keys.emitted == [('w', 1, (0, 0, 0))]

    def test_it_repeats_at_the_interval_after_that(self):
        keys = self._held()
        keys.noteKeyDown('w', (0, 0, 0), now=0.0)
        when = keys.keyRepeatDelay + 0.001
        keys.pumpKeyRepeats(now=when)
        keys.pumpKeyRepeats(now=when + keys.keyRepeatInterval / 2.0)
        assert len(keys.emitted) == 1
        keys.pumpKeyRepeats(now=when + keys.keyRepeatInterval + 0.001)
        assert len(keys.emitted) == 2

    def test_a_platform_that_repeats_for_itself_stops_the_synthetic_one(self):
        keys = self._held()
        keys.noteKeyDown('w', (0, 0, 0), now=0.0)
        keys.noteNativeRepeat()
        keys.pumpKeyRepeats(now=100.0)
        assert keys.emitted == []

    def test_nothing_held_is_nothing_to_do(self):
        keys = self._held()
        keys.pumpKeyRepeats(now=100.0)
        keys.clearHeldKeys()
        assert keys.emitted == []
