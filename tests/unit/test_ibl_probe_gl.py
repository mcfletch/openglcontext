"""In-process GL tests for the IBLProbe build/bind/release lifecycle.

These drive the real probe machinery against a hidden GLFW context: the
RGBA16F-render capability probe, the procedural and cubemap env-source paths,
the rebuild-on-env-change and build-failure fallbacks, per-frame texture binding,
and defensive teardown. The pure mode-resolution logic is in test_ibl.py.
"""
import os

import numpy as np
import pytest

glfw = pytest.importorskip("glfw")

from OpenGLContext.passes import ibl  # noqa: E402
from OpenGLContext.passes.ibl import IBLProbe  # noqa: E402


@pytest.fixture
def gl_context():
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    if not glfw.init():
        pytest.skip("glfw init failed")
    glfw.default_window_hints()
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    win = glfw.create_window(64, 64, "ibl-probe", None, None)
    if not win:
        pytest.skip("no GL window")
    glfw.make_context_current(win)
    yield win
    glfw.destroy_window(win)


class _FakeProgram:
    """Stand-in for VRML97ShaderProgram: records the prefilterMaxLod upload."""
    program = 0

    def __init__(self):
        self.calls = []

    def _set_uniform1f(self, name, value, program):
        self.calls.append((name, value, program))


def test_float_render_capability_probe_true_on_real_gpu(gl_context):
    """A live desktop GL context can render an RGBA16F FBO, so the probe passes
    and caches its verdict for the process."""
    ibl._FLOAT_RENDER_CAP['checked'] = False
    ibl._FLOAT_RENDER_CAP['ok'] = False
    assert ibl._run_float_render_capability_probe() is True
    # the public wrapper caches: first real probe sets checked, second reuses it
    ibl._FLOAT_RENDER_CAP['checked'] = False
    assert ibl.probe_float_render_capability(force=True) is True
    assert ibl._FLOAT_RENDER_CAP['checked'] is True
    assert ibl.probe_float_render_capability() is True    # cached path


def test_gl_context_present_true_with_live_context(gl_context):
    assert ibl._gl_context_present() is True


class TestProceduralBuild:
    def test_build_bind_and_release(self, gl_context, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
        monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)
        ibl.set_equirect_env(None)
        probe = IBLProbe()
        assert probe.ensure_built() is True
        assert probe.ready is True
        # every probe texture was allocated
        assert probe.env is not None
        assert probe.irradiance is not None
        assert probe.prefilter is not None
        assert probe.brdf is not None

        prog = _FakeProgram()
        probe.bind(prog)
        assert prog.calls == [('prefilterMaxLod', probe.max_lod, 0)]

        probe.release()
        assert probe.env is None and probe.brdf is None

    def test_second_ensure_built_is_cached(self, gl_context, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
        monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)
        ibl.set_equirect_env(None)
        probe = IBLProbe()
        probe.ensure_built()
        env_tex = probe.env
        # same env generation -> no rebuild, same textures
        assert probe.ensure_built() is True
        assert probe.env == env_tex
        probe.release()

    def test_env_change_triggers_rebuild(self, gl_context, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
        monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)
        ibl.set_equirect_env(None)
        probe = IBLProbe()
        probe.ensure_built()
        gen0 = probe._source_gen
        # registering a new panorama bumps the generation -> rebuild
        ibl.set_equirect_env(np.ones((8, 16, 3), dtype=np.float32))
        try:
            assert probe.ensure_built() is True
            assert probe._source_gen != gen0
        finally:
            probe.release()
            ibl.set_equirect_env(None)


class TestCubemapEnvSource:
    def test_cubemap_faces_uploaded_into_env(self, gl_context, monkeypatch):
        """When a cubemap face set is configured, its faces are uploaded into the
        env cube rather than the procedural studio env being rendered."""
        monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
        monkeypatch.setenv('OPENGLCONTEXT_ENV_CUBEMAP', '/fake/env_')
        ibl.set_equirect_env(None)
        size = IBLProbe.ENV_SIZE
        faces = {off: np.full((size, size, 3), 0.5, dtype=np.float32)
                 for off in range(6)}
        monkeypatch.setattr(ibl, 'load_cubemap_faces', lambda prefix, s: faces)
        probe = IBLProbe()
        try:
            assert probe.ensure_built() is True
            assert probe.env is not None
        finally:
            probe.release()


