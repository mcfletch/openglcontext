"""Unit tests for shadow capability detection logic (no GL context)."""
import pytest

from OpenGLContext.passes.shadowcaps import ShadowCapabilities


class TestTechniqueSelection:
    def test_baseline_33_has_cube_and_csm(self):
        caps = ShadowCapabilities.from_features(set(), (3, 3))
        assert caps.has_cube_shadow is True
        assert caps.point_technique == 'cube'
        # 3.3 (>= 3.2) has depth clamp
        assert caps.has_depth_clamp is True
        # but not 4.0-era features without the extension
        assert caps.has_texture_gather is False
        assert caps.has_cube_array is False

    def test_texture_gather_via_extension(self):
        caps = ShadowCapabilities.from_features({'GL_ARB_texture_gather'}, (3, 3))
        assert caps.has_texture_gather is True

    def test_texture_gather_via_version_40(self):
        caps = ShadowCapabilities.from_features(set(), (4, 0))
        assert caps.has_texture_gather is True
        assert caps.has_cube_array is True

    def test_extension_name_without_gl_prefix(self):
        caps = ShadowCapabilities.from_features({'ARB_texture_cube_map_array'}, (3, 3))
        assert caps.has_cube_array is True

    def test_old_context_no_cube(self):
        caps = ShadowCapabilities.from_features(set(), (2, 1))
        assert caps.has_cube_shadow is False
        assert caps.point_technique == 'none'


class TestUnitBudget:
    # Packed layout: fixed cost is shadowArray + shadowArrayRaw = 2
    # fragment units; point shadows add one cube-array unit total, or one cube
    # sampler per light in the 3.3 fallback.

    def test_baseline_16_units_supports_full_four(self):
        # 16 - 4 reserved = 12 avail; fallback caps at HARD_MAX (4).
        caps = ShadowCapabilities.from_features(set(), (3, 3), max_texture_units=16)
        assert caps.max_shadow_lights(reserved_units=4) == 4

    def test_fallback_scales_with_units(self):
        # 10 units, 4 reserved -> 6 avail; minus the 2 array samplers = 4 cubes.
        caps = ShadowCapabilities.from_features(set(), (3, 3), max_texture_units=10)
        assert caps.max_shadow_lights(reserved_units=4) == 4
        # 9 units -> 5 avail -> 3 cube samplers -> 3 lights
        caps9 = ShadowCapabilities.from_features(set(), (3, 3), max_texture_units=9)
        assert caps9.max_shadow_lights(reserved_units=4) == 3

    def test_cube_array_independent_of_light_count(self):
        # With a cube-array all point shadows cost one unit, so a tight budget
        # still allows the full four lights.
        caps = ShadowCapabilities.from_features(
            {'ARB_texture_cube_map_array'}, (3, 3), max_texture_units=8)
        assert caps.has_cube_array is True
        assert caps.max_shadow_lights(reserved_units=4) == 4

    def test_max_shadow_lights_never_zero(self):
        caps = ShadowCapabilities.from_features(set(), (3, 3), max_texture_units=4)
        assert caps.max_shadow_lights(reserved_units=4) == 1


class TestNoPhantomTiers:
    """3.17: only capabilities the renderer actually consumes are exposed; the
    detected-but-never-implemented tiers were removed so callers can't branch on
    a phantom feature."""

    def test_dropped_unimplemented_capability_fields(self):
        caps = ShadowCapabilities.from_features(set(), (3, 3))
        for dead in ('has_geometry_layered', 'has_float_color', 'has_seamless_cube',
                     'has_aniso', 'max_array_layers'):
            assert not hasattr(caps, dead), f"{dead} is unimplemented; should be gone"

    def test_dropped_phantom_technique_selectors(self):
        caps = ShadowCapabilities.from_features(set(), (3, 3))
        # 'single' directional technique and a pcf_kernel size were never consumed
        assert not hasattr(caps, 'directional_technique')
        assert not hasattr(caps, 'pcf_kernel')

    def test_retained_fields_are_the_consumed_ones(self):
        caps = ShadowCapabilities.from_features(set(), (3, 3))
        for kept in ('has_texture_gather', 'has_cube_shadow', 'has_cube_array',
                     'has_depth_clamp', 'max_texture_units', 'total_vram_mb'):
            assert hasattr(caps, kept)


class TestVersionParsing:
    @pytest.mark.parametrize("raw,expected", [
        (b"3.3.0 NVIDIA 535.0", (3, 3)),
        (b"4.6 (Core Profile) Mesa 23.0", (4, 6)),
        ("3.0 Mesa", (3, 0)),
        (b"garbage", (3, 3)),
    ])
    def test_parse_version(self, raw, expected):
        assert ShadowCapabilities._parse_version(raw) == expected


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
