"""Equirectangular-HDR environment source for the IBL probe.

Headless tests for the non-GL logic: registering an equirect panorama as the probe
env source, generation bumping (so a built probe knows to rebuild), and resolving
the ``OPENGLCONTEXT_ENV_HDR`` path/URL source. The actual cube convolution is
covered by the GL render test (test_hdr_background_render.py).
"""
import os
import numpy as np
import pytest

from OpenGLContext.passes import ibl


@pytest.fixture(autouse=True)
def _clear_env_registration():
    """Each test starts with no registered equirect env."""
    ibl.set_equirect_env(None)
    yield
    ibl.set_equirect_env(None)


def test_register_equirect_env_roundtrips():
    arr = np.ones((4, 8, 3), dtype=np.float32)
    ibl.set_equirect_env(arr)
    got = ibl.get_equirect_env()
    assert got is not None
    assert got.shape == (4, 8, 3)
    assert got.dtype == np.float32


def test_registration_bumps_generation():
    g0 = ibl.equirect_env_generation()
    ibl.set_equirect_env(np.ones((2, 4, 3), np.float32))
    g1 = ibl.equirect_env_generation()
    ibl.set_equirect_env(np.zeros((2, 4, 3), np.float32))
    g2 = ibl.equirect_env_generation()
    assert g1 > g0 and g2 > g1


def test_clear_registration():
    ibl.set_equirect_env(np.ones((2, 4, 3), np.float32))
    assert ibl.get_equirect_env() is not None
    ibl.set_equirect_env(None)
    assert ibl.get_equirect_env() is None


def test_env_hdr_path_from_environment(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_ENV_HDR', '/some/where/foo.hdr')
    assert ibl.equirect_hdr_path() == '/some/where/foo.hdr'
    monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
    assert ibl.equirect_hdr_path() is None


def test_load_equirect_hdr_from_local_file(tmp_path):
    # Build a tiny valid Radiance file via the decoder's own round-trip helpers.
    from tests.unit.test_hdr_loader import encode_flat
    src = (np.linspace(0, 4, 8 * 16 * 3, dtype=np.float32).reshape(8, 16, 3))
    p = tmp_path / 'tiny.hdr'
    p.write_bytes(encode_flat(src))
    out = ibl.load_equirect_hdr(str(p))
    assert out.shape == (8, 16, 3)
    assert out.dtype == np.float32


def test_registered_env_takes_priority_over_env_var(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_ENV_HDR', '/does/not/exist.hdr')
    arr = np.ones((2, 4, 3), np.float32)
    ibl.set_equirect_env(arr)
    # resolve_env_source returns the registered array without touching the bad path
    src = ibl.resolve_equirect_source()
    assert src is arr


def test_resolve_equirect_source_none_when_unset(monkeypatch):
    monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
    assert ibl.resolve_equirect_source() is None


def test_capability_probe_returns_bool():
    # Headless (no current GL context) the probe defers, reporting capable, so
    # mode resolution stays on the renderer-name path. Either way it is a bool.
    result = ibl.probe_float_render_capability(force=True)
    assert isinstance(result, bool)
    assert result is True          # no context -> deferred -> capable


def test_resolve_ibl_mode_degrades_to_analytic_when_probe_fails():
    """A failed capability probe must gate 'full' down to 'analytic', even on a
    GPU whose renderer name passes the software blocklist."""
    assert ibl.resolve_ibl_mode(
        'NVIDIA GeForce RTX 4090', probe=lambda: False) == 'analytic'


def test_resolve_ibl_mode_stays_full_when_probe_passes():
    assert ibl.resolve_ibl_mode(
        'NVIDIA GeForce RTX 4090', probe=lambda: True) == 'full'


def test_explicit_full_is_still_gated_by_probe(monkeypatch):
    """Even an explicit OPENGLCONTEXT_IBL=full degrades when the probe fails, so
    'full' is never selected on hardware that cannot render the RGBA16F cube."""
    monkeypatch.setenv('OPENGLCONTEXT_IBL', 'full')
    assert ibl.resolve_ibl_mode('llvmpipe', probe=lambda: False) == 'analytic'


def test_dir_to_equirect_is_shared_by_both_shaders():
    """The equirect UV mapping lives once in _cubemap_inc.glsl and both the skybox
    and the reflection shader pull it from there (kept in lock-step)."""
    from OpenGLContext.passes.shadersource import preprocess_shader
    sky = preprocess_shader('hdr_background.frag')
    refl = preprocess_shader('ibl_equirect.frag')
    # hdr_background.frag is routed through the include preprocessor.
    assert '_cubemap_inc.glsl' in sky
    # Exactly one definition each -- pulled from the shared include, no private copy.
    assert sky.count('vec2 dirToEquirect(vec3') == 1
    assert refl.count('vec2 dirToEquirect(vec3') == 1
    # A single shared INV_ATAN constant (from the include), not one per shader body.
    assert sky.count('const vec2 INV_ATAN') == 1
    assert refl.count('const vec2 INV_ATAN') == 1


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
