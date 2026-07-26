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
    """Clear the cached environment reads before and after every test.

    Both ends, not just one: before, so a test sees the variables it set rather
    than a value some earlier test settled; after, so a test that deliberately
    pokes a memo does not leave it holding its answer.
    """
    from OpenGLContext import renderoptions
    from OpenGLContext.passes import pbrpass

    def clear() -> None:
        pbrpass.reset_renderer_cache()
        renderoptions.reset_env_cache()

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
