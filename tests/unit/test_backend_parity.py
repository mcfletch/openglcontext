"""Every window system offers the same window, whichever toolkit opened it.

OpenGLContext is meant to be the choice a thick-client project makes for its 3D,
which means the GUI toolkit the project already uses must not decide what the
engine can do. The capabilities below are the window-level ones -- the ones a
window system rather than the renderer has to provide -- and this is where they
are demanded of every window system at once, the way
`test_backend_context_lifecycle.py` demands the context-loss contract.

A window system that genuinely cannot do something answers ``False`` rather
than not having the method, so a caller can tell "this platform will not" from
"nobody implemented this" and offer the user something else. Where a platform
limit is real it is named here, once, with what it is.

See `plans/BACKEND-PARITY.md` and `plans/WINDOWSYSTEM-COMPOSITION.md`.
"""
import ast
import ctypes
import inspect
import os
import threading
from typing import ClassVar

import pytest
from OpenGL.GL import (
    GL_MATRIX_MODE, GL_NO_ERROR, GL_PROJECTION, glGetError, glGetIntegerv, glMatrixMode,
)

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext import context as context_module, testingcontext, windowsystem
from OpenGLContext.context import Context, contextAddress, sameContext
from OpenGLContext.events.eventhandlermixin import HeldKeyMixin
from OpenGLContext.scenegraph import imagetexture
from OpenGLContext.testing.glcontext import gl_available
from OpenGLContext.windowsystem.base import WindowSystem

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(os.path.dirname(HERE))

#: Every window system that owns a window, the module it lives in and its
#: class.  One missing from here is one nothing holds to the contract.
WINDOW_SYSTEMS = (
    ('glfw', 'OpenGLContext/windowsystem/glfw.py', 'GLFWWindowSystem'),
    ('glut', 'OpenGLContext/windowsystem/glut.py', 'GLUTWindowSystem'),
    ('pygame', 'OpenGLContext/windowsystem/pygame.py', 'PygameWindowSystem'),
    ('tk', 'OpenGLContext/windowsystem/tk.py', 'TkWindowSystem'),
    ('wx', 'OpenGLContext/windowsystem/wx.py', 'WxWindowSystem'),
)
WINDOW_SYSTEM_IDS = [entry[0] for entry in WINDOW_SYSTEMS]

#: What a window system has to define beyond the base class, the Context call
#: an application makes that reaches it, and why.
CAPABILITIES = (
    ('setPointerCapture', 'setPointerCapture',
     'mouse-look needs a hidden pointer reporting unbounded motion'),
    ('setFullscreen', 'setFullscreen',
     'a player has to be able to leave full screen without restarting'),
    ('applyVSync', 'applyVSync',
     'the settings screen writes the field; something has to read it'),
    ('pump', 'pumpWindowEvents',
     'a program driving its own loop has to be able to deliver input'),
    ('release', 'releaseWindow',
     'one name for letting a window and the GL objects in it go, so a caller '
     'that built a context need not know which toolkit made it'),
)
CAPABILITY_IDS = [entry[0] for entry in CAPABILITIES]


def _source(path):
    with open(os.path.join(PACKAGE, path), encoding='utf-8') as handle:
        return handle.read()


def _methods(path, className):
    """The methods the class ``className`` in the module at ``path`` defines,
    by name.

    Read from the source rather than imported, so a window system whose
    toolkit is not installed here is held to the contract as well.
    """
    for node in ast.parse(_source(path)).body:
        if isinstance(node, ast.ClassDef) and node.name == className:
            return {child.name: child for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))}
    raise AssertionError('%s defines no class %s' % (path, className))


#: The module each window system's toolkit is imported from, for a skip that
#: names what is not installed here.
TOOLKITS = {
    'glfw': 'glfw',
    'glut': 'OpenGL.GLUT',
    'pygame': 'pygame',
    'tk': 'tkinter',
    'wx': 'wx',
}


