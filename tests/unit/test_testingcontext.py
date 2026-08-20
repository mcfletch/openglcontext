"""Asking the engine for a context type to build a window class on."""

import pytest

from OpenGLContext import plugins, testingcontext


def test_the_backend_installed_here_is_returned():
    """GLFW is the engine's own test backend and is always installed."""
    assert testingcontext.getInteractive('glfw') is not None


def test_a_backend_nobody_registered_says_so():
    """The name is usually a typo or a backend from a package not installed."""
    with pytest.raises(RuntimeError, match='no-such-toolkit'):
        testingcontext.getInteractive('no-such-toolkit')


def test_a_backend_that_will_not_import_says_which_one():
    """Registered but unusable -- the toolkit it needs is not installed.

    Returning None here is what gives the caller a metaclass conflict several
    frames later, naming neither the backend nor the missing package.
    """
    plugins.InteractiveContext('brokenbackend',
                               'no_such_module_at_all.NotAContext')
    try:
        with pytest.raises(RuntimeError, match='brokenbackend'):
            testingcontext.getInteractive('brokenbackend')
    finally:
        plugins.InteractiveContext.registry[:] = [
            plugin for plugin in plugins.InteractiveContext.registry
            if plugin.name != 'brokenbackend'
        ]


def test_the_error_names_the_backends_that_are_registered():
    """So that a reader can see what to ask for instead."""
    with pytest.raises(RuntimeError, match='glfw'):
        testingcontext.getInteractive('no-such-toolkit')
