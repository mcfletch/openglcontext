"""Texture-sampler-budget gating for KHR extension textures (no GL).

The PBR uber-shader's core maps + shadows + IBL fill the 16-unit GL 3.3 minimum;
extension textures (transmission / iridescence-thickness / ...) live at units 16+
and must be gated on GL_MAX_TEXTURE_IMAGE_UNITS so a 16-unit min-spec GPU (or
llvmpipe) still compiles and renders -- just without those extras.
"""
import urllib.request
import pytest

from OpenGLContext.passes import pbrpass
from OpenGLContext.loaders import gltf


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
            assert chan in pbrpass._PBR_EXT_SAMPLER  # noqa: SLF001 the pass's channel tables, which the shader's samplers are held to
            assert chan in pbrpass._PBR_EXT_HAS  # noqa: SLF001 the pass's channel tables, which the shader's samplers are held to

    def test_ext_units_do_not_collide_with_core_units(self):
        core = set(pbrpass.PBR_UNITS.values())
        ext = set(pbrpass.PBR_EXT_UNITS.values())
        assert core.isdisjoint(ext)
        assert min(ext) >= 16          # all extension units are above the min-spec block


def _has_network():
    try:
        urllib.request.urlopen(gltf.SAMPLE_MODELS_BASE + '/README.md', timeout=6).close()  # noqa: S310 a fixed https URL, asking whether the sample models can be reached
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _has_network(), reason="needs network for sample models")
class TestExtTextureLoaderParse:
    def _materials(self, name):
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


class TestDrawSlots:
    """Which samplers a draw borrows for a Phong specular map and 2D layers"""

    def test_a_phong_draw_on_sixteen_samplers_frees_three(self):
        found = pbrpass.draw_slots((), (), phong=True, specular=False)
        assert found == pbrpass.DrawSlots(None, (0, pbrpass.SLOT_LIGHTMAP,
                                                 pbrpass.SLOT_METALLIC_ROUGHNESS,
                                                 pbrpass.SLOT_BRDF))

    def test_a_physical_draw_frees_only_the_lightmaps(self):
        found = pbrpass.draw_slots(('metallicRoughness',), (), phong=False, specular=False)
        assert found.layers == (0, pbrpass.SLOT_LIGHTMAP)

    def test_a_sampled_lightmap_is_not_lent(self):
        assert pbrpass.draw_slots(('lightmap',), (), False, False).layers == (0,)

    def test_the_specular_map_takes_the_first_free_sampler(self):
        found = pbrpass.draw_slots(('lightmap', 'metallicRoughness'), (), True, True)
        assert found == pbrpass.DrawSlots(pbrpass.SLOT_BRDF, (0,))

    def test_the_specular_map_has_its_own_sampler_with_the_extension_maps(self):
        ext = pbrpass.ext_texture_channels(32)
        found = pbrpass.draw_slots((), ext, True, True)
        assert found.specular is None
        assert found.layers[:4] == (0, 1, 2, 3)