def _loaded(name):
    """The registered window-system class ``name``; skipped where its toolkit
    is not installed here."""
    pytest.importorskip(TOOLKITS[name])
    return windowsystem.load(name)


class TestEveryWindowSystemIsRegistered:
    """A name that does not resolve is a window system nobody can select."""

    @pytest.mark.parametrize('name', WINDOW_SYSTEM_IDS)
    def test_the_registered_name_resolves_to_a_class(self, name):
        assert name in windowsystem.registered(), (
            '%s is not registered as a window system' % (name,))
        loaded = _loaded(name)
        assert issubclass(loaded, WindowSystem)
        assert loaded.name == name

    @pytest.mark.parametrize('name', WINDOW_SYSTEM_IDS)
    def test_nothing_it_must_provide_is_missing(self, name):
        """An abstract method a window system leaves out makes it a class
        nobody can instantiate, so every context on it fails as it is built."""
        loaded = _loaded(name)
        assert not inspect.isabstract(loaded), (
            '%s leaves abstract: %s'
            % (name, ', '.join(sorted(loaded.__abstractmethods__))))


class TestEveryWindowSystemOffersTheWindowCapabilities:
    @pytest.mark.parametrize('name,path,className', WINDOW_SYSTEMS,
                             ids=WINDOW_SYSTEM_IDS)
    @pytest.mark.parametrize('capability,call,why', CAPABILITIES,
                             ids=CAPABILITY_IDS)
    def test_it_defines_the_capability(self, name, path, className,
                                       capability, call, why):
        assert capability in _methods(path, className), (
            '%s has no %s, so Context.%s cannot: %s'
            % (className, capability, call, why))


class TestTheAnswerIsAlwaysAnAnswer:
    """Each capability answers True or False, never None.

    False is what a caller acts on -- "this platform will not, offer something
    else" -- and a method that trails off the end without returning says
    nothing at all while looking like a refusal.
    """

    #: `release` is not one of these: it lets a window go, and there is
    #: nothing to answer about having done so.
    ANSWERING = tuple(entry[0] for entry in CAPABILITIES if entry[0] != 'release')

    @pytest.mark.parametrize('name,path,className', WINDOW_SYSTEMS,
                             ids=WINDOW_SYSTEM_IDS)
    @pytest.mark.parametrize('capability', ANSWERING)
    def test_every_path_out_returns_something(self, name, path, className,
                                              capability):
        node = _methods(path, className)[capability]
        returns = [child for child in ast.walk(node)
                   if isinstance(child, ast.Return)]
        assert returns, '%s.%s answers nothing' % (className, capability)
        assert all(child.value is not None for child in returns), (
            '%s.%s has a bare return' % (className, capability))
        assert isinstance(node.body[-1], (ast.Return, ast.Try)), (
            '%s.%s can fall off the end and answer None'
            % (className, capability))


class TestEveryWindowSystemReportsPointerMotionAsItHappens:
    """Mouse-look is not picking.

    A move delivered as a *pick* event arrives only once the selection buffer
    has resolved it, is dropped when the pointer is over nothing, and never
    arrives at all with picking switched off -- none of which has anything to do
    with turning the view. A window system that knows where the pointer went
    says so directly.
    """

    @pytest.mark.parametrize('name,path,className', WINDOW_SYSTEMS,
                             ids=WINDOW_SYSTEM_IDS)
    def test_it_calls_record_pointer_motion(self, name, path, className):
        assert 'recordPointerMotion' in _source(path), (
            '%s never reports pointer motion to the sampler, so a mouse-look '
            'mode grabs the pointer and the view never turns' % (name,))


class TestEveryWindowSystemLetsGoOfHeldKeys:
    """No key-up arrives for a key that was down when the window lost focus.

    Without something to say so, that key stays held for the rest of the
    session -- the camera keeps walking with nobody touching the keyboard.
    """

    @pytest.mark.parametrize('name,path,className', WINDOW_SYSTEMS,
                             ids=WINDOW_SYSTEM_IDS)
    def test_it_clears_held_keys(self, name, path, className):
        assert 'clearHeldKeys' in _source(path), (
            '%s never releases held keys' % (name,))


