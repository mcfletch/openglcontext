"""The per-light `shadowBias` / `shadowMapResolution` node fields
were dead -- the shadow pass hardcoded module constants. The shared depth array
is one physical texture, so a single bias/resolution drives all slots; the pass
now derives them from the shadow-casting lights (largest requested wins, favouring
acne-free, higher-detail maps) instead of ignoring the fields.
"""
import pytest

from OpenGLContext.passes import shadowmixin
from OpenGLContext.passes.shadowmixin import per_light_shadow_settings, SHADOW_DEPTH_BIAS


class _Light:
    def __init__(self, bias=None, resolution=None):
        if bias is not None:
            self.shadowBias = bias
        if resolution is not None:
            self.shadowMapResolution = resolution


class TestPerLightSettings:
    def test_no_lights_uses_defaults(self):
        bias, res = per_light_shadow_settings([], SHADOW_DEPTH_BIAS, 2048)
        assert bias == SHADOW_DEPTH_BIAS
        assert res == 2048

    def test_largest_resolution_wins(self):
        lights = [_Light(resolution=1024), _Light(resolution=4096),
                  _Light(resolution=2048)]
        _, res = per_light_shadow_settings(lights, SHADOW_DEPTH_BIAS, 2048)
        assert res == 4096

    def test_largest_bias_wins(self):
        lights = [_Light(bias=0.001), _Light(bias=0.004)]
        bias, _ = per_light_shadow_settings(lights, SHADOW_DEPTH_BIAS, 2048)
        assert bias == pytest.approx(0.004)

    def test_resolution_clamped_to_sane_range(self):
        lights = [_Light(resolution=99999)]
        _, res = per_light_shadow_settings(lights, SHADOW_DEPTH_BIAS, 2048)
        assert res == 8192
        lights = [_Light(resolution=16)]
        _, res = per_light_shadow_settings(lights, SHADOW_DEPTH_BIAS, 2048)
        assert res == 256

    def test_fields_absent_falls_back(self):
        # a light node without the fields must not crash the derivation
        bias, res = per_light_shadow_settings([_Light()], 0.002, 1024)
        assert bias == 0.002 and res == 1024


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
