"""Asking the engine for a context type to build a window class on."""

import pytest

from OpenGLContext import plugins, testingcontext, windowsystem
from OpenGLContext.context import Context
from OpenGLContext.glfwcontext import GLFWContext


def test_asking_for_nothing_in_particular_answers_context():
    """The window system is then chosen as the context is built."""
    assert testingcontext.getInteractive() is Context


def test_the_backend_installed_here_is_returned():
    """GLFW is the engine's own test window system and is always installed."""
    assert testingcontext.getInteractive('glfw') is GLFWContext


def test_a_backend_nobody_registered_says_so():
    """The name is usually a typo or a window system from a package not
    installed."""
    with pytest.raises(RuntimeError, match='no-such-toolkit'):
        testingcontext.getInteractive('no-such-toolkit')


def test_the_refusal_is_the_window_system_registrys_own():
    with pytest.raises(windowsystem.WindowSystemUnavailable):
        testingcontext.getInteractive('no-such-toolkit')


def test_a_backend_that_will_not_import_says_which_one():
    """Registered but unusable -- the toolkit it needs is not installed.

    Returning None here is what gives the caller a metaclass conflict several
    frames later, naming neither the window system nor the missing package.
    """
    windowsystem.registered()           # entry points first, so ours is last
    plugins.WindowSystem('brokenbackend', 'no_such_module_at_all.NotAWindowSystem')
    try:
        with pytest.raises(RuntimeError, match='brokenbackend') as caught:
            testingcontext.getInteractive('brokenbackend')
        assert 'will not import' in str(caught.value)
    finally:
        plugins.WindowSystem.registry[:] = [
            plugin for plugin in plugins.WindowSystem.registry
            if plugin.name != 'brokenbackend'
        ]


def test_the_error_names_the_backends_that_are_registered():
    """So that a reader can see what to ask for instead."""
    with pytest.raises(RuntimeError, match='glfw'):
        testingcontext.getInteractive('no-such-toolkit')
