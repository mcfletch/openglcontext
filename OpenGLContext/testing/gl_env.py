"""Which GL a test run gets, and what a child process is told about it.

Two kinds of environment variable meet in a GL test suite, and keeping them
apart is the whole of this module:

**Configuration** -- ``OPENGLCONTEXT_*`` and ``PYOPENGL_*`` -- says which kind
of context a program is given: the profile, the backend, the renderer, the
shadows, the PyOpenGL platform. It belongs to one test, or to one run, and a
test that leaves it behind has changed what every later test renders.

**Infrastructure** -- the display, the driver's own variables, the interpreter's
paths -- says which machine the program is running on. It belongs to the
machine and every child needs all of it.

So a child is built by :func:`gl_subprocess_env` from the infrastructure plus
exactly the configuration its caller names, and :func:`configuration` is what a
guard or a fixture uses to see what a test changed. The rule is a prefix rather
than a list of names: a list has to be kept in step with the variables, and the
one that was not is what let ``PYOPENGL_PLATFORM=egl`` -- set at import by ten
test modules on their own account -- reach every script the suite launched, on
a platform with no EGL, where it made every entry point undefined.

:func:`settle_gl_platform` is why no test module needs to set that one: it is
answered once, from the OS, before anything imports ``OpenGL``.
"""

from __future__ import annotations

import os
import sys
from typing import Mapping

from OpenGLContext import renderoptions

__all__ = [
    'CONFIGURATION_PREFIXES', 'GL_BACKENDS', 'GL_BACKEND_VARIABLE',
    'GL_PLATFORM_BY_OS', 'GL_PLATFORM_VARIABLE', 'backend_available',
    'configuration', 'gl_platform_for', 'gl_subprocess_env', 'import_unconfigured',
    'is_configuration', 'settle_gl_backend', 'settle_gl_platform',
]

#: The prefixes that mark a variable as configuration rather than as part of
#: the machine.  The engine's, rather than a second answer kept here: a test
#: suite that disagreed with the engine about which variables decide a render
#: would build children the engine's own tools would not.
CONFIGURATION_PREFIXES = renderoptions.CONFIGURATION_PREFIXES

#: The variable naming which of PyOpenGL's platform modules is loaded.
GL_PLATFORM_VARIABLE = 'PYOPENGL_PLATFORM'

#: Which platform module a test run asks for, by the prefix ``sys.platform``
#: takes on that OS.  Only Linux has an entry, and deliberately: EGL renders
#: with no X display, which is what a headless runner has and what the Wayland
#: sessions here need, and PyOpenGL would otherwise choose GLX.  Everywhere
#: else PyOpenGL's own default is the only right answer -- WGL on Windows, the
#: OpenGL framework on macOS -- so nothing is named and nothing is overridden.
GL_PLATFORM_BY_OS = (
    ('linux', 'egl'),
)

#: The variable naming which windowing backend builds a context.
GL_BACKEND_VARIABLE = 'OPENGLCONTEXT_BACKEND'

#: The backends a test run will take, best first.  GLFW leads because it is the
#: one that opens a window without mapping it, which is what a suite of several
#: hundred rendering tests needs from a toolkit; the rest follow so a machine
#: without it still has a suite to run.  Left unnamed, the engine takes the
#: first backend that happens to be registered, so two machines with different
#: packages installed run different code.
GL_BACKENDS = ('glfw', 'pygame', 'wx', 'glut')

#: The module each backend needs, where it is not the backend's own name.
_BACKEND_MODULES = {'glut': 'OpenGL.GLUT'}

#: Variables that are not configuration but that a GL child still needs by
#: name, since they belong to no common prefix.
_MACHINE_NAMES = frozenset((
    'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'SHELL', 'TERM',
    'TMPDIR', 'TEMP', 'TMP', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT',
    'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'NUMBER_OF_PROCESSORS',
    'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY',
    'LD_LIBRARY_PATH', 'LD_PRELOAD', 'DYLD_LIBRARY_PATH',
    'PYTHONPATH', 'PYTHONHASHSEED', 'PYTHONUNBUFFERED', 'VIRTUAL_ENV',
))

#: And the prefixes of the same, which is most of what a graphics driver reads.
_MACHINE_PREFIXES = (
    'XDG_', '__GLX_', '__EGL_', '__NV', '__VK', 'NVIDIA_', 'NV_',
    'LIBGL_', 'MESA_', 'VK_', 'DRI', 'GALLIUM_', 'EGL_', 'GBM_',
)


def is_configuration(name: str) -> bool:
    """Whether ``name`` says what kind of context a program gets.

    As against what machine it is running on.  A configuration variable is one
    test's to set and nobody else's to inherit.  The engine's own rule --
    :func:`OpenGLContext.renderoptions.is_render_configuration` -- so that what
    a test's child may inherit and what the engine's tools drop are one
    question with one answer.
    """
    return renderoptions.is_render_configuration(name)


