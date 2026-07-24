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


class TestVramQuery:
    """_query_vram_mb reads the vendor meminfo extension when present."""

    def test_nvidia_nvx_reports_total_vram(self, monkeypatch):
        import OpenGL.GL as GL
        monkeypatch.setattr(GL, 'glGetIntegerv', lambda enum: 8 * 1024 * 1024)
        mb = ShadowCapabilities._query_vram_mb({'GL_NVX_gpu_memory_info'})
        assert mb == 8 * 1024   # KB -> MB

    def test_amd_ati_meminfo_list_first_element(self, monkeypatch):
        import OpenGL.GL as GL
        monkeypatch.setattr(GL, 'glGetIntegerv',
                            lambda enum: [4 * 1024 * 1024, 0, 0, 0])
        mb = ShadowCapabilities._query_vram_mb({'GL_ATI_meminfo'})
        assert mb == 4 * 1024

    def test_amd_ati_meminfo_scalar(self, monkeypatch):
        import OpenGL.GL as GL
        monkeypatch.setattr(GL, 'glGetIntegerv', lambda enum: 2 * 1024 * 1024)
        mb = ShadowCapabilities._query_vram_mb({'GL_ATI_meminfo'})
        assert mb == 2 * 1024

    def test_no_meminfo_extension_returns_zero(self, monkeypatch):
        import OpenGL.GL as GL
        monkeypatch.setattr(GL, 'glGetIntegerv',
                            lambda enum: pytest.fail("must not query"))
        assert ShadowCapabilities._query_vram_mb(set()) == 0

    def test_query_exception_returns_zero(self, monkeypatch):
        import OpenGL.GL as GL

        def boom(enum):
            raise RuntimeError("no GL")

        monkeypatch.setattr(GL, 'glGetIntegerv', boom)
        assert ShadowCapabilities._query_vram_mb({'GL_NVX_gpu_memory_info'}) == 0


class TestListExtensions:
    def test_context_extension_manager_decodes_names(self):
        """A context ExtensionManager supplies the names directly; bytes are
        decoded and str names pass through."""
        class _Exts:
            def listGL(self):
                return [b'GL_ARB_texture_gather', 'GL_ARB_depth_clamp']

        class _Ctx:
            extensions = _Exts()

        result = ShadowCapabilities._list_extensions(_Ctx())
        assert result == {'GL_ARB_texture_gather', 'GL_ARB_depth_clamp'}

    def test_context_extension_manager_failure_falls_through(self, monkeypatch):
        """A context whose ExtensionManager.listGL() raises must not crash;
        detection falls back to the core-profile enumeration."""
        import OpenGL.GL as GL

        class _Exts:
            def listGL(self):
                raise RuntimeError("broken extension manager")

        class _Ctx:
            extensions = _Exts()

        # Force the glGetStringi fallback to also fail so we get a clean set().
        def boom(*a, **k):
            raise RuntimeError("no GL")

        monkeypatch.setattr(GL, 'glGetIntegerv', boom)
        result = ShadowCapabilities._list_extensions(_Ctx())
        assert result == set()

    def test_fallback_enumeration_failure_returns_empty(self, monkeypatch):
        import OpenGL.GL as GL

        def boom(*a, **k):
            raise RuntimeError("no GL")

        monkeypatch.setattr(GL, 'glGetIntegerv', boom)
        assert ShadowCapabilities._list_extensions(None) == set()


class TestDetectErrorPaths:
    def test_unit_query_failure_defaults_to_16(self, monkeypatch):
        """If GL_MAX_TEXTURE_IMAGE_UNITS can't be read, detect assumes 16."""
        import OpenGL.GL as GL
        monkeypatch.setattr(GL, 'glGetString', lambda enum: b"3.3.0 NVIDIA")

        def boom(enum):
            raise RuntimeError("no GL")

        monkeypatch.setattr(GL, 'glGetIntegerv', boom)
        caps = ShadowCapabilities.detect(None)
        assert caps.max_texture_units == 16
        assert caps.gl_version == (3, 3)

    def test_total_failure_uses_baseline(self, monkeypatch):
        """A GL query that raises outright degrades to the default 3.3 caps."""
        import OpenGL.GL as GL

        def boom(enum):
            raise RuntimeError("no context")

        monkeypatch.setattr(GL, 'glGetString', boom)
        caps = ShadowCapabilities.detect(None)
        # cls() baseline
        assert caps.gl_version == (3, 3)
        assert caps.max_texture_units == 16
        assert caps.has_cube_shadow is True


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
