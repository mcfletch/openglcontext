"""Pytest fixtures for tests that render, for this project and for yours.

A game or an application built on OpenGLContext has the same testing problem the
engine has: some of what it draws can only be checked by drawing it, and that
needs a current GL context in the test process. Turn the fixtures on from the
project's ``conftest.py``::

    pytest_plugins = ['OpenGLContext.testing.plugin']

and a test can then ask for a window::

    def test_the_glow_spreads(gl_context):
        ...                                   # gl_context is current

    @pytest.fixture
    def gl_context(gl_window):                # a bigger one, or another profile
        return gl_window('bloom', size=(96, 96))

:func:`gl_context` is a hidden core-profile 3.3 window; :func:`gl_context_compat`
is the same in the compatibility profile, for the fixed-function render arms;
:func:`gl_window` is the factory both are built on, for a test that wants a
different size, profile or hint. All three **skip** rather than fail where no GL
target exists, which is what a headless runner without an offscreen platform
should get -- see :mod:`OpenGLContext.testing.display` for what counts as one.

The window machinery itself is in :mod:`OpenGLContext.testing.glcontext` and has
no pytest in it, so a test runner that is not pytest can use it too.
"""
from __future__ import annotations

import contextlib
from typing import Any, Callable, Iterator

import pytest

from OpenGLContext.testing.glcontext import GLUnavailable, hidden_window


@pytest.fixture
def gl_window() -> Iterator[Callable[..., Any]]:
    """Make hidden GL windows; every one is destroyed when the test ends.

    The factory takes the arguments of
    :func:`~OpenGLContext.testing.glcontext.hidden_window` and returns the GLFW
    window handle, with the context current. Asking for a second window makes a
    second one and leaves *it* current, which is how a test drives two contexts
    (a resource cached against the first must not be handed to the second).
    """
    with contextlib.ExitStack() as windows:
        def make(title: str = 'OpenGLContext test', **named: Any) -> Any:
            try:
                return windows.enter_context(hidden_window(title, **named))
            except GLUnavailable as err:
                pytest.skip(str(err))
        yield make


@pytest.fixture
def gl_context(gl_window: Callable[..., Any]) -> Any:
    """A hidden core-profile 3.3 window, current for the test."""
    return gl_window('gl_context')


@pytest.fixture
def gl_context_compat(gl_window: Callable[..., Any]) -> Any:
    """A hidden compatibility-profile 3.3 window, current for the test.

    Compatibility *and* 3.3, so the fixed-function state the legacy render arms
    touch is valid while GLSL 330 still compiles. Skips where the driver
    answers with a core-only context, since nothing the fixture exists for
    would work in one.
    """
    return gl_window('gl_context_compat', profile='compatibility')
