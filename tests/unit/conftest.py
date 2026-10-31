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

import importlib
import os
import shutil
import stat
from collections.abc import Iterator

import pytest

from OpenGLContext import renderoptions
from OpenGLContext.passes import pbrpass, quality, shadersource, shadowcaps


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Run each test marked ``engines(...)`` once on each physics engine it names.

    A module marks itself ``pytestmark = pytest.mark.engines('omi', 'jolt')``;
    a test that reads one engine's own machinery narrows it with its own
    ``@pytest.mark.engines('omi', reason=...)``. An engine whose package is
    not installed is skipped, with the package named.
    """
    marker = metafunc.definition.get_closest_marker('engines')
    if marker is None:
        return
    metafunc.parametrize('physics_engine', [
        pytest.param(name, marks=pytest.mark.skipif(
            not _have(_PACKAGES[name]), reason='%s is not installed' % (_PACKAGES[name],)))
        for name in marker.args], indirect=True)


#: The package each engine steps its worlds with. pyjoltphysics is a requirement
#: of OpenGLContext; omi_physics is the deprecated ``omi`` extra, installed in
#: this workspace, so the omi engine's tests run here.
_PACKAGES = {'jolt': 'pyjoltphysics', 'omi': 'omi_physics'}


def _have(package: str) -> bool:
    try:
        importlib.import_module(package)
    except ImportError:
        return False
    return True


#: The modules that test the omi engine's own modules (its runtime, workers,
#: replica and queries) import them at the top; they are not collected where
#: omi_physics, the deprecated omi extra, is not installed.
collect_ignore = [] if _have('omi_physics') else [
    'test_physics_frame_cost.py', 'test_physics_runtime.py', 'test_physics_sweep_steps.py']


@pytest.fixture(autouse=True)
def physics_engine(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str | None:
    """The physics engine a test marked ``engines`` steps its worlds with, as the definition's default.

    Autouse, so it is set before the fixtures that make a service; a test
    with no ``engines`` mark is left with the environment it was given.
    """
    name = getattr(request, 'param', None)
    if name is None:
        return None
    monkeypatch.setenv('OPENGLCONTEXT_PHYSICS_ENGINE', str(name))
    renderoptions.reset_env_cache()
    return str(name)


@pytest.fixture(autouse=True)
def reset_environment_memos() -> Iterator[None]:
    """Clear the cached environment and driver reads before and after each test.

    Both ends, not just one: before, so a test sees the variables it set rather
    than a value some earlier test settled; after, so a test that deliberately
    pokes a memo does not leave it holding its answer.

    The frame's quality choices (:func:`OpenGLContext.passes.quality.use`)
    go back to ``auto`` for the same reason.

    The driver's shadow capabilities are memoised for the same reason the
    environment reads are -- they cannot change while a context lives -- and a
    test that fakes a failing GL query has to reach the query to see it fail.
    """
    def clear() -> None:
        pbrpass.reset_renderer_cache()
        renderoptions.reset_env_cache()
        shadowcaps.reset_detected()
        shadersource.reset_shadow_config()
        quality.use('auto', 'auto')

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
    # glrender skips its importer where glfw is not installed, which at the
    # top of this conftest would stop the directory's collection.
    from tests.unit import glrender  # noqa: PLC0415 skips without glfw

    yield from glrender.render_scene_factory(monkeypatch)


@pytest.fixture
def sixteen_samplers(monkeypatch):
    """The PBR program compiled as for a fragment stage of 16 samplers, GL 3.3's least

    Two modules draw what such a driver draws: a Phong material's maps and
    a MultiTexture's layers, through the samplers a draw leaves free.
    """
    from OpenGL.GL import GL_MAX_TEXTURE_IMAGE_UNITS  # noqa: PLC0415 kept with its use

    from OpenGLContext.passes import pbrpass  # noqa: PLC0415 kept with its use
    real = pbrpass.glGetIntegerv

    def reported(name):
        return 16 if name == GL_MAX_TEXTURE_IMAGE_UNITS else real(name)
    monkeypatch.setattr(pbrpass, 'glGetIntegerv', reported)


@pytest.fixture(scope='session')
def posix_modes(tmp_path_factory):
    """Whether this filesystem enforces the POSIX mode a directory asks for.

    The engine creates its private directories with ``mode=0o700``, and on a
    POSIX filesystem that is what keeps another account out of them. Windows
    ignores the mode and controls access by ACL instead, reporting 0o777 for
    every directory -- so the mode says nothing there, and a test that reads it
    is asking a question the platform does not answer.
    """
    probe = tmp_path_factory.mktemp('modes') / 'private'
    os.makedirs(str(probe), mode=0o700, exist_ok=True)
    return not stat.S_IMODE(os.stat(str(probe)).st_mode) & (stat.S_IRWXG | stat.S_IRWXO)


@pytest.fixture(scope='session')
def blender():
    """The ``blender`` executable on the path; a test asking for it is skipped
    where there is none, since Blender is an optional tool here."""
    found = shutil.which('blender')
    if found is None:
        pytest.skip('Blender is not installed')
    return found


@pytest.fixture
def no_installed_content(tmp_path, monkeypatch):
    """The per-user content store is empty: no pack fetched on this machine is found.

    A pack a developer has installed (``release-assets.py --install``, or a first run of a
    game) lives under the per-user application directory, so a test that means no pack to be
    installed moves that directory.
    """
    monkeypatch.setattr('OpenGLContext.userpaths.appdatadirectory',
                        lambda: str(tmp_path / 'appdata'))