def configuration(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Every configuration variable in ``environ``, and what it is set to.

    What a guard compares before and after, and what a fixture puts back.
    """
    environ = os.environ if environ is None else environ
    return {name: value for name, value in environ.items()
            if is_configuration(name)}


def gl_platform_for(platform: str | None = None) -> str | None:
    """The PyOpenGL platform a test run asks for on this OS, or ``None``.

    ``None`` means "leave it to PyOpenGL", which is the right answer on every
    OS whose windowing API PyOpenGL already picks correctly.  Naming one there
    would name the wrong one: the platform module decides which library
    ``glViewport`` is looked for in, so a Linux answer given to Windows leaves
    every entry point undefined and the first GL call raising
    ``NullFunctionError`` -- with nothing in it to say a variable was to blame.

    ``platform`` defaults to :data:`sys.platform`; pass one to ask about
    another, which is what lets the map be checked anywhere.
    """
    if platform is None:
        platform = sys.platform
    for prefix, name in GL_PLATFORM_BY_OS:
        if platform.startswith(prefix):
            return name
    return None


def settle_gl_platform(environ: dict | None = None,
                       platform: str | None = None) -> str | None:
    """Name the PyOpenGL platform for this run, and answer what it is.

    Called once, before anything imports ``OpenGL``: the platform module is
    chosen at import and cannot be changed afterwards.  A run that named one
    already means it -- ``PYOPENGL_PLATFORM=osmesa`` is how a machine with
    neither a display nor EGL renders at all -- so this only fills a gap.

    An OS with no answer is left unset rather than set to the empty string,
    which PyOpenGL would read as a platform named badly rather than as one not
    named.
    """
    environ = os.environ if environ is None else environ
    already = environ.get(GL_PLATFORM_VARIABLE)
    if already:
        return already
    wanted = gl_platform_for(platform)
    if wanted is not None:
        environ[GL_PLATFORM_VARIABLE] = wanted
    return wanted


def backend_available(name: str) -> bool:
    """Whether ``name``'s toolkit will import here.

    Asked rather than assumed: a backend registered but whose package is not
    installed fails at context creation, several frames from the choice.
    """
    import importlib.util

    module = _BACKEND_MODULES.get(name, name)
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):          # a namespace package, or worse
        return False


def settle_gl_backend(environ: dict | None = None,
                      available=None) -> str | None:
    """Name the windowing backend for this run, and answer what it is.

    The first of :data:`GL_BACKENDS` whose toolkit imports.  A run that named
    one already means it -- that is how a case about a particular backend asks
    for it -- so this only fills a gap, and where none will import it names
    nothing: the engine's own error says which backend was wanted and which
    package to install, and a choice made here would hide it.

    ``available`` answers whether a backend can be used, for a caller asking
    about a machine other than this one.
    """
    environ = os.environ if environ is None else environ
    already = environ.get(GL_BACKEND_VARIABLE)
    if already:
        return already
    if available is None:
        available = backend_available
    for name in GL_BACKENDS:
        if available(name):
            environ[GL_BACKEND_VARIABLE] = name
            return name
    return None


#: What this run settled on, once: the platform and backend chosen from the
#: machine, plus whatever the project's ``conftest.py`` set for the session.
#: Told to :func:`settle_run` when there is nothing left to import, which is
#: the last moment it can be distinguished from what a single test sets.
_RUN: dict[str, str] = {}


def settle_run(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Remember the configuration this run holds to, and answer it."""
    _RUN.clear()
    _RUN.update(configuration(environ))
    return dict(_RUN)


def run_configuration() -> dict[str, str]:
    """The configuration this run settled on; empty until :func:`settle_run`.

    What a child process inherits and what a test's own settings are put back
    to. Empty is the right answer before a run has settled: nothing has been
    chosen yet, so nothing is owed to a child.
    """
    return dict(_RUN)


#: What the test now running declared it is about, if it declared anything.
#: Kept apart from the run's own so that a child gets the two of them and
#: nothing else -- in particular, nothing a test set for its own in-process use
#: and did not mean to pass on.
_ASKED: dict[str, str] = {}


def asking(asked: Mapping[str, str] | None) -> dict[str, str]:
    """Say what the test now running is about, and answer what was there before.

    Called by :mod:`OpenGLContext.testing.plugin` around each test; a caller
    doing its own bookkeeping passes the previous value back when it is done.
    """
    before = dict(_ASKED)
    _ASKED.clear()
    _ASKED.update(asked or {})
    return before


def asked_configuration() -> dict[str, str]:
    """What the test now running declared it is about; empty if nothing."""
    return dict(_ASKED)


def import_unconfigured(name: str):
    """Import ``name``, and leave the run's configuration as it was.

    A program settles the renderer as it is imported, which is right for a
    program: it is about to draw something. A test that imports one to call a
    function of it is not, and taking that settling would hand the program's
    choice to every test collected afterwards and to every child the suite
    launches.

    So the module is imported and the configuration put back. What the module
    itself sees while it runs is unchanged, which is what lets it be imported
    at all.
    """
    import importlib

    before = configuration()
    try:
        return importlib.import_module(name)
    finally:
        for found in [n for n in os.environ if is_configuration(n)]:
            if found not in before:
                del os.environ[found]
        os.environ.update(before)


def gl_subprocess_env(environ: Mapping[str, str] | None = None,
                      **overrides: object) -> dict[str, str]:
    """The environment for a GL child: this machine, this run, and no more.

    Four things reach the child and nothing else does: the machine it runs on,
    the configuration the *run* settled (:func:`run_configuration` -- the
    platform and backend chosen here, and whatever the session was set up
    with), the kind of context the test now running declared it is about
    (:func:`asked_configuration`), and the ``overrides`` this caller names.

    Anything else a test happened to put in the environment does not, which is
    the whole point: it is one test's answer to a question this child was not
    asked, and it is how a script came to be launched with a platform module
    that does not exist on the machine it ran on.

    ``environ`` defaults to this process's own; values are stringified.
    """
    environ = os.environ if environ is None else environ
    child = {name: value for name, value in environ.items()
             if not is_configuration(name)
             and (name in _MACHINE_NAMES or name.startswith(_MACHINE_PREFIXES))}
    child.update(run_configuration())
    child.update(asked_configuration())
    child.update({name: str(value) for name, value in overrides.items()})
    return child
