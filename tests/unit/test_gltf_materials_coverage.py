"""Coverage tests for glTF material construction edge paths.

The table-driven KHR extension handlers (unlit / emissive-strength / specular /
sheen / diffuse-transmission), the texture collector's None-holder and
KHR_texture_transform texCoord-override branches, and the archived
KHR_materials_pbrSpecularGlossiness conversion (factor-only, diffuse-texture
fallback, and the full per-pixel texture conversion). Materials are built through
the real ``_build_material`` against synthetic buffers -- no GL, no network.
"""
import io

import pytest

pygltflib = pytest.importorskip("pygltflib")
Image = pytest.importorskip("PIL.Image")
from pygltflib import (  # noqa: E402
    GLTF2, Material, PbrMetallicRoughness, TextureInfo,
    Image as GLTFImage, Texture, BufferView, Buffer,
)

from OpenGLContext.loaders.gltf import materials as gmat  # noqa: E402


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
            'KHR_materials_unlit': {},
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
        assert bool(mat.unlit) is True
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
        mat = gmat._build_material(g, 0, r, {})
        assert 'baseColor' in mat.textures
        assert mat.uv_transform is not None
        # UV set 1 for baseColor sets the low bit of the texCoord mask.
        assert mat._tex_coord_mask & 1


class TestSpecularGlossiness:
    def test_factor_only_conversion(self):
        # A metal authored in spec/gloss: white specular, no textures.
        g = GLTF2()
        g.materials = [Material(extensions={'KHR_materials_pbrSpecularGlossiness': {
            'diffuseFactor': [0.0, 0.0, 0.0, 1.0],
            'specularFactor': [1.0, 1.0, 1.0],
            'glossinessFactor': 1.0}})]
        mat = gmat._build_material(g, 0, _R(), {})
        # A bright white specular solves to high metalness; roughness = 1 - gloss.
        assert mat.metallic > 0.9
        assert abs(mat.roughness - 0.0) < 1e-6

    def test_diffuse_texture_fallback_when_no_specgloss_texture(self):
        g, r = _g_with_images([_png((10, 200, 10))])
        g.materials = [Material(extensions={'KHR_materials_pbrSpecularGlossiness': {
            'diffuseFactor': [1, 1, 1, 1],
            'specularFactor': [0.0, 0.0, 0.0],
            'glossinessFactor': 0.5,
            'diffuseTexture': {'index': 0}}})]
        mat = gmat._build_material(g, 0, r, {})
        # No spec/gloss image, so the diffuse map is added as the base colour map.
        assert 'baseColor' in mat.textures

    def test_full_texture_conversion_to_metalrough_maps(self):
        # A textured spec/gloss material converts per pixel to baseColor +
        # metallicRoughness maps (metalness lives in the spec/gloss image).
        g, r = _g_with_images([_png((120, 90, 60)), _png((220, 220, 220))])
        g.materials = [Material(extensions={'KHR_materials_pbrSpecularGlossiness': {
            'diffuseFactor': [1, 1, 1, 1],
            'specularFactor': [1, 1, 1],
            'glossinessFactor': 0.8,
            'diffuseTexture': {'index': 0},
            'specularGlossinessTexture': {'index': 1}}})]
        mat = gmat._build_material(g, 0, r, {})
        assert 'baseColor' in mat.textures
        assert 'metallicRoughness' in mat.textures
        # Factors just pass the maps through after a per-pixel conversion.
        assert mat.metallic == 1.0 and mat.roughness == 1.0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
