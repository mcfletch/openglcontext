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

The plugin also supplies the ``performance`` marker. A test that measures how
*fast* something draws is asking about the renderer as much as about the code,
so on a CPU rasteriser -- a CI runner with no GPU, say -- those are skipped
instead of held to a speed no CPU reaches::

    @pytest.mark.performance
    def test_instancing_is_faster(gl_context):
        ...

``OPENGLCONTEXT_PERFORMANCE_TESTS=1`` runs them anyway, and ``=0`` skips them
whatever the renderer, which is what a shared or throttled machine wants.

The window machinery itself is in :mod:`OpenGLContext.testing.glcontext` and has
no pytest in it, so a test runner that is not pytest can use it too.
"""
from __future__ import annotations

import contextlib
import os
from typing import Any, Callable, Iterator, Mapping

import pytest

from OpenGLContext.testing.glcontext import (
    GLDescription,
    GLUnavailable,
    describe_gl,
    hidden_window,
)

#: Runs the ``performance`` tests, or refuses to, whatever the renderer is.
PERFORMANCE_TESTS = 'OPENGLCONTEXT_PERFORMANCE_TESTS'

_TRUE = ('1', 'true', 'yes', 'on')
_FALSE = ('0', 'false', 'no', 'off')


def performance_skip_reason(description: GLDescription | None,
                            env: Mapping[str, str] | None = None) -> str | None:
    """Why ``performance`` tests are passed over here, or ``None`` to run them.

    The renderer decides unless :data:`PERFORMANCE_TESTS` overrules it. A value
    that is neither a yes nor a no is reported rather than swallowed: this
    variable is how a CI run pins the behaviour, and a typo that quietly
    reversed the pin would make that run's result a lie. An unset variable and
    an empty one agree, since that is what an unexported shell variable expands
    to.
    """
    env = os.environ if env is None else env
    setting = env.get(PERFORMANCE_TESTS, '').strip().lower()
    if setting:
        if setting in _TRUE:
            return None
        if setting not in _FALSE:
            raise ValueError(
                '%s=%r is neither a yes nor a no; use one of %s or %s'
                % (PERFORMANCE_TESTS, env[PERFORMANCE_TESTS],
                   ', '.join(_TRUE), ', '.join(_FALSE)))
        return '%s asks for no performance tests on this run' % (PERFORMANCE_TESTS,)
    if description is None:
        return 'there is no GL here to measure'
    if description.software:
        return ('%s rasterises on the CPU, so what it takes to draw a frame is '
                'not what this measures' % (description.renderer,))
    return None


def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        'markers',
        'performance: asserts how fast something draws, so it needs a GPU to '
        'draw it; skipped on a CPU rasteriser unless %s says otherwise'
        % (PERFORMANCE_TESTS,))


def pytest_collection_modifyitems(config: Any, items: list) -> None:
    """Skip the ``performance`` tests where the renderer cannot answer them.

    The reason is worked out once, and only where something is marked: a suite
    with no performance tests in it should not open a probe window to discover
    that it has none.
    """
    marked = [item for item in items if item.get_closest_marker('performance')]
    if not marked:
        return
    reason = performance_skip_reason(describe_gl())
    if reason is None:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in marked:
        item.add_marker(skip)


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
