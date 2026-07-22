"""PBRMaterial edits invalidate the cached std140 UBO.

The PBR pass caches each material's packed uniform block keyed on
``material._ubo_version``. Nothing bumped that version on an in-place edit
(`material.roughness = 0.3`), so the pass would keep serving a stale block. A
`__setattr__` hook now bumps the version whenever a UBO-relevant factor changes.
"""
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial


class TestUboVersionBump:
    def test_factor_edit_bumps_version(self):
        m = PBRMaterial()
        before = getattr(m, '_ubo_version', 0)
        m.roughness = 0.25
        assert getattr(m, '_ubo_version', 0) > before

    def test_each_edit_bumps_again(self):
        m = PBRMaterial()
        m.metallic = 0.1
        v1 = m._ubo_version
        m.metallic = 0.2
        assert m._ubo_version > v1

    def test_color_and_extension_factors_bump(self):
        m = PBRMaterial()
        v = m._ubo_version
        m.baseColor = (0.1, 0.2, 0.3)
        assert m._ubo_version > v
        v = m._ubo_version
        m.transmission = 0.5
        assert m._ubo_version > v

    def test_unrelated_attribute_does_not_bump(self):
        m = PBRMaterial()
        m.roughness = 0.5
        v = m._ubo_version
        m._some_private = 123          # private/bookkeeping, not a UBO factor
        m.not_a_material_field = 'x'
        assert m._ubo_version == v

    def test_pbrpass_cache_repacks_after_edit(self):
        # The pass keys its cache on (buffer, version); a bumped version must make
        # the cached entry stale. Exercise that comparison without GL.
        m = PBRMaterial()
        cache = {}
        version = int(getattr(m, '_ubo_version', 0))
        cache[m] = ('OLD_BUFFER', version)
        m.roughness = 0.9
        new_version = int(getattr(m, '_ubo_version', 0))
        entry = cache.get(m)
        assert entry is not None and entry[1] != new_version, \
            "a factor edit must make the cached UBO entry stale"