class _Bare(WindowSystem):
    """A window system that provides what it must and nothing more."""

    name = 'bare'

    def open(self, definition, parent=None):
        return True

    def release(self):
        pass

    def makeCurrent(self):
        return None

    def swap(self):
        pass

    def drawableSize(self):
        return (1, 1)


def _onBare(contextClass=Context):
    made = contextClass.__new__(contextClass)
    made.contextDefinition = ContextDefinition()
    made.windowsystem = _Bare(made)
    return made


class TestTheContractIsStatedOnce:
    """A new window system should inherit the contract rather than have to
    know it."""

    @pytest.mark.parametrize('capability,call,why', CAPABILITIES,
                             ids=CAPABILITY_IDS)
    def test_the_base_context_declares_it(self, capability, call, why):
        assert callable(getattr(Context, call, None)), why

    @pytest.mark.parametrize('capability,call,why', CAPABILITIES,
                             ids=CAPABILITY_IDS)
    def test_the_base_window_system_declares_it(self, capability, call, why):
        assert callable(getattr(WindowSystem, capability, None)), why

    def test_asking_for_vsync_writes_the_field_and_applies_it(self):
        """`setVSync` is the one call an application makes.

        Uncapping the frame rate is a thing every benchmark and every headless
        capture wants -- a forced redraw blocks on a swap nobody is presenting
        -- and each of them used to reach for `glfw.swap_interval` directly,
        which does nothing on any other backend and warns that GLFW is not
        initialised on all of them.
        """
        applied = []

        class _Applies(_Bare):
            def applyVSync(self, definition):
                applied.append(bool(definition.vsync))
                return True

        made = _onBare()
        made.windowsystem = _Applies(made)
        assert made.setVSync(False) is True
        assert applied == [False]
        assert bool(made.contextDefinition.vsync) is False
        made.setVSync(True)
        assert applied == [False, True]

    def test_it_answers_what_the_window_system_could_do(self):
        made = _onBare()
        assert made.setVSync(False) is False

    def test_a_window_system_that_cannot_says_so_rather_than_raising(self):
        """`False` is an answer a caller can act on; an AttributeError is not."""
        bare = _onBare()
        assert bare.setFullscreen(True) is False
        assert bare.setPointerCapture(True) is False
        assert bare.pumpWindowEvents() is False

    def test_held_key_tracking_is_shared(self):
        for name in ('noteKeyDown', 'noteKeyUp', 'pumpKeyRepeats',
                     'clearHeldKeys'):
            assert callable(getattr(HeldKeyMixin, name, None)), name


class TestTheSharedHeldKeyTracking:
    """The map, the synthetic repeat, and letting go on focus loss."""

    def _held(self):
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
        if not gl_available():
            pytest.skip('no GL target available')
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
        return ctypes.cast(ctypes.c_void_p(address), ctypes.POINTER(ctypes.c_int))

    def test_two_pointers_at_one_address_are_one_context(self):
        one, other = self._pointer(0xBEEF), self._pointer(0xBEEF)
        assert one != other, 'the hazard this guards has gone away'
        assert sameContext(one, other)

    def test_pointers_at_different_addresses_are_different_contexts(self):
        assert not sameContext(self._pointer(0xBEEF), self._pointer(0xC0FFEE))

    def test_an_integer_handle_compares_by_value(self):
        assert sameContext(0xBEEF, 0xBEEF)
        assert not sameContext(0xBEEF, 0xC0FFEE)

    def test_nothing_is_never_the_same_context_as_anything(self):
        """Including another nothing: no context is current, not 'the same one'."""
        assert not sameContext(None, None)
        assert not sameContext(0, 0)
        assert not sameContext(0xBEEF, None)

    def test_a_handle_that_is_no_kind_of_address_names_no_context(self):
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
        BaseContext = testingcontext.getInteractive()

        class Profiled(BaseContext):
            def OnInit(self):
                pass

        return Profiled(profile=profile)

    def test_a_compatibility_context_after_a_core_one_still_has_the_matrix_stack(self):
        if not gl_available():
            pytest.skip('no GL target available')

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
                assert glGetError() == GL_NO_ERROR
                assert glGetIntegerv(GL_MATRIX_MODE) == GL_PROJECTION
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


