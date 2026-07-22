"""Texture-sampler-budget gating for KHR extension textures (no GL).

The PBR uber-shader's core maps + shadows + IBL fill the 16-unit GL 3.3 minimum;
extension textures (transmission / iridescence-thickness / ...) live at units 16+
and must be gated on GL_MAX_TEXTURE_IMAGE_UNITS so a 16-unit min-spec GPU (or
llvmpipe) still compiles and renders -- just without those extras.
"""
import pytest

from OpenGLContext.passes import pbrpass


class TestExtTextureGating:
    def test_min_spec_16_units_disables_extension_textures(self):
        assert pbrpass.ext_texture_channels(16) == {}
        assert pbrpass.ext_textures_supported(16) is False

    def test_capable_gpu_enables_extension_textures(self):
        chans = pbrpass.ext_texture_channels(32)
        assert 'transmission' in chans
        assert chans['transmission'] == 16
        assert pbrpass.ext_textures_supported(32) is True

    def test_partial_budget_enables_only_fitting_channels(self):
        # a budget of 17 admits only the unit-16 channel, not unit-17+
        chans = pbrpass.ext_texture_channels(17)
        assert set(chans) == {'transmission'}

    def test_every_ext_channel_has_sampler_and_flag_names(self):
        for chan in pbrpass.PBR_EXT_UNITS:
            assert chan in pbrpass._PBR_EXT_SAMPLER
            assert chan in pbrpass._PBR_EXT_HAS

    def test_ext_units_do_not_collide_with_core_units(self):
        core = set(pbrpass.PBR_UNITS.values())
        ext = set(pbrpass.PBR_EXT_UNITS.values())
        assert core.isdisjoint(ext)
        assert min(ext) >= 16          # all extension units are above the min-spec block


def _has_network():
    import urllib.request
    from OpenGLContext.loaders import gltf
    try:
        urllib.request.urlopen(gltf.SAMPLE_MODELS_BASE + '/README.md', timeout=6).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_network(), reason="needs network for sample models")
class TestExtTextureLoaderParse:
    def _materials(self, name):
        from OpenGLContext.loaders import gltf
        scene = gltf.load_sample(name)
        out = []

        def find(n):
            ap = getattr(n, 'appearance', None)
            if ap is not None and getattr(ap, 'material', None) is not None:
                out.append(ap.material)
            for c in getattr(n, 'children', []) or []:
                find(c)
        find(scene.group)
        return out

    def test_iridescence_thickness_texture_parsed(self):
        mats = self._materials('IridescenceSuzanne')
        assert any('iridescenceThickness' in getattr(m, 'textures', {}) for m in mats)

    def test_clearcoat_textures_parsed(self):
        mats = self._materials('ClearCoatTest')
        assert any('clearcoat' in getattr(m, 'textures', {}) for m in mats)
        assert any('clearcoatRoughness' in getattr(m, 'textures', {}) for m in mats)
