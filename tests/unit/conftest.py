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


# Putting the renderer configuration back after every test is the shipped
# plugin's `gl_configuration` fixture, so it covers the whole session and a
# project built on the engine gets it too. This directory alone would be one
# directory short: the modules that set it at import are here, and
# `tests/test_all_scripts.py`, which inherits it into every script it launches,
# is not. See OpenGLContext.testing.gl_env.


# Whether a GLFW context can be handed back at all is a question about the
# driver, and some stacks abort the process answering it.
# `OpenGLContext.testing.glfwteardown` asks it, once per session and through
# the shipped plugin, so the answer covers the whole run rather than this
# directory: a stack that frees its contexts cleanly keeps the engine's own
# release path -- the one a user's application runs on exit -- under test.


@pytest.fixture
def render_scene(monkeypatch):
    """Build a context around a scenegraph, render frames, count what ran.

    Seven modules in this directory ask for it, so it is a fixture of the
    directory rather than one imported out of whichever test module happens to
    hold it. :mod:`tests.unit.glrender` is the machinery, and carries the rest
    of what those modules share.
    """
    from tests.unit import glrender

    yield from glrender.render_scene_factory(monkeypatch)


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
