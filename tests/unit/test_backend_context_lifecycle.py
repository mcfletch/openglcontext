"""Every window system says when it takes a context and when it lets one go.

Two things listen.  The engine's own caches hold GL names keyed by the context
handle, and PyOpenGL's C dispatch layer holds a table of resolved entry-point
addresses keyed by the same handle.  Both are only trustworthy while something
tells them a context has gone, because a driver hands the same handle out again
for the next context -- and then a cache answers the new one with the dead one's
names, and PyOpenGL calls the dead one's function pointers.

A window system that does not announce leaves both wrong, occasionally, nowhere
near the code that caused it.
"""

import ast
import os

import pytest
from OpenGL import _dispatch

from OpenGLContext import context as context_module, contextresources
from OpenGLContext.testing.glcontext import gl_available
from OpenGLContext.windowsystem.base import WindowSystem

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(os.path.dirname(HERE))

#: The class every window system derives from, and the module it lives in.
BASE = ('OpenGLContext/windowsystem/base.py', 'WindowSystem')

#: Every window system that owns a GL context, the module it lives in and its
#: class.  One missing from here is one nothing holds to the contract.
WINDOW_SYSTEMS = (
    ('glfw', 'OpenGLContext/windowsystem/glfw.py', 'GLFWWindowSystem'),
    ('glut', 'OpenGLContext/windowsystem/glut.py', 'GLUTWindowSystem'),
    ('pygame', 'OpenGLContext/windowsystem/pygame.py', 'PygameWindowSystem'),
    ('tk', 'OpenGLContext/windowsystem/tk.py', 'TkWindowSystem'),
    ('wx', 'OpenGLContext/windowsystem/wx.py', 'WxWindowSystem'),
    ('egl', 'OpenGLContext/windowsystem/egl.py', 'EGLWindowSystem'),
    ('wgl', 'OpenGLContext/windowsystem/wgl.py', 'WGLWindowSystem'),
)
IDS = [entry[0] for entry in WINDOW_SYSTEMS]

#: What a window system calls to say its GL context is going.
ANNOUNCEMENT = 'self.context.releaseContextResources'


def _methods(path, className):
    """The methods of the class ``className`` in the module at ``path``"""
    source = open(os.path.join(PACKAGE, path), encoding='utf-8').read()
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == className:
            return {child.name: child for child in node.body
                    if isinstance(child, ast.FunctionDef)}
    raise AssertionError('%s defines no class %s' % (path, className))


def _calls_within(path, className, function, depth=3):
    """Every attribute call one method of a window system reaches.

    Follows ``self.something()`` into that method -- the class's own, or the
    base class's where it does not define one -- and ``super().something()``
    into the base class's, so a window system that leaves its teardown to
    ``release`` rather than writing it out counts as making the call.
    """
    own = _methods(path, className)
    base = _methods(*BASE)

    def within(node, remaining):
        if node is None or remaining <= 0:
            return set()
        names = set()
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            parts = []
            target = inner.func
            while isinstance(target, ast.Attribute):
                parts.append(target.attr)
                target = target.value
            if isinstance(target, ast.Name):
                dotted = '.'.join(reversed(parts + [target.id]))
                names.add(dotted)
                if target.id == 'self' and len(parts) == 1:
                    names |= within(own.get(parts[0], base.get(parts[0])),
                                    remaining - 1)
            elif (isinstance(target, ast.Call) and len(parts) == 1
                  and isinstance(target.func, ast.Name)
                  and target.func.id == 'super'):
                names |= within(base.get(parts[0]), remaining - 1)
        return names

    return within(own.get(function, base.get(function)), depth)


