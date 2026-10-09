"""Coverage tests for glTF material construction edge paths.

The table-driven KHR extension handlers (unlit / emissive-strength / specular /
sheen / diffuse-transmission), the texture collector's None-holder and
KHR_texture_transform texCoord-override branches, and the archived
KHR_materials_pbrSpecularGlossiness, read as a SpecularGlossinessMaterial where
there is no metallic/roughness fallback. Materials are built through
the real ``_build_material`` against synthetic buffers -- no GL, no network.
"""
import io

import pytest

pygltflib = pytest.importorskip("pygltflib")
Image = pytest.importorskip("PIL.Image")
from pygltflib import (
    GLTF2, Material, PbrMetallicRoughness, TextureInfo,
    Image as GLTFImage, Texture, BufferView, Buffer,
)

from OpenGLContext.loaders.gltf import materials as gmat
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.specularglossiness import SpecularGlossinessMaterial


class _R:
    def __init__(self, data=b''):
        self._buffers = {0: data}


def _png(color=(180, 120, 60), size=(2, 2)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='PNG')
    return buf.getvalue()


def _g_with_images(pngs):
    """A GLTF2 whose buffer 0 holds ``pngs`` back to back, one image+texture each.

    Returns (g, resolver). Texture i samples image i.
    """
    g = GLTF2()
    g.images = []
    g.textures = []
    g.bufferViews = []
    blob = b''
    for i, png in enumerate(pngs):
        g.bufferViews.append(BufferView(buffer=0, byteOffset=len(blob),
                                        byteLength=len(png)))
        g.images.append(GLTFImage(bufferView=i, mimeType='image/png'))
        g.textures.append(Texture(source=i))
        blob += png
    g.buffers = [Buffer(byteLength=len(blob))]
    return g, _R(blob)


class TestExtensionHandlers:
    def test_factor_only_extension_handlers_run(self):
        g = GLTF2()
        g.materials = [Material(extensions={
            'KHR_materials_emissive_strength': {'emissiveStrength': 3.0},
            'KHR_materials_specular': {'specularFactor': 0.4,
                                       'specularColorFactor': [0.1, 0.2, 0.3]},
            'KHR_materials_sheen': {'sheenColorFactor': [0.5, 0.4, 0.3],
                                    'sheenRoughnessFactor': 0.6},
            'KHR_materials_diffuse_transmission': {
                'diffuseTransmissionFactor': 0.7,
                'diffuseTransmissionColorFactor': [0.2, 0.4, 0.6]},
        })]
        mat = gmat._build_material(g, 0, _R(), {})
        assert abs(mat.emissiveStrength - 3.0) < 1e-6
        assert abs(mat.specular - 0.4) < 1e-6
        assert tuple(round(float(x), 2) for x in mat.specularColor) == (0.1, 0.2, 0.3)
        assert abs(mat.sheenRoughness - 0.6) < 1e-6
        assert abs(mat.diffuseTransmission - 0.7) < 1e-6


class TestTextureCollector:
    def test_texture_with_no_source_yields_no_holder(self):
        # baseColorTexture points at a texture with no image source -> the holder is
        # None and the channel is not recorded.
        g = GLTF2()
        g.textures = [Texture()]        # no source
        g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
            baseColorTexture=TextureInfo(index=0)))]
        mat = gmat._build_material(g, 0, _R(), {})
        assert 'baseColor' not in getattr(mat, 'textures', {})

    def test_texture_transform_texcoord_override_sets_uv_set(self):
        g, r = _g_with_images([_png()])
        info = TextureInfo(index=0)
        info.extensions = {'KHR_texture_transform': {'texCoord': 1,
                                                     'offset': [0.1, 0.2],
                                                     'scale': [2, 2]}}
        g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
            baseColorTexture=info))]
        mat, transforms = gmat._material_and_transforms(g, 0, r, {})
        assert 'baseColor' in mat.textures
        # UV set 1, through the material's first transform.
        assert mat.baseTextureMapping == 'TEXCOORD_1:0'
        assert [t.mapping for t in transforms] == ['TEXCOORD_1:0']


