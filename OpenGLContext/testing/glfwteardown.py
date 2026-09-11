"""Whether this GLFW stack can hand a context back, and what to do where it cannot.

Some driver stacks fault while freeing an EGL context, with no frame of ours in
the call.  Two have been seen, both under GLFW's Wayland backend, which reaches
the driver through EGL:

**NVIDIA** -- roughly **one teardown in ten** dies with SIGSEGV inside
``libnvidia-eglcore``, reached through ``eglDestroyContext``.  PyOpenGL's
``tests/README.md`` and ``plans/C-DISPATCH.md`` record the AddressSanitizer
stack; Mesa and the macOS backends do not show it.  Its rarity is what
:data:`CYCLES` is sized against.

**Mesa** -- an abort rather than a segmentation fault::

    free(): invalid size   -> abort
      __libc_free
      libgallium                        <- invalid free
      libEGL_mesa.so.0
      destroyContextEGL
      _glfwDestroyWindowWayland
      glfwDestroyWindow                 (and the same path under glfwTerminate)

A fault at teardown lands in whatever runs next -- often a later test's
``glfw.poll_events`` or its own teardown -- long after the assertions that
"caused" it have passed, which is why it reads as flaky pollution between tests
rather than as one broken test.  A SIGABRT cannot be caught, so one teardown
takes a whole run down.

A second free of a context something already released looks the same from
inside the allocator, so a trace like the one above is worth reading twice: it
says where the bad free landed, not who made it.

A test process has no need to hand these back at all: ``glfw.init()`` returns
immediately when the library is already initialised, and the OS reclaims every
context and window when the process exits.  So where the stack faults, both
teardown calls are stood down for the session and the windows a run leaks cost
a little memory until it ends and nothing more.

**Which stack this is, is asked rather than assumed.**  :func:`teardown_faults`
builds a window in a child process and frees it; if the child aborts, this
machine is one of them.  Where it does not, the engine's own release path --
:meth:`OpenGLContext.glfwcontext.GLFWContext.close` and the fixtures in
:mod:`OpenGLContext.testing.glcontext` -- runs as it does in a user's
application, and so stays under test.  That is what stops the workaround
outliving the driver defect: it retires itself on the first machine that no
longer needs it.

``OPENGLCONTEXT_GLFW_TEARDOWN`` pins the answer for a run whose stack is
already known -- ``native`` to release contexts, ``neutralised`` to stand the
release down, ``auto`` (the default) to ask.  Pinning also skips the probe,
which is what a CI job on a settled image wants.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Callable, Mapping, Optional, Sequence

#: Pins whether contexts are released, for a run that already knows.
TEARDOWN_VARIABLE = 'OPENGLCONTEXT_GLFW_TEARDOWN'

#: What that variable may say. ``auto`` asks this machine.
TEARDOWNS = ('auto', 'native', 'neutralised')

#: The probe's exit code for "there is no GL here to ask about".  Distinct from
#: every other ending, because a machine with no driver has no windows to
#: protect and must not be read as a faulting one.
CANNOT_TELL = 3

#: How many build-and-free cycles the probe runs.
#:
#: The fault this exists to catch is **intermittent**: on an NVIDIA driver
#: roughly one teardown in ten dies, so a probe of a handful of cycles answers
#: "sound" on a faulting stack most of the time -- and a run waved through that
#: way crashes exactly as it did before.  A hundred puts the chance of missing a
#: one-in-ten fault at three in a hundred thousand, and costs almost nothing:
#: starting the child and opening the first window is the whole expense, and the
#: probe takes about a third of a second whether it runs four cycles or a
#: hundred.
#:
#: :data:`FAULT_RATE` is the rate this is chosen against;
#: ``tests/unit/test_glfw_teardown.py`` holds the two together.
CYCLES = 100

#: The rarest fault the probe is meant to catch, as a fraction of teardowns --
#: the NVIDIA EGL/Wayland one recorded in PyOpenGL's ``tests/README.md``.
FAULT_RATE = 0.1


def setting(environ: Optional[Mapping[str, str]] = None) -> str:
    """What :data:`TEARDOWN_VARIABLE` says, as one of :data:`TEARDOWNS`.

    An unset variable and an empty one mean the same thing, because that is
    what an unexported shell variable expands to.  A value that is neither is
    reported rather than swallowed: this setting is how a run pins the
    behaviour on a known stack, and a typo that quietly reversed the pin would
    make that run's result a lie.
    """
    if environ is None:
        environ = os.environ
    written = (environ.get(TEARDOWN_VARIABLE, '') or '').strip().lower()
    if not written:
        return 'auto'
    if written not in TEARDOWNS:
        raise ValueError('%s=%r is not recognised (expected one of %s)'
                         % (TEARDOWN_VARIABLE, written, ', '.join(TEARDOWNS)))
    return written


def probe_command() -> Sequence[str]:
    """The child process that finds out whether freeing a context aborts."""
    return (sys.executable, '-m', __name__)


def faults_from(returncode: int) -> bool:
    """Whether a probe that ended this way says the stack faults.

    Zero is a child that built and freed its contexts and lived.
    :data:`CANNOT_TELL` is a child that found no GL, which is not an answer
    about teardown and must not be read as one.  Everything else -- a signal,
    or an exception on the way out -- is the fault this module is about.
    """
    if returncode == 0:
        return False
    if returncode == CANNOT_TELL:
        return False
    return True


#: The answer for this process, so the child runs once rather than per caller.
_FAULTS: Optional[bool] = None


def teardown_faults(run: Optional[Callable[[Sequence[str]], int]] = None) -> bool:
    """Whether freeing a GLFW context aborts on this machine.

    Asked once per process and remembered: the answer is a property of the
    driver, which does not change while the process lives.  ``run`` takes the
    command and answers its exit status; it exists so the reading of that
    status can be checked without a driver that aborts.
    """
    global _FAULTS
    if _FAULTS is not None:
        return _FAULTS
    if run is None:
        run = _run
    try:
        returncode = run(probe_command())
    except OSError:
        # A machine that will not start a child process will not open a window
        # on this backend either, so there is nothing to stand down.
        _FAULTS = False
        return _FAULTS
    _FAULTS = faults_from(returncode)
    return _FAULTS


def _run(command: Sequence[str]) -> int:
    """Run the probe, discarding what it says, and answer how it ended."""
    try:
        finished = subprocess.run(list(command), capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:     # pragma: no cover - needs a hung driver
        # A probe that never came back has told us nothing good about this
        # stack, and standing the teardown down is the side that costs a run
        # nothing but memory.
        return 1
    return finished.returncode


def forget() -> None:
    """Ask the machine again next time.  For the cases that test this module."""
    global _FAULTS
    _FAULTS = None


def _NOTHING_AT_ALL() -> None:
    """Stands in for ``glfw.terminate`` where releasing a context aborts."""


def _NOTHING_TO_DO(window: Any) -> None:
    """Stands in for ``glfw.destroy_window`` where releasing a context aborts."""


def neutralise(glfw: Any) -> None:
    """Stand both teardown calls down for the rest of the process."""
    glfw.terminate = _NOTHING_AT_ALL
    glfw.destroy_window = _NOTHING_TO_DO


def settle(glfw: Any, asked: Optional[str] = None) -> str:
    """Decide this session's teardown and apply it; answer what was decided.

    ``'unavailable'`` where there is no ``glfw`` to decide about.  ``glfw`` is
    passed in rather than imported here so that a caller who has not needed the
    windowing library does not load one to find that out.
    """
    if glfw is None:
        return 'unavailable'
    if asked is None:
        asked = setting()
    decided = teardown_choice(asked, teardown_faults)
    if decided == 'neutralised':
        neutralise(glfw)
    return decided


def teardown_choice(asked: str, faults: Callable[[], bool]) -> str:
    """``'native'`` or ``'neutralised'``, from the setting and the machine.

    A setting that has decided is not second-guessed, and the machine is not
    asked -- which is what makes pinning it free.
    """
    if asked != 'auto':
        return asked
    return 'neutralised' if faults() else 'native'


def settle_for_session() -> str:
    """What a test runner calls once, before anything opens a window.

    Answers what was decided, for a runner that wants to report it.
    """
    try:
        import glfw
    except Exception:                     # pragma: no cover - needs no glfw
        return 'unavailable'
    return settle(glfw)


def _probe() -> int:
    """Build a GL context and free it, a few times over.  The child's body.

    Written against ``glfw`` directly rather than through
    :mod:`OpenGLContext.testing.glcontext`, because what is being asked about
    is the library's own teardown and nothing above it.
    """
    try:
        import glfw
    except Exception:
        return CANNOT_TELL
    if not glfw.init():
        return CANNOT_TELL
    for _cycle in range(CYCLES):
        glfw.default_window_hints()
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        glfw.window_hint(glfw.DECORATED, glfw.FALSE)
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
        window = glfw.create_window(64, 64, 'teardown probe', None, None)
        if not window:
            return CANNOT_TELL
        glfw.make_context_current(window)
        # Something has to be drawn: a context the driver never used may never
        # allocate the state whose freeing is what faults.
        from OpenGL.GL import GL_COLOR_BUFFER_BIT, glClear, glFinish
        glClear(GL_COLOR_BUFFER_BIT)
        glFinish()
        glfw.destroy_window(window)
        glfw.poll_events()
    glfw.terminate()
    return 0


if __name__ == '__main__':                # pragma: no cover - the child process
    sys.exit(_probe())
