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

**Which context the run gets is settled here**, before anything imports
``OpenGL``: the PyOpenGL platform from the OS, the windowing backend from what
will actually import.  So no test module has to set either, and none may -- a
module-scope ``os.environ`` write happens while pytest is still collecting, and
becomes the answer for the whole session and for every child process it
launches.  The plugin puts the ``OPENGLCONTEXT_*`` and ``PYOPENGL_*``
configuration back to the run's after collection and after every test.

A test that is about **one kind** of context and no other says so, and is
skipped where that kind cannot be had rather than failing on a machine that was
never going to serve it::

    @pytest.mark.gl_context(profile='compatibility')
    def test_the_old_pipeline_still_lights(gl_context_compat):
        ...

What the marker names is set for the test, reaches any child process it
launches, and is put back afterwards.  See :mod:`OpenGLContext.testing.gl_env`
for the rule that tells configuration from the machine, and ``docs/testing.html``
for the whole of it.

The window machinery itself is in :mod:`OpenGLContext.testing.glcontext` and has
no pytest in it, so a test runner that is not pytest can use it too.
"""
from __future__ import annotations

import contextlib
import os
from typing import Any, Callable, Iterator, Mapping

import pytest

from OpenGLContext.testing import gl_env

# Before anything here imports OpenGL, because the platform module is chosen at
# import and cannot be changed afterwards.  This is why no test module needs to
# name it, and why none may: ten of them once did, each on its own account, and
# the value reached every child the suite launched.
gl_env.settle_gl_platform()
gl_env.settle_gl_backend()

from OpenGLContext.testing.glcontext import (  # noqa: E402 -- after the settling
    GLDescription,
    GLUnavailable,
    describe_gl,
    hidden_window,
    profile_unavailable,
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


#: How a ``gl_context`` marker's keywords are spelled in the environment. A
#: marker says ``profile='compatibility'``; the engine reads
#: ``OPENGLCONTEXT_PROFILE``. Any name already in full is passed through, so a
#: setting with no short spelling still has one place to be written.
_CONTEXT_PREFIX = 'OPENGLCONTEXT_'


def context_asked_for(marker: Any) -> dict[str, str]:
    """The configuration a ``gl_context`` marker names, ready for the environment.

    ``profile='core'`` becomes ``OPENGLCONTEXT_PROFILE='core'``; a name given
    in full is left alone. Values are stringified, since that is what an
    environment holds.
    """
    if marker is None:
        return {}
    asked = {}
    for name, value in marker.kwargs.items():
        if not name.startswith(_CONTEXT_PREFIX):
            name = _CONTEXT_PREFIX + name.upper()
        asked[name] = str(value)
    return asked


def context_skip_reason(asked: Mapping[str, str],
                        available: Callable[[str], bool] | None = None,
                        profile_available: Callable[[str], str | None] | None = None,
                        ) -> str | None:
    """Why this machine cannot serve the context a test asked for, or ``None``.

    Only what was asked for is checked, and only where something was: a test
    that wants *a* context takes whatever the run settled on, and asking the
    driver on its behalf would open a probe window to answer a question it did
    not put.
    """
    backend = asked.get(gl_env.GL_BACKEND_VARIABLE)
    if backend:
        if available is None:
            available = gl_env.backend_available
        if not available(backend):
            return ('this test is about the %s backend and its toolkit is not '
                    'installed here' % (backend,))
    profile = asked.get('OPENGLCONTEXT_PROFILE')
    if profile:
        if profile_available is None:
            profile_available = profile_unavailable
        refused = profile_available(profile)
        if refused:
            return refused
    return None


def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        'markers',
        'performance: asserts how fast something draws, so it needs a GPU to '
        'draw it; skipped on a CPU rasteriser unless %s says otherwise'
        % (PERFORMANCE_TESTS,))
    config.addinivalue_line(
        'markers',
        'gl_context(profile=..., backend=..., **options): this test is about '
        'one kind of context and no other. The options are set for the test '
        'and put back afterwards, and it is skipped where this machine cannot '
        'give that kind. A test with no marker takes whatever the run settled '
        'on -- see OpenGLContext.testing.gl_env.')


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


#: What collection changed, if anything, so a test can say which module did it.
_COLLECTION_CHANGED: dict[str, str] = {}


def collection_changed() -> dict[str, str]:
    """Configuration that appeared while the test modules were being imported."""
    return dict(_COLLECTION_CHANGED)


def pytest_collection(session: Any) -> None:
    """Settle the run's configuration, before a single test module is imported.

    *Before*, because importing is when the damage is done and after it there
    is no way to tell a deliberate session setting from something a module did
    on its own account. A project's ``conftest.py`` has already run by now,
    which is right: configuring the session is what a conftest is for.
    """
    gl_env.settle_run()


def pytest_collection_finish(session: Any) -> None:
    """Put the configuration back to the run's, and record what moved it.

    A test module must not configure the renderer as it is imported, and
    ``tests/unit/test_no_configuration_at_import.py`` holds this project's own
    to that. What no reading of a test module can catch is a module that
    *imports a program* -- ``OpenGLContext.bin.terrain_view`` settles the
    renderer as it loads, reasonably, because it is about to draw one. Left
    standing, that program's choice would be the run's, and every child process
    launched afterwards would render under it.
    """
    _COLLECTION_CHANGED.clear()
    settled = gl_env.run_configuration()
    for name, value in gl_env.configuration().items():
        if settled.get(name) != value:
            _COLLECTION_CHANGED[name] = value
    _restore(settled)


def _restore(settled: Mapping[str, str]) -> None:
    """Make the configuration in the environment ``settled`` exactly."""
    for name in [n for n in os.environ if gl_env.is_configuration(n)]:
        if name not in settled:
            del os.environ[name]
    os.environ.update(settled)


@pytest.fixture(autouse=True)
def gl_configuration(request: Any) -> Iterator[None]:
    """Set what this test asked for, and put the run's own back afterwards.

    Every test, whether it renders or not: a test that changes the
    configuration without restoring it changes what every later test draws, and
    the ones that draw in a child process inherit it silently. One fixture for
    the whole session rather than one guard per module, so a module that
    forgets is not a hole.
    """
    asked = context_asked_for(request.node.get_closest_marker('gl_context'))
    if asked:
        reason = context_skip_reason(asked)
        if reason:
            pytest.skip(reason)
        os.environ.update(asked)
    before = gl_env.asking(asked)
    settled = gl_env.run_configuration()
    try:
        yield
    finally:
        gl_env.asking(before)
        _restore(settled)


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
