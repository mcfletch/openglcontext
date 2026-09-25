"""PBRMaterial edits invalidate the cached std140 UBO.

The PBR pass caches each material's packed uniform block keyed on
``material.factorVersion``. Setting a factor the block holds
(`material.roughness = 0.3`) moves the version, and so does
``factorsChanged()``, which a caller editing a factor in place calls.
"""
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial


class TestUboVersionBump:
    def test_factor_edit_bumps_version(self):
        m = PBRMaterial()
        before = m.factorVersion
        m.roughness = 0.25
        assert m.factorVersion > before

    def test_each_edit_bumps_again(self):
        m = PBRMaterial()
        m.metallic = 0.1
        v1 = m.factorVersion
        m.metallic = 0.2
        assert m.factorVersion > v1

    def test_color_and_extension_factors_bump(self):
        m = PBRMaterial()
        v = m.factorVersion
        m.baseColor = (0.1, 0.2, 0.3)
        assert m.factorVersion > v
        v = m.factorVersion
        m.transmission = 0.5
        assert m.factorVersion > v

    def test_unrelated_attribute_does_not_bump(self):
        m = PBRMaterial()
        m.roughness = 0.5
        v = m.factorVersion
        m.not_a_material_field = 'x'
        assert m.factorVersion == v

    def test_an_edit_made_in_place_is_announced(self):
        """A texture transform's component written into its array is not a set."""
        m = PBRMaterial(uv_transform=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                                      [0.0, 0.0, 1.0]])
        v = m.factorVersion
        m.uv_transform[0][2] = 0.5
        assert m.factorVersion == v
        m.factorsChanged()
        assert m.factorVersion > v

    def test_the_batching_version_follows_it(self):
        m = PBRMaterial()
        before = m.batchingVersion()
        m.factorsChanged()
        assert m.batchingVersion() != before

    def test_pbrpass_cache_repacks_after_edit(self):
        # The pass keys its cache on (buffer, version); a bumped version must make
        # the cached entry stale. Exercise that comparison without GL.
        m = PBRMaterial()
        cache = {}
        cache[m] = ('OLD_BUFFER', m.factorVersion)
        m.roughness = 0.9
        entry = cache.get(m)
        assert entry is not None and entry[1] != m.factorVersion, \
            "a factor edit must make the cached UBO entry stale"
