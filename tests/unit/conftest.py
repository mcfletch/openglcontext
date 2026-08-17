"""Isolation fixtures shared by the unit tests.

Two pieces of global state a unit test cannot restore for itself, and both
decide what *later* tests see:

* **Process-lifetime memos of environment variables.**  ``monkeypatch`` puts
  the variable back; nothing puts the memo back, so the first test to read one
  decides the answer for every test after it.
* **The environment itself.**  Several of these tests render in a subprocess
  that inherits ``os.environ``, so a test that sets a variable without
  ``monkeypatch`` -- or a module that sets one at import time -- silently
  reconfigures the renderer for every later test that spawns one.

Clearing and restoring both around every test is what keeps a file's result the
same whether it runs alone or after two hundred others.
"""

import os
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


#: The renderer-configuring variables to restore, and what they were when this
#: file was imported -- **before any test module was**.  Several test modules
#: set one of these at import time to configure their own GL context; taken at
#: test start instead, that pollution would already be baked in and would carry
#: to every later test, including the ones that render in a subprocess and
#: inherit it.
_ENV_PREFIXES = ('OPENGLCONTEXT_', 'PYOPENGL_')
_PRISTINE_ENV = {name: value for name, value in os.environ.items()
                 if name.startswith(_ENV_PREFIXES)}


@pytest.fixture(autouse=True)
def restore_environment() -> Iterator[None]:
    """Put ``OPENGLCONTEXT_*`` and ``PYOPENGL_*`` back after every test.

    Back to what the *session* started with, not to what this test started
    with: a module that sets one of these at import time has already changed it
    for everything collected after it, and a test that renders in a subprocess
    inherits whatever is there.  Restoring to the session's own environment is
    what makes a file's result the same however it is scheduled.

    Only these two prefixes rather than the whole environment: they are what
    changes the renderer, and leaving the rest alone keeps this from fighting
    anything that legitimately edits the environment for the session.
    """
    yield
    for name in [n for n in os.environ if n.startswith(_ENV_PREFIXES)]:
        if name not in _PRISTINE_ENV:
            del os.environ[name]
    os.environ.update(_PRISTINE_ENV)


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