#: Every published context class in the package, windowed or offscreen, and
#: the module it lives in.  The contract below is about the ``Context`` API
#: rather than about owning a window.
CONTEXT_MODULES = (
    ('glfw', 'OpenGLContext/glfwcontext.py'),
    ('glut', 'OpenGLContext/glutcontext.py'),
    ('pygame', 'OpenGLContext/pygamecontext.py'),
    ('tk', 'OpenGLContext/tkcontext.py'),
    ('wx', 'OpenGLContext/wxcontext.py'),
    ('egl', 'OpenGLContext/eglcontext.py'),
    ('wgl', 'OpenGLContext/wglcontext.py'),
)


def _parameters(path, name):
    """The parameter names of the first ``def name`` in the module at ``path``"""
    for node in ast.walk(ast.parse(_source(path))):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            arguments = node.args
            return [arg.arg for arg in
                    arguments.posonlyargs + arguments.args + arguments.kwonlyargs]
    return None


class TestTakingTheContextIsTheSameCallEverywhere:
    """``setCurrent`` takes ``blocking`` on every context class, as the base
    does.

    The base class acquires the context lock with it, so ``setCurrent(0)`` is
    how a caller asks for the context *if it is free* and gets a
    ``LockingError`` rather than a wait.  An override that drops the parameter
    answers that call with ``TypeError`` instead.
    """

    def test_the_base_accepts_blocking(self):
        assert 'blocking' in inspect.signature(Context.setCurrent).parameters

    @pytest.mark.parametrize('name,path', CONTEXT_MODULES,
                             ids=[entry[0] for entry in CONTEXT_MODULES])
    def test_set_current_accepts_blocking(self, name, path):
        parameters = _parameters(path, 'setCurrent')
        if parameters is None:
            return                      # inherits the base class's own
        assert 'blocking' in parameters, (
            '%s.setCurrent drops the blocking argument, so setCurrent(0) is a '
            'TypeError there and a LockingError everywhere else' % (name,))


class TestTheVRMLContextsTakeTheirArguments:
    """``ContextMainLoop(size=..., title=...)`` reaches the constructor.

    It is the one call a program that opens a world makes, and the arguments
    are how it says what window it wants.
    """

    def test_the_glut_vrml_context_builds_with_what_it_was_given(self, monkeypatch):
        pytest.importorskip('OpenGL.GLUT')
        from OpenGLContext import glutvrmlcontext  # noqa: PLC0415 follows the GLUT importorskip
        from OpenGLContext.windowsystem import glut as glutsystem  # noqa: PLC0415 follows the GLUT importorskip

        built = []

        class _Stop(Exception):
            """Ends the call where the window would have been made."""

        class Recording(glutvrmlcontext.VRMLContext):
            def __init__(self, *arguments, **named):
                built.append((arguments, named))
                raise _Stop()

        # Nothing here may reach GLUT: initialising it needs a display, and a
        # second initialisation ends the process rather than raising.
        monkeypatch.setattr(glutsystem, 'ensureGlutInitialised',
                            lambda *_args, **_named: False)
        monkeypatch.setattr(glutsystem, 'glutInit', lambda *_args: None)
        monkeypatch.setattr(glutsystem, 'glutMainLoop', lambda: None,
                            raising=False)

        with pytest.raises(_Stop):
            Recording.ContextMainLoop(size=(640, 480), title='a world')
        assert built == [((), {'size': (640, 480), 'title': 'a world'})]
