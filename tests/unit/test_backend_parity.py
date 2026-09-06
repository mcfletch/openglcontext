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
from OpenGLContext.contextdefinition import ContextDefinition

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(os.path.dirname(HERE))

#: Every backend that owns a window, and the module its Context lives in.  A
#: backend missing from here is a backend nothing holds to the contract.
BACKENDS = (
    ('glfw', 'OpenGLContext/glfwcontext.py'),
    ('glut', 'OpenGLContext/glutcontext.py'),
    ('pygame', 'OpenGLContext/pygamecontext.py'),
    ('tk', 'OpenGLContext/tkcontext.py'),
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
    ('pumpWindowEvents',
     'a program driving its own loop has to be able to deliver input'),
    ('releaseWindow',
     'one name for letting a window and the GL objects in it go, so a caller '
     'that built a context need not know which backend made it'),
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

    #: `releaseWindow` is not one of these: it lets a window go, and there is
    #: nothing to answer about having done so.
    ANSWERING = tuple(entry for entry in CAPABILITIES
                      if entry[0] != 'releaseWindow')

    @pytest.mark.parametrize('name,path', BACKENDS,
                             ids=[b[0] for b in BACKENDS])
    @pytest.mark.parametrize('capability,why', ANSWERING,
                             ids=[c[0] for c in ANSWERING])
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
        'tk': 'OpenGLContext/events/tkevents.py',
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

    def test_asking_for_vsync_writes_the_field_and_applies_it(self):
        """`setVSync` is the one call an application makes.

        Uncapping the frame rate is a thing every benchmark and every headless
        capture wants -- a forced redraw blocks on a swap nobody is presenting
        -- and each of them used to reach for `glfw.swap_interval` directly,
        which does nothing on any other backend and warns that GLFW is not
        initialised on all of them.
        """
        applied = []

        class _Backend(Context):
            def applyVSync(self, definition=None):
                applied.append(bool(self.contextDefinition.vsync))
                return True

        made = _Backend.__new__(_Backend)
        made.contextDefinition = ContextDefinition()
        assert made.setVSync(False) is True
        assert applied == [False]
        assert bool(made.contextDefinition.vsync) is False
        made.setVSync(True)
        assert applied == [False, True]

    def test_it_answers_what_the_backend_could_do(self):
        class _Cannot(Context):
            pass

        made = _Cannot.__new__(_Cannot)
        made.contextDefinition = ContextDefinition()
        assert made.setVSync(False) is False

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


class TestAContextKnowsItsSizeAsSoonAsItExists:
    """``getViewPort()`` answers before a single event has been pumped.

    Everything that sizes itself from the window -- the projection matrix, the
    overlay's scale, a picking ray, a screenshot -- asks the context how big it
    is, and the first frame is drawn before any toolkit has delivered a resize.
    A backend that waits to be told its size renders that frame into a zero
    viewport.
    """

    def test_the_run_s_backend_reports_a_size(self):
        from OpenGLContext.testing.glcontext import gl_available
        if not gl_available():
            pytest.skip('no GL target available')
        from OpenGLContext import testingcontext
        BaseContext = testingcontext.getInteractive()

        class Sized(BaseContext):
            def Render(self, mode=None):
                pass

        context = Sized(ContextDefinition(size=(160, 120)))
        try:
            width, height = context.getViewPort()
        finally:
            context.releaseWindow()
        assert width > 0 and height > 0, (
            'the context reported %sx%s before any event was pumped'
            % (width, height))


class TestTheContextThreadCheckBeforeThereIsOne:
    """``inContextThread`` answers rather than raising.

    Backends call it while setting a window up, which is before any context has
    claimed a thread -- and until one has, there is no wrong thread to be on.
    """

    def test_no_context_thread_yet_is_not_the_wrong_thread(self, monkeypatch):
        from OpenGLContext import context as context_module
        monkeypatch.setattr(context_module, 'contextThread', None)
        assert context_module.inContextThread()


class TestTellingOneGLContextFromAnother:
    """Two handles name the same context when they point at the same thing.

    A platform answers with whatever its binding API calls a context, and GLX
    hands back a fresh ctypes pointer object per query -- two of them at one
    address are unequal, because ``==`` on a pointer object is identity.  A
    backend comparing them raw would take its own context for a foreign one and
    let go of it, which on GLUT it can never take back.
    """

    def _pointer(self, address):
        import ctypes
        return ctypes.cast(ctypes.c_void_p(address), ctypes.POINTER(ctypes.c_int))

    def test_two_pointers_at_one_address_are_one_context(self):
        from OpenGLContext.context import sameContext
        one, other = self._pointer(0xBEEF), self._pointer(0xBEEF)
        assert one != other, 'the hazard this guards has gone away'
        assert sameContext(one, other)

    def test_pointers_at_different_addresses_are_different_contexts(self):
        from OpenGLContext.context import sameContext
        assert not sameContext(self._pointer(0xBEEF), self._pointer(0xC0FFEE))

    def test_an_integer_handle_compares_by_value(self):
        from OpenGLContext.context import sameContext
        assert sameContext(0xBEEF, 0xBEEF)
        assert not sameContext(0xBEEF, 0xC0FFEE)

    def test_nothing_is_never_the_same_context_as_anything(self):
        """Including another nothing: no context is current, not 'the same one'."""
        from OpenGLContext.context import sameContext
        assert not sameContext(None, None)
        assert not sameContext(0, 0)
        assert not sameContext(0xBEEF, None)

    def test_a_handle_that_is_no_kind_of_address_names_no_context(self):
        from OpenGLContext.context import contextAddress
        assert contextAddress(object()) is None


class TestTheProfileAskedForIsTheProfileGiven:
    """A context's profile does not depend on what was built before it.

    Some window systems keep the parameters a context is created from as
    process-global state, so a backend that sets only what it wants leaves the
    rest of the last request in place: a compatibility context asked for after
    a core one then arrives with the fixed-function pipeline removed, and every
    ``glMatrixMode`` in it raises ``GL_INVALID_OPERATION``.
    """

    def _built(self, profile):
        from OpenGLContext import testingcontext
        BaseContext = testingcontext.getInteractive()

        class Profiled(BaseContext):
            def OnInit(self):
                pass

        return Profiled(profile=profile)

    def test_a_compatibility_context_after_a_core_one_still_has_the_matrix_stack(self):
        from OpenGLContext.testing.glcontext import gl_available
        if not gl_available():
            pytest.skip('no GL target available')
        from OpenGL.GL import GL_PROJECTION, glMatrixMode

        core = self._built('core')
        core.releaseWindow()
        compatibility = self._built('compatibility')
        try:
            # Balanced: setCurrent takes context.contextLock and unsetCurrent is
            # what gives it back.  A test that keeps it holds it for the rest of
            # the session, and every background loader blocks on it.
            compatibility.setCurrent()
            try:
                glMatrixMode(GL_PROJECTION)
            finally:
                compatibility.unsetCurrent()
        finally:
            compatibility.releaseWindow()


class TestNothingKeepsTheProcessAlive:
    """A background loader cannot stop the interpreter from exiting.

    Python joins every non-daemon thread as it shuts down.  An image texture
    loads its URL on a thread that ends by asking each live context to redraw,
    and ``triggerRedraw`` takes the context lock -- so a loader whose lock never
    comes is a loader that never finishes, and a process that never exits.  The
    suite met that as a seven-minute run followed by thirteen minutes of
    nothing.  An image nobody is going to see is not a reason to refuse to
    exit.
    """

    def test_an_image_load_runs_on_a_daemon_thread(self):
        import threading

        from OpenGLContext.scenegraph import imagetexture

        started = []
        real = threading.Thread

        class Recording(real):
            def start(self):
                started.append(self)

        threading.Thread = Recording
        try:
            imagetexture.ImageTexture(url=['no-such-image.png'])
        finally:
            threading.Thread = real
        assert started, 'setting a url started no loader'
        assert all(thread.daemon for thread in started), (
            'an image loader can keep the process alive after its last window '
            'has gone')
