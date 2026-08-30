"""What a light's own `shadowBias` / `shadowMapResolution` fields drive.

The shadow maps share one physical depth array, so the resolution is one number
for all of them: the largest any casting light asks for. The bias is not shared
-- it converts against each map's own projection where that map is built -- so a
light asking for more slack gets it without loosening every other light's shadow.
"""
import pytest

from OpenGLContext.passes.shadowmixin import (
    SHADOW_DEPTH_BIAS, light_depth_bias, per_light_shadow_resolution,
)


class _Light:
    def __init__(self, bias=None, resolution=None):
        if bias is not None:
            self.shadowBias = bias
        if resolution is not None:
            self.shadowMapResolution = resolution


class TestPerLightResolution:
    def test_no_lights_uses_the_default(self):
        assert per_light_shadow_resolution([], 2048) == 2048

    def test_largest_resolution_wins(self):
        lights = [_Light(resolution=1024), _Light(resolution=4096),
                  _Light(resolution=2048)]
        assert per_light_shadow_resolution(lights, 2048) == 4096

    def test_resolution_clamped_to_sane_range(self):
        assert per_light_shadow_resolution([_Light(resolution=99999)], 2048) == 8192
        assert per_light_shadow_resolution([_Light(resolution=16)], 2048) == 256

    def test_fields_absent_falls_back(self):
        assert per_light_shadow_resolution([_Light()], 1024) == 1024


class TestPerLightBias:
    def test_a_light_without_the_field_takes_the_default(self):
        assert light_depth_bias(_Light()) == SHADOW_DEPTH_BIAS

    def test_each_light_keeps_its_own_bias(self):
        """The larger no longer wins for both: they light different maps."""
        tight, loose = _Light(bias=0.5), _Light(bias=4.0)
        assert light_depth_bias(tight) == pytest.approx(0.5)
        assert light_depth_bias(loose) == pytest.approx(4.0)

    def test_zero_is_a_bias_rather_than_a_missing_field(self):
        assert light_depth_bias(_Light(bias=0.0)) == 0.0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
