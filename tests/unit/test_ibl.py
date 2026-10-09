"""Unit tests for proper metal rendering: IBL mode resolution + adaptive
degradation, and the spec/gloss -> metallic/roughness conversion (no GL)."""
import os

import numpy as np
import pytest
from PIL import Image

from OpenGLContext.passes import ibl
from OpenGLContext.loaders import hdr, resolver


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
        seen = [c.effective_mode(20.0) for _ in range(ibl.IBLController.DOWN_FRAMES)]
        assert seen[-1] == 'analytic'

    def test_a_few_slow_frames_leave_it_full(self):
        """Programs compiling in the first frames, or a mirror's first view,
        read as a few frames at a few fps: switching the lighting for a hundred
        frames over them changes every glossy surface twice."""
        c = ibl.IBLController('full')
        seen = [c.effective_mode(fps) for fps in [4.0] * 5 + [120.0] * 60]
        assert set(seen) == {'full'}

    def test_never_degrades_below_analytic(self):
        """Adaptation must never reach 'off' -- analytic is nearly free and keeps
        metals reflecting; only an explicit off selects off."""
        c = ibl.IBLController('full')
        seen = [c.effective_mode(10.0)
                for _ in range(ibl.IBLController.DOWN_FRAMES * 3)]
        assert seen[-1] == 'analytic'
        assert 'off' not in seen

    def test_re_upgrades_after_sustained_headroom(self):
        c = ibl.IBLController('full')
        for _ in range(ibl.IBLController.DOWN_FRAMES):
            last = c.effective_mode(20.0)          # drop to analytic
        assert last == 'analytic'
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
        monkeypatch.setattr(ibl, 'load_equirect_hdr', lambda _src: loaded)
        out = ibl.resolve_equirect_source()
        assert out is loaded

    def test_bad_env_hdr_is_logged_and_treated_as_unset(self, monkeypatch):
        ibl.set_equirect_env(None)
        monkeypatch.setenv('OPENGLCONTEXT_ENV_HDR', '/nonexistent.hdr')

        def boom(_src):
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
        decoded = np.zeros((2, 4, 3), dtype=np.float32)
        monkeypatch.setattr(hdr, 'load_hdr', lambda _path: decoded)
        assert ibl.load_equirect_hdr('/local/pano.hdr') is decoded


class TestGLContextPresent:
    def test_absent_context_when_query_raises(self, monkeypatch):
        def boom(_enum):
            raise RuntimeError("no current context")

        monkeypatch.setattr(ibl, 'glGetString', boom)
        assert ibl._gl_context_present() is False  # noqa: SLF001 the context check the capability probe defers on


class TestFloatRenderProbe:
    def test_missing_immutable_storage_fails_probe(self, monkeypatch):
        """No glTexStorage2D entry point -> the 'full' path cannot run."""
        monkeypatch.setattr(ibl, 'glTexStorage2D', None)
        assert ibl._run_float_render_capability_probe() is False  # noqa: SLF001 the capability probe with its entry point missing

    def test_no_context_defers_and_reports_capable(self, monkeypatch):
        """With no current context the probe is deferred (returns True, uncached)
        so headless mode resolution stays on the renderer-name path."""
        monkeypatch.setattr(ibl, '_gl_context_present', lambda: False)
        ibl._FLOAT_RENDER_CAP['checked'] = False  # noqa: SLF001 the probe's once-per-process memo, which a deferred probe must leave unset
        assert ibl.probe_float_render_capability(force=True) is True
        assert ibl._FLOAT_RENDER_CAP['checked'] is False  # noqa: SLF001 the probe's once-per-process memo, which a deferred probe must leave unset


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
