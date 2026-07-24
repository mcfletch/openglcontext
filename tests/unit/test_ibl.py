"""Unit tests for proper metal rendering: IBL mode resolution + adaptive
degradation, and the spec/gloss -> metallic/roughness conversion (no GL)."""
import os

import numpy as np
import pytest

from OpenGLContext.passes import ibl
from OpenGLContext.loaders.gltf.specular_glossiness import (
    _solve_metallic, _specgloss_to_metalrough, _specgloss_textures_to_metalrough,
    _DIELECTRIC_SPECULAR,
)


class TestResolveIBLMode:
    def test_auto_is_full_on_hardware_gpu(self):
        os.environ.pop('OPENGLCONTEXT_IBL', None)
        assert ibl.resolve_ibl_mode('NVIDIA GeForce RTX 3060 Ti') == 'full'

    def test_auto_degrades_to_analytic_on_software_rasteriser(self):
        os.environ.pop('OPENGLCONTEXT_IBL', None)
        assert ibl.resolve_ibl_mode('llvmpipe (LLVM 15)') == 'analytic'

    @pytest.mark.parametrize('value,expected', [
        ('off', 'off'), ('none', 'off'), ('0', 'off'),
        ('analytic', 'analytic'), ('approx', 'analytic'),
        ('full', 'full'), ('on', 'full'), ('1', 'full'),
    ])
    def test_env_override(self, value, expected):
        os.environ['OPENGLCONTEXT_IBL'] = value
        try:
            assert ibl.resolve_ibl_mode('llvmpipe') == expected
        finally:
            os.environ.pop('OPENGLCONTEXT_IBL', None)


class TestIBLController:
    def test_full_stays_full_with_headroom(self):
        c = ibl.IBLController('full')
        assert c.effective_mode(120.0) == 'full'
        assert c.effective_mode(120.0) == 'full'

    def test_full_degrades_to_analytic_when_fps_sags(self):
        c = ibl.IBLController('full')
        c.effective_mode(120.0)
        assert c.effective_mode(20.0) == 'analytic'

    def test_never_degrades_below_analytic(self):
        """Adaptation must never reach 'off' -- analytic is nearly free and keeps
        metals reflecting; only an explicit off selects off."""
        c = ibl.IBLController('full')
        for _ in range(20):
            c.effective_mode(10.0)
        assert c._effective == 'analytic'

    def test_re_upgrades_after_sustained_headroom(self):
        c = ibl.IBLController('full')
        c.effective_mode(20.0)                     # drop to analytic
        assert c._effective == 'analytic'
        last = 'analytic'
        for _ in range(ibl.IBLController.UP_FRAMES + ibl.IBLController.COOLDOWN + 5):
            last = c.effective_mode(200.0)
        assert last == 'full'

    def test_non_adaptive_pins_base_mode(self):
        c = ibl.IBLController('full', adaptive=False)
        assert c.effective_mode(5.0) == 'full'

    def test_off_base_is_never_touched(self):
        c = ibl.IBLController('off')
        assert c.effective_mode(5.0) == 'off'
        assert c.effective_mode(500.0) == 'off'


class TestIBLIsAdaptive:
    @pytest.mark.parametrize('value,expected', [
        ('', True), ('auto', True),
        ('full', False), ('analytic', False), ('off', False),
    ])
    def test_only_auto_or_unset_adapts(self, value, expected, monkeypatch):
        if value == '':
            monkeypatch.delenv('OPENGLCONTEXT_IBL', raising=False)
        else:
            monkeypatch.setenv('OPENGLCONTEXT_IBL', value)
        assert ibl.ibl_is_adaptive() is expected


class TestProbeMaxLod:
    def test_max_lod_is_levels_minus_one(self):
        """max_lod is a pure property; no probe build / GL needed."""
        p = ibl.IBLProbe()
        assert p.max_lod == float(ibl.IBLProbe.PRE_LEVELS - 1)