class TestEveryWindowSystemAnnouncesTheEndOfAContext:
    @pytest.mark.parametrize('name,path,className', WINDOW_SYSTEMS, ids=IDS)
    def test_it_releases_the_context_it_owned(self, name, path, className):
        assert ANNOUNCEMENT in _calls_within(path, className, 'release'), (
            '%s never says its context is going, so every cache keyed on the '
            'handle keeps answering for it' % (name,)
        )

    @pytest.mark.parametrize('name,path,className', WINDOW_SYSTEMS, ids=IDS)
    def test_quitting_releases_before_the_process_ends(self, name, path,
                                                       className):
        """``Context.OnQuit`` ends the process with ``os._exit``.

        Nothing after it runs -- no ``finally``, no ``atexit`` hook -- so a
        window system that leaves the release to the end of its main loop does
        not release at all on the path a user actually takes, which is pressing
        Escape or closing the window. The release has to happen in ``quit``,
        which ``OnQuit`` asks before it ends anything.
        """
        assert ANNOUNCEMENT in _calls_within(path, className, 'quit'), (
            "%s releases its context only after its loop, and quitting never "
            "reaches there" % (name,)
        )

    def test_the_context_asks_the_window_system_before_it_exits(self):
        """The window system's ``quit`` is only the release if the context
        calls it ahead of ``os._exit``."""
        source = open(os.path.join(PACKAGE, 'OpenGLContext/context.py'),
                      encoding='utf-8').read()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ClassDef) and node.name == 'ContextCore':
                onQuit = next(child for child in node.body
                              if isinstance(child, ast.FunctionDef)
                              and child.name == 'OnQuit')
                break
        else:
            raise AssertionError('context.py defines no ContextCore')
        lines = {ast.unparse(call.func): call.lineno for call in ast.walk(onQuit)
                 if isinstance(call, ast.Call)}
        assert 'self.windowsystem.quit' in lines
        assert 'os._exit' in lines
        assert lines['self.windowsystem.quit'] < lines['os._exit']


class TestQuittingReallyReleases:
    """The static contract above, run rather than read.

    Through GLFW, which is the window system this container can open a window
    on; the shape is the same on every one, and the static check is what holds
    the ones a given machine cannot run.
    """

    def _quit(self, monkeypatch):
        """Build a window, quit it, and answer what the quit told the caches"""
        if not gl_available():
            pytest.skip('no GL target available')
        pytest.importorskip('glfw')

        told = []
        monkeypatch.setattr(contextresources, 'context_lost',
                            lambda: told.append('engine'))
        # OnQuit ends the process; what is under test is what happens before
        # it does.
        monkeypatch.setattr(os, '_exit', lambda _status: told.append('exited'))
        monkeypatch.setenv('OPENGLCONTEXT_HIDDEN', '1')
        made = context_module.Context(windowsystem='glfw', size=(64, 64))
        made.OnQuit()
        return made, told

    def test_the_caches_are_told_before_the_process_ends(self, monkeypatch):
        _made, told = self._quit(monkeypatch)
        assert told == ['engine', 'exited'], told

    def test_the_window_is_gone_afterwards(self, monkeypatch):
        made, _told = self._quit(monkeypatch)
        assert made.window is None

    def test_quitting_twice_releases_once(self, monkeypatch):
        made, told = self._quit(monkeypatch)
        made.OnQuit()
        assert told.count('engine') == 1


class _Failed(Exception):
    """Raised part-way through building a context."""


class _HalfOpened(WindowSystem):
    """A window system whose window exists by the time ``open`` fails."""

    name = 'half-opened'

    def __init__(self, context, failIn='open'):
        super().__init__(context)
        self.failIn = failIn
        self.abandoned = 0
        self.released = 0

    def open(self, definition, parent=None):
        self.window = 'window'
        if self.failIn == 'open':
            raise _Failed()
        return False

    def abandon(self):
        self.abandoned += 1
        self.window = None

    def release(self):
        self.released += 1

    def makeCurrent(self):
        return None

    def swap(self):
        pass

    def drawableSize(self):
        return (1, 1)


