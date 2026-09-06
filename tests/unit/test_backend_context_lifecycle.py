"""Every backend says when it takes a context and when it lets one go.

Two things listen.  The engine's own caches hold GL names keyed by the context
handle, and PyOpenGL's C dispatch layer holds a table of resolved entry-point
addresses keyed by the same handle.  Both are only trustworthy while something
tells them a context has gone, because a driver hands the same handle out again
for the next context -- and then a cache answers the new one with the dead one's
names, and PyOpenGL calls the dead one's function pointers.

A backend that does not announce leaves both wrong, occasionally, nowhere near
the code that caused it.
"""

import ast
import os

import pytest

from OpenGLContext import context as context_module
from OpenGLContext import contextresources

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.dirname(os.path.dirname(HERE))

#: Every backend that owns a window, and the module it lives in.  A backend
#: missing from here is a backend nothing holds to the contract.
BACKENDS = (
    ('glfw', 'OpenGLContext/glfwcontext.py'),
    ('glut', 'OpenGLContext/glutcontext.py'),
    ('pygame', 'OpenGLContext/pygamecontext.py'),
    ('tk', 'OpenGLContext/tkcontext.py'),
    ('wx', 'OpenGLContext/wxcontext.py'),
    ('egl', 'OpenGLContext/eglcontext.py'),
)


def _calls_in(path):
    """Every attribute call written in a module, as dotted names."""
    source = open(os.path.join(PACKAGE, path), encoding='utf-8').read()
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            parts = []
            target = node.func
            while isinstance(target, ast.Attribute):
                parts.append(target.attr)
                target = target.value
            if isinstance(target, ast.Name):
                parts.append(target.id)
                names.add('.'.join(reversed(parts)))
    return names


def _calls_within(path, function, depth=3):
    """Every attribute call one function of a module reaches.

    Follows ``self.something()`` into that method, so a backend that calls its
    named teardown -- ``releaseWindow`` -- rather than writing the release out
    counts as making the call.
    """
    source = open(os.path.join(PACKAGE, path), encoding='utf-8').read()
    tree = ast.parse(source)
    bodies = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            bodies.setdefault(node.name, node)

    def within(name, remaining):
        node = bodies.get(name)
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
                    names |= within(parts[0], remaining - 1)
        return names

    return within(function, depth)


class TestEveryBackendAnnouncesTheEndOfAContext:
    @pytest.mark.parametrize('name,path', BACKENDS, ids=[b[0] for b in BACKENDS])
    def test_it_releases_the_context_it_owned(self, name, path):
        assert 'self.releaseContextResources' in _calls_in(path), (
            '%s never says its context is going, so every cache keyed on the '
            'handle keeps answering for it' % (name,)
        )

    @pytest.mark.parametrize('name,path', BACKENDS, ids=[b[0] for b in BACKENDS])
    def test_quitting_releases_before_the_process_ends(self, name, path):
        """``Context.OnQuit`` ends the process with ``os._exit``.

        Nothing after it runs -- no ``finally``, no ``atexit`` hook -- so a
        backend that leaves the release to the end of its main loop does not
        release at all on the path a user actually takes, which is pressing
        Escape or closing the window. The release has to happen in ``OnQuit``,
        before the base class is called.
        """
        assert 'self.releaseContextResources' in _calls_within(path, 'OnQuit'), (
            "%s releases its context only after its loop, and quitting never "
            "reaches there" % (name,)
        )


class TestQuittingReallyReleases:
    """The static contract above, run rather than read.

    Through GLFW, which is the backend this container can open a window on;
    the shape is the same on every backend, and the static check is what holds
    the ones a given machine cannot run.
    """

    def _quit(self, monkeypatch):
        """Build a window, quit it, and answer what the quit told the caches"""
        from OpenGLContext.testing.glcontext import gl_available

        if not gl_available():
            pytest.skip('no GL target available')
        from OpenGLContext import glfwinteractivecontext

        told = []
        monkeypatch.setattr(contextresources, 'context_lost',
                            lambda: told.append('engine'))
        # The base class ends the process; what is under test is what happens
        # before it does.
        monkeypatch.setattr(context_module.Context, 'OnQuit',
                            lambda self, event=None: told.append('exited'))
        monkeypatch.setenv('OPENGLCONTEXT_HIDDEN', '1')
        made = glfwinteractivecontext.GLFWInteractiveContext(size=(64, 64))
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


class _AnyContext:
    """Any object the contract is called against; it records its own handle."""


class TestTheContractIsStatedOnce:
    """A new backend should inherit the contract rather than have to know it."""

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
        from OpenGL import _dispatch

        told = []
        monkeypatch.setattr(contextresources, 'context_lost', lambda: None)
        monkeypatch.setattr(
            _dispatch, 'forget_context', lambda handle: told.append(handle)
        )
        context_module.Context.releaseContextResources(_AnyContext(), handle=0xC0FFEE)
        assert told == [0xC0FFEE]

    def test_binding_tells_pyopengl(self, monkeypatch):
        from OpenGL import _dispatch

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

    def test_neither_half_raises_where_pyopengl_has_no_c_layer(self, monkeypatch):
        from OpenGL import _dispatch

        monkeypatch.setattr(_dispatch, 'ACTIVE', False)
        context_module.Context.bindContextResources(_AnyContext(), handle=1)
        context_module.Context.releaseContextResources(_AnyContext(), handle=1)
