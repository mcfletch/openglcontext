"""Isolation fixtures shared by the unit tests.

**Process-lifetime memos of environment variables.** ``monkeypatch`` puts the
variable back; nothing puts the memo back, so the first test to read one
decides the answer for every test after it. Clearing them around every test is
what keeps a file's result the same whether it runs alone or after two hundred
others.

The environment those memos are read from is the shipped plugin's to restore --
:mod:`OpenGLContext.testing.gl_env` -- and it does it for the whole session
rather than for this directory.
"""

from typing import Iterator

import pytest


@pytest.fixture(autouse=True)
def reset_environment_memos() -> Iterator[None]:
    """Clear the cached environment and driver reads before and after each test.

    Both ends, not just one: before, so a test sees the variables it set rather
    than a value some earlier test settled; after, so a test that deliberately
    pokes a memo does not leave it holding its answer.

    The driver's shadow capabilities are memoised for the same reason the
    environment reads are -- they cannot change while a context lives -- and a
    test that fakes a failing GL query has to reach the query to see it fail.
    """
    from OpenGLContext import renderoptions
    from OpenGLContext.passes import pbrpass, shadersource, shadowcaps

    def clear() -> None:
        pbrpass.reset_renderer_cache()
        renderoptions.reset_env_cache()
        shadowcaps.reset_detected()
        shadersource.reset_shadow_config()

    clear()
    yield
    clear()


# Putting the renderer configuration back after every test used to be done
# here, for this directory only -- which is one directory short: the modules
# that set it at import are here, and `tests/test_all_scripts.py`, which
# inherits it into every script it launches, is not. It is the shipped plugin's
# `gl_configuration` fixture now, so it covers the whole session and a project
# built on the engine gets it too. See OpenGLContext.testing.gl_env.


# Tearing down a GLFW context on this Wayland/EGL stack corrupts the heap. A
# hidden core window built and then destroyed reproduces it with no OpenGLContext
# in the loop, and gdb puts the fault squarely in the driver, not in us:
#
#     free(): invalid size   -> abort
#       __libc_free
#       libgallium-25.2.8 (Mesa)          <- invalid free
#       libEGL_mesa.so.0
#       destroyContextEGL
#       _glfwDestroyWindowWayland
#       glfwDestroyWindow                 (and the same path under glfwTerminate)
#
# So both ``glfwDestroyWindow`` and ``glfwTerminate`` free an EGL context through
# Mesa's Gallium driver, which frees a bad pointer and aborts.  The abort lands
# in whatever runs next -- often a later test's ``glfw.poll_events`` or its own
# teardown -- long after the assertions that "caused" it have passed, which is
# why it reads as flaky cross-test pollution rather than one broken test.  A
# SIGABRT cannot be caught, so a single teardown takes the whole run down.
#
# A test process has no need to hand these back at all: ``glfw.init()`` returns
# immediately when the library is already initialised, and the OS reclaims every
# context and window when the process exits.  Neutralise both teardown calls for
# the session (patched here at conftest import, before any fixture runs) so the
# driver's broken free is never reached.  The hidden windows a run leaks cost a
# little memory until it ends and nothing more.  Remove this once the Mesa/GLFW
# Wayland-EGL context teardown no longer faults.
try:
    import glfw as _glfw
except Exception:
    pass
else:
    _glfw.terminate = lambda: None
    _glfw.destroy_window = lambda window: None


@pytest.fixture(scope='session')
def posix_modes(tmp_path_factory):
    """Whether this filesystem enforces the POSIX mode a directory asks for.

    The engine creates its private directories with ``mode=0o700``, and on a
    POSIX filesystem that is what keeps another account out of them. Windows
    ignores the mode and controls access by ACL instead, reporting 0o777 for
    every directory -- so the mode says nothing there, and a test that reads it
    is asking a question the platform does not answer.
    """
    import os
    import stat

    probe = tmp_path_factory.mktemp('modes') / 'private'
    os.makedirs(str(probe), mode=0o700, exist_ok=True)
    return not stat.S_IMODE(os.stat(str(probe)).st_mode) & (stat.S_IRWXG | stat.S_IRWXO)