class TestSpecularGlossiness:
    def test_without_metallic_roughness_it_is_a_specular_glossiness_material(self):
        g = GLTF2()
        g.materials = [Material(extensions={'KHR_materials_pbrSpecularGlossiness': {
            'diffuseFactor': [0.5, 0.25, 0.0, 0.5],
            'specularFactor': [1.0, 0.8, 0.4],
            'glossinessFactor': 0.75}}, alphaMode='BLEND')]
        g.materials[0].pbrMetallicRoughness = None
        mat = gmat._build_material(g, 0, _R(), {})
        assert isinstance(mat, SpecularGlossinessMaterial)
        assert list(mat.diffuseColor) == pytest.approx([0.5, 0.25, 0.0])
        assert list(mat.specularColor) == pytest.approx([1.0, 0.8, 0.4])
        assert mat.glossiness == pytest.approx(0.75)
        assert mat.transparency == pytest.approx(0.5)

    def test_its_maps_are_its_channels(self):
        g, r = _g_with_images([_png((120, 90, 60)), _png((220, 220, 220))])
        g.materials = [Material(extensions={'KHR_materials_pbrSpecularGlossiness': {
            'diffuseTexture': {'index': 0},
            'specularGlossinessTexture': {'index': 1, 'texCoord': 1}}})]
        g.materials[0].pbrMetallicRoughness = None
        mat = gmat._build_material(g, 0, r, {})
        assert mat.texture('baseColor') is not None
        assert mat.texture('specularColor') is not None
        assert mat.specularGlossinessTextureMapping == 'TEXCOORD_1'

    def test_a_metallic_roughness_fallback_is_drawn_in_its_place(self):
        g = GLTF2()
        g.materials = [Material(
            pbrMetallicRoughness=PbrMetallicRoughness(metallicFactor=0.25),
            extensions={'KHR_materials_pbrSpecularGlossiness': {'glossinessFactor': 0.5}})]
        mat = gmat._build_material(g, 0, _R(), {})
        assert isinstance(mat, PhysicalMaterial)
        assert mat.metallic == pytest.approx(0.25)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestAMalformedMaterialExtension:
    """A factor a document gets wrong costs that factor, reported, not the material."""

    def _built(self, extensions):
        g = GLTF2()
        g.materials = [Material(extensions=extensions)]
        return gmat._build_material(g, 0, _R(), {})

    def test_a_factor_that_is_not_a_number_takes_the_default(self, caplog):
        mat = self._built({'KHR_materials_ior': {'ior': 'glass'},
                           'KHR_materials_iridescence': {'iridescenceIor': float('nan')}})
        assert abs(mat.ior - 1.5) < 1e-6
        assert abs(mat.iridescenceIor - 1.3) < 1e-6
        assert 'ior' in caplog.text

    def test_a_factor_outside_its_range_is_held_to_it(self):
        mat = self._built({'KHR_materials_clearcoat': {'clearcoatFactor': 5.0,
                                                       'clearcoatRoughnessFactor': -1},
                           'KHR_materials_volume': {'thicknessFactor': -2,
                                                    'attenuationDistance': 'far'}})
        assert (float(mat.clearcoat), float(mat.clearcoatRoughness)) == (1.0, 0.0)
        assert (float(mat.thickness), float(mat.attenuationDistance)) == (0.0, gmat.NO_ATTENUATION)

    def test_a_texture_transform_with_a_bad_uv_set_uses_the_texture_s(self):
        g, r = _g_with_images([_png()])
        info = TextureInfo(index=0)
        info.extensions = {'KHR_texture_transform': {'texCoord': 'second',
                                                     'rotation': 'quarter'}}
        g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
            baseColorTexture=info))]
        mat, transforms = gmat._material_and_transforms(g, 0, r, {})
        assert mat.baseTextureMapping == 'TEXCOORD_0:0'
        assert len(transforms) == 1
