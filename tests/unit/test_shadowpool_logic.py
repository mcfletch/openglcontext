"""Headless tests for the cascade controller + shadow-map pool (no GL).

:class:`_CascadeControllerMixin` (fps/VRAM-adaptive directional cascade count) and
:class:`_ShadowMapPoolMixin` (lazy pool allocation + teardown) are pure state
machines over a fake shader program / caps / frame counter, so they run without a
context. The real GL depth textures they hand out are covered in
test_shadowmap_gl.py.
"""
import pytest

from OpenGLContext.passes.shadowpool import (
    _CascadeControllerMixin, _ShadowMapPoolMixin,
)


class FakeProg:
    MAX_CASCADES = 4
    MAX_SHADOW_LIGHTS = 4


class Caps:
    def __init__(self, vram):
        self.total_vram_mb = vram


class FrameCounter:
    def __init__(self, fps):
        self._fps = fps

    def recentFps(self):
        return self._fps


class Ctx:
    def __init__(self, fps):
        self.frameCounter = FrameCounter(fps)


def _cascade(vram=8000, shadow_cascades=4, adaptive=False, fps=0.0):
    c = _CascadeControllerMixin.__new__(_CascadeControllerMixin)
    c._shadow_caps = Caps(vram) if vram is not None else None
    c.shadow_cascades = shadow_cascades
    c.shadow_cascades_adaptive = adaptive
    c.shader_program = FakeProg()
    c._adaptive_cascades = 1
    c._cascade_up_streak = 0
    c._cascade_cooldown = 0
    c.context = Ctx(fps)
    return c


class TestVramCascadeCap:
    def test_unknown_vram_is_conservative(self):
        assert _cascade(vram=None)._vramCascadeCap() == 2
        assert _cascade(vram=0)._vramCascadeCap() == 2

    def test_small_vram_single_cascade(self):
        assert _cascade(vram=2000)._vramCascadeCap() == 1

    def test_medium_vram_two_cascades(self):
        assert _cascade(vram=4000)._vramCascadeCap() == 2

    def test_large_vram_full_budget(self):
        assert _cascade(vram=8000, shadow_cascades=4)._vramCascadeCap() == 4


class TestEffectiveCascades:
    def test_env_pin_overrides_probe(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_SHADOW_CASCADES', '3')
        assert _cascade(adaptive=True, fps=200)._effectiveCascades() == 3

    def test_env_pin_clamped_to_max(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_SHADOW_CASCADES', '99')
        assert _cascade()._effectiveCascades() == FakeProg.MAX_CASCADES

    def test_non_integer_env_pin_ignored(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_SHADOW_CASCADES', 'lots')
        # falls through to the computed value (non-adaptive -> clamped budget)
        assert _cascade(adaptive=False)._effectiveCascades() == 4

    def test_non_adaptive_returns_clamped_budget(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_SHADOW_CASCADES', raising=False)
        c = _cascade(vram=8000, shadow_cascades=3, adaptive=False)
        assert c._effectiveCascades() == 3

    def test_low_fps_sheds_a_cascade(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_SHADOW_CASCADES', raising=False)
        c = _cascade(vram=8000, adaptive=True, fps=50.0)
        c._adaptive_cascades = 3
        c._cascade_cooldown = 5
        result = c._effectiveCascades()
        assert result == 2                      # shed one from the effective 3
        assert c._cascade_cooldown == c._CASCADE_COOLDOWN
        assert c._cascade_up_streak == 0

    def test_high_fps_ramps_up_after_sustained_headroom(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_SHADOW_CASCADES', raising=False)
        c = _cascade(vram=8000, adaptive=True, fps=200.0)
        c._adaptive_cascades = 1
        # one frame short of the streak: still 1, streak incremented
        c._cascade_up_streak = c._CASCADE_UP_FRAMES - 1
        assert c._effectiveCascades() == 2      # earns a cascade this frame

    def test_steady_fps_holds_and_resets_streak(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_SHADOW_CASCADES', raising=False)
        c = _cascade(vram=8000, adaptive=True, fps=75.0)   # between down and up
        c._adaptive_cascades = 2
        c._cascade_up_streak = 10
        assert c._effectiveCascades() == 2
        assert c._cascade_up_streak == 0


# --------------------------------------------------------------------------- #
# _ShadowMapPoolMixin
# --------------------------------------------------------------------------- #
class _RaisingPool:
    def cleanup(self):
        raise RuntimeError("cleanup failed")


def _pool():
    p = _ShadowMapPoolMixin.__new__(_ShadowMapPoolMixin)
    p.shader_program = FakeProg()
    p.shadow_resolution = 1024
    p.shadow_cube_resolution = 512
    p._shared_array = None
    p._shared_cube_array = None
    p._maps_cube = None
    p._shadow_bindings = None
    p._depth_map_cache = None
    p._depth_grouping_cache = None
    return p


class TestShadowMapPool:
    def test_array_layers_is_lights_times_cascades(self):
        assert _pool()._array_layers() == FakeProg.MAX_SHADOW_LIGHTS * FakeProg.MAX_CASCADES

    def test_shared_map_created_and_cached(self):
        from OpenGLContext.passes.shadowmap import ShadowMapArray
        p = _pool()
        arr = p._shared_map()
        assert isinstance(arr, ShadowMapArray)
        assert arr.layers == FakeProg.MAX_SHADOW_LIGHTS * FakeProg.MAX_CASCADES
        assert p._shared_map() is arr             # cached

    def test_cube_array_map_created_and_cached(self):
        from OpenGLContext.passes.shadowmap import ShadowMapCubeArray
        p = _pool()
        ca = p._cube_array_map()
        assert isinstance(ca, ShadowMapCubeArray)
        assert ca.num_cubes == FakeProg.MAX_SHADOW_LIGHTS
        assert p._cube_array_map() is ca

    def test_map_cube_created_and_cached_per_slot(self):
        p = _pool()
        a = p._map_cube(0)
        assert a is p._map_cube(0)               # cached per slot
        b = p._map_cube(1)
        assert b is not a
        assert set(p._maps_cube) == {0, 1}
        assert a.size == 512

    def test_dispose_swallows_pool_cleanup_errors(self):
        p = _pool()
        p._shared_array = _RaisingPool()
        p._shared_cube_array = _RaisingPool()
        p._maps_cube = {0: _RaisingPool()}
        p.disposeShadowMaps()                    # every cleanup throws; must not raise
        assert p._shared_array is None
        assert p._shared_cube_array is None
        assert p._maps_cube is None
        assert p._depth_map_cache is None
        assert p._depth_grouping_cache is None


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