class TestBuildFailureFallback:
    def test_build_exception_degrades_to_not_ready(self, gl_context, monkeypatch):
        """If _build raises, ensure_built swallows it and reports not-ready so the
        caller falls back to the analytic path."""
        ibl.set_equirect_env(None)
        probe = IBLProbe()

        def boom():
            raise RuntimeError("simulated float-cube incompleteness")

        monkeypatch.setattr(probe, '_build', boom)
        assert probe.ensure_built() is False
        assert probe.ready is False
        assert probe._failed is True


class TestDefensiveTeardown:
    def test_release_swallows_texture_delete_errors(self, gl_context, monkeypatch):
        """A GL failure while freeing probe textures must not escape release()."""
        ibl.set_equirect_env(None)
        probe = IBLProbe()
        probe.ensure_built()

        def boom(_ids):
            raise RuntimeError("delete failed")

        monkeypatch.setattr(ibl, 'glDeleteTextures', boom)
        probe.release()               # must not raise
        assert probe.env is None
        assert probe.brdf is None


class TestCapabilityProbeDefensive:
    def test_gl_error_during_probe_reports_incapable(self, gl_context, monkeypatch):
        """A raised GL error while trialling the RGBA16F FBO degrades to False."""
        def boom(*a, **k):
            raise RuntimeError("simulated immutable-storage failure")

        # a function object is truthy, so the `not glTexStorage2D` early-out is
        # skipped and the probe reaches the trial-allocation try/except.
        monkeypatch.setattr(ibl, 'glTexStorage2D', boom)
        assert ibl._run_float_render_capability_probe() is False


class TestBuildDefensive:
    def _procedural(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
        monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)
        ibl.set_equirect_env(None)

    def test_incomplete_cube_fbo_degrades_to_not_ready(self, gl_context, monkeypatch):
        """An incomplete cube FBO (status != COMPLETE) aborts the build; ensure_built
        swallows it and reports not-ready for the analytic fallback."""
        self._procedural(monkeypatch)
        monkeypatch.setattr(ibl, 'glCheckFramebufferStatus', lambda target: 0)
        probe = IBLProbe()
        assert probe.ensure_built() is False
        assert probe.ready is False
        assert probe._failed is True

    def test_incomplete_final_fbo_raises_and_degrades(self, gl_context, monkeypatch):
        """A BRDF-LUT stage that returns an incomplete status raises out of _build;
        ensure_built degrades to not-ready."""
        self._procedural(monkeypatch)
        probe = IBLProbe()
        monkeypatch.setattr(probe, '_build_brdf_lut', lambda fbo, prog: 0)
        assert probe.ensure_built() is False
        assert probe._failed is True

    def test_program_teardown_errors_do_not_break_build(self, gl_context, monkeypatch):
        """A GL failure while freeing the transient build programs is swallowed and
        the probe still builds successfully."""
        self._procedural(monkeypatch)
        probe = IBLProbe()

        def boom(_prog):
            raise RuntimeError("delete program failed")

        monkeypatch.setattr(ibl, 'glDeleteProgram', boom)
        assert probe.ensure_built() is True
        assert probe.ready is True
        probe.release()

    def test_equirect_teardown_errors_do_not_break_build(self, gl_context, monkeypatch):
        """The equirect env path frees a temporary source texture + program in a
        finally; delete failures there must not escape the build."""
        monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)
        ibl.set_equirect_env(np.ones((8, 16, 3), dtype=np.float32))

        def boom(*a, **k):
            raise RuntimeError("teardown delete failed")

        monkeypatch.setattr(ibl, 'glDeleteTextures', boom)
        monkeypatch.setattr(ibl, 'glDeleteProgram', boom)
        probe = IBLProbe()
        try:
            assert probe.ensure_built() is True
            assert probe.ready is True
        finally:
            ibl.set_equirect_env(None)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v', '-s']))