class TestEquirectSource:
    def teardown_method(self):
        ibl.set_equirect_env(None)

    def test_registered_panorama_wins(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
        arr = np.ones((4, 8, 3), dtype=np.float32)
        ibl.set_equirect_env(arr)
        out = ibl.resolve_equirect_source()
        assert out is not None
        assert out.shape == (4, 8, 3)

    def test_env_hdr_path_decoded_when_no_registered_env(self, monkeypatch):
        ibl.set_equirect_env(None)
        monkeypatch.setenv('OPENGLCONTEXT_ENV_HDR', '/some/panorama.hdr')
        loaded = np.zeros((2, 4, 3), dtype=np.float32)
        monkeypatch.setattr(ibl, 'load_equirect_hdr', lambda src: loaded)
        out = ibl.resolve_equirect_source()
        assert out is loaded

    def test_bad_env_hdr_is_logged_and_treated_as_unset(self, monkeypatch):
        ibl.set_equirect_env(None)
        monkeypatch.setenv('OPENGLCONTEXT_ENV_HDR', '/nonexistent.hdr')

        def boom(src):
            raise IOError("cannot read")

        monkeypatch.setattr(ibl, 'load_equirect_hdr', boom)
        assert ibl.resolve_equirect_source() is None

    def test_no_source_configured_returns_none(self, monkeypatch):
        ibl.set_equirect_env(None)
        monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
        assert ibl.resolve_equirect_source() is None


class TestLoadEquirectHDR:
    def test_url_source_is_fetched_to_cache_first(self, monkeypatch):
        """An http(s) HDR is fetched to the asset cache, then decoded from disk."""
        from OpenGLContext.loaders import hdr
        from OpenGLContext.loaders import resolver
        seen = {}

        def fake_fetch(url):
            seen['url'] = url
            return '/cache/panorama.hdr'

        decoded = np.zeros((2, 4, 3), dtype=np.float32)

        def fake_load(path):
            seen['path'] = path
            return decoded

        monkeypatch.setattr(resolver, 'fetch_to_cache', fake_fetch)
        monkeypatch.setattr(hdr, 'load_hdr', fake_load)
        out = ibl.load_equirect_hdr('https://example.com/pano.hdr')
        assert seen['url'] == 'https://example.com/pano.hdr'
        assert seen['path'] == '/cache/panorama.hdr'
        assert out is decoded

    def test_local_path_decoded_directly(self, monkeypatch):
        from OpenGLContext.loaders import hdr
        decoded = np.zeros((2, 4, 3), dtype=np.float32)
        monkeypatch.setattr(hdr, 'load_hdr', lambda path: decoded)
        assert ibl.load_equirect_hdr('/local/pano.hdr') is decoded


class TestGLContextPresent:
    def test_absent_context_when_query_raises(self, monkeypatch):
        def boom(enum):
            raise RuntimeError("no current context")

        monkeypatch.setattr(ibl, 'glGetString', boom)
        assert ibl._gl_context_present() is False


class TestFloatRenderProbe:
    def test_missing_immutable_storage_fails_probe(self, monkeypatch):
        """No glTexStorage2D entry point -> the 'full' path cannot run."""
        monkeypatch.setattr(ibl, 'glTexStorage2D', None)
        assert ibl._run_float_render_capability_probe() is False

    def test_no_context_defers_and_reports_capable(self, monkeypatch):
        """With no current context the probe is deferred (returns True, uncached)
        so headless mode resolution stays on the renderer-name path."""
        monkeypatch.setattr(ibl, '_gl_context_present', lambda: False)
        ibl._FLOAT_RENDER_CAP['checked'] = False
        assert ibl.probe_float_render_capability(force=True) is True
        assert ibl._FLOAT_RENDER_CAP['checked'] is False


class TestSpecGlossFactorConversion:
    def test_pure_dielectric_is_non_metal(self):
        base, metallic, rough = _specgloss_to_metalrough(
            [0.5, 0.2, 0.1, 1.0], [0.04, 0.04, 0.04], 0.5)
        assert metallic == pytest.approx(0.0, abs=1e-3)
        assert base == pytest.approx([0.5, 0.2, 0.1], abs=1e-2)
        assert rough == pytest.approx(0.5)

    def test_coloured_specular_metal_recovers_metallic_and_base(self):
        # gold: black diffuse, coloured high specular -> metallic ~1, base = spec
        base, metallic, rough = _specgloss_to_metalrough(
            [0.0, 0.0, 0.0, 1.0], [1.0, 0.78, 0.34], 0.9)
        assert metallic == pytest.approx(1.0, abs=1e-3)
        assert base == pytest.approx([1.0, 0.78, 0.34], abs=1e-2)
        assert rough == pytest.approx(0.1, abs=1e-3)

    def test_solve_metallic_below_dielectric_is_zero(self):
        assert _solve_metallic(0.5, _DIELECTRIC_SPECULAR - 0.01, 0.9) == 0.0


class TestSpecGlossTextureConversion:
    def _solid(self, rgba):
        from PIL import Image
        return Image.new('RGBA', (4, 4), tuple(rgba))

    def test_gold_specular_texture_becomes_metal(self):
        # diffuse black, specular ~gold, glossiness high (alpha 255)
        diffuse = self._solid((0, 0, 0, 255))
        sg = self._solid((255, 200, 90, 255))
        base_img, mr_img = _specgloss_textures_to_metalrough(
            diffuse, sg, [1, 1, 1, 1], [1, 1, 1, 1], 1.0)
        mr = np.asarray(mr_img)
        # B channel = metallic; near fully metallic for a bright coloured specular
        assert mr[..., 2].mean() > 240
        # G channel = roughness; glossiness 1.0 -> roughness 0
        assert mr[..., 1].mean() < 15
        base = np.asarray(base_img)
        # base colour is the (sRGB) specular tint, not black
        assert base[..., 0].mean() > 200 and base[..., 2].mean() < base[..., 0].mean()

    def test_dielectric_texture_stays_non_metal(self):
        diffuse = self._solid((180, 60, 40, 255))
        sg = self._solid((10, 10, 10, 128))          # low specular -> dielectric
        base_img, mr_img = _specgloss_textures_to_metalrough(
            diffuse, sg, [1, 1, 1, 1], [1, 1, 1, 1], 1.0)
        mr = np.asarray(mr_img)
        assert mr[..., 2].mean() < 15                 # metallic ~0
        base = np.asarray(base_img)                   # base ~ diffuse
        assert base[..., 0].mean() > base[..., 2].mean()


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