class TestAFailedConstructionGivesTheWindowBack:
    """A context that fails to build hands back what its window system made.

    An application that catches the failure and carries on -- tries another
    window system, asks for a smaller context -- would otherwise keep a window
    and a GL context for every attempt.  No cache has seen the context, so none
    is told it is going.
    """

    def _build(self, failIn):
        made = []

        class Failing(context_module.Context):
            def createWindowSystem(self, definition):
                made.append(_HalfOpened(self, failIn))
                return made[0]

            def setupCallbacks(self):
                if failIn == 'setup':
                    raise _Failed()

        with pytest.raises(_Failed):
            Failing()
        return made[0]

    @pytest.mark.parametrize('failIn', ['open', 'setup'])
    def test_the_window_system_abandons_what_it_made(self, failIn):
        system = self._build(failIn)
        assert system.abandoned == 1
        assert system.released == 0
        assert system.window is None

    @pytest.mark.parametrize('name,path,className', WINDOW_SYSTEMS, ids=IDS)
    def test_every_window_system_can_abandon(self, name, path, className):
        assert 'abandon' in _methods(path, className), (
            '%s inherits the base class\'s abandon, which gives nothing back, '
            'so a failed construction leaves its window open' % (name,))

    @pytest.mark.parametrize('name,path,className', WINDOW_SYSTEMS, ids=IDS)
    def test_abandoning_tells_no_cache(self, name, path, className):
        assert ANNOUNCEMENT not in _calls_within(path, className, 'abandon'), (
            '%s announces the loss of a context no cache has seen, which drops '
            'whichever context is current instead' % (name,))

    def test_a_real_window_is_gone_afterwards(self, monkeypatch):
        """Through GLFW, which this container can open a window on."""
        if not gl_available():
            pytest.skip('no GL target available')
        pytest.importorskip('glfw')
        told = []
        monkeypatch.setattr(contextresources, 'context_lost',
                            lambda: told.append('engine'))
        monkeypatch.setenv('OPENGLCONTEXT_HIDDEN', '1')
        made = []

        class Failing(context_module.Context):
            def createWindowSystem(self, definition):
                made.append(super().createWindowSystem(definition))
                return made[0]

            def setupCallbacks(self):
                raise _Failed()

        with pytest.raises(_Failed):
            Failing(windowsystem='glfw', size=(32, 32))
        assert made[0].window is None
        assert told == []


class _AnyContext:
    """Any object the contract is called against; it records its own handle."""


class TestTheContractIsStatedOnce:
    """A new window system should inherit the contract rather than have to
    know it."""

    def test_the_base_context_offers_both_halves(self):
        assert callable(context_module.Context.bindContextResources)
        assert callable(context_module.Context.releaseContextResources)

    def test_releasing_tells_the_engines_caches(self, monkeypatch):
        told = []
        monkeypatch.setattr(
            contextresources, 'context_lost', lambda: told.append('engine')
        )
        context_module.Context.releaseContextResources(
            _AnyContext(), handle=0xC0FFEE
        )
        assert 'engine' in told

    def test_releasing_tells_pyopengl(self, monkeypatch):
        told = []
        monkeypatch.setattr(contextresources, 'context_lost', lambda: None)
        monkeypatch.setattr(
            _dispatch, 'forget_context', lambda handle: told.append(handle)
        )
        context_module.Context.releaseContextResources(_AnyContext(), handle=0xC0FFEE)
        assert told == [0xC0FFEE]

    def test_binding_tells_pyopengl(self, monkeypatch):
        told = []
        monkeypatch.setattr(
            _dispatch, 'make_current', lambda handle: told.append(handle)
        )
        context_module.Context.bindContextResources(_AnyContext(), handle=0xBEEF)
        assert told == [0xBEEF]

    def test_a_handle_of_none_is_not_an_error(self, monkeypatch):
        """A backend that cannot name its handle still has caches to release,
        and the release is the half that matters."""
        told = []
        monkeypatch.setattr(
            contextresources, 'context_lost', lambda: told.append('engine')
        )
        context_module.Context.releaseContextResources(_AnyContext(), handle=None)
        assert told == ['engine']

    def test_both_halves_work_where_pyopengl_has_no_c_layer(self, monkeypatch):
        told = []
        monkeypatch.setattr(_dispatch, 'ACTIVE', False)
        monkeypatch.setattr(
            contextresources, 'context_lost', lambda: told.append('engine')
        )
        bound = _AnyContext()
        context_module.Context.bindContextResources(bound, handle=1)
        assert bound._ownContext == 1
        context_module.Context.releaseContextResources(bound, handle=1)
        assert told == ['engine']
