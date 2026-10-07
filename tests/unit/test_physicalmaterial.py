"""PhysicalMaterial: the engine's PBR material is X3D's, with the glTF extensions.

No GL: the fields, the channel view the pass reads, the versions its caches key
on, and ImageDataTexture, the texture node for an image that arrives decoded.
"""
import importlib

import pytest
from PIL import Image

from vrml import node
from vrml.x3d import nodes as x3d

from OpenGLContext.passes.pbrpass import PBR_EXT_UNITS, PBR_UNITS
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.imagedata import ImageDataTexture
from OpenGLContext.scenegraph.physicalmaterial import (
    CHANNEL_FIELDS, PhysicalMaterial, pbr_material,
)


def image(colour=(10, 128, 30, 255), size=(4, 4)):
    return Image.new('RGBA', size, colour)


class TestTheNode:
    def test_it_is_x3ds_physical_material(self):
        assert issubclass(PhysicalMaterial, x3d.PhysicalMaterial)
        assert PhysicalMaterial.PROTO == 'PhysicalMaterial'
        assert basenodes.PhysicalMaterial is PhysicalMaterial

    def test_its_defaults_are_x3ds(self):
        material = PhysicalMaterial()
        assert tuple(material.baseColor) == (1.0, 1.0, 1.0)
        assert (material.metallic, material.roughness) == (1.0, 1.0)
        assert material.baseTexture is node.NULL
        assert material.baseTextureMapping == ''

    def test_the_old_name_is_gone(self):
        with pytest.raises(ImportError):
            importlib.import_module('OpenGLContext.scenegraph.pbrmaterial')
        assert not hasattr(basenodes, 'PBRMaterial')

    def test_it_goes_in_an_appearance(self):
        material = PhysicalMaterial()
        appearance = basenodes.Appearance(material=material)
        assert appearance.material is material
        assert pbr_material(appearance) is material


class TestTextureChannels:
    def test_every_channel_the_pass_binds_has_a_field(self):
        assert set(CHANNEL_FIELDS) == set(PBR_UNITS) | set(PBR_EXT_UNITS)
        for channel, name in CHANNEL_FIELDS.items():
            assert isinstance(getattr(PhysicalMaterial, name), node.SFNode), channel
            assert hasattr(PhysicalMaterial, name + 'Mapping'), channel

    def test_x3d_names_the_core_channels(self):
        assert CHANNEL_FIELDS['baseColor'] == 'baseTexture'
        assert CHANNEL_FIELDS['metallicRoughness'] == 'metallicRoughnessTexture'
        assert CHANNEL_FIELDS['normal'] == 'normalTexture'
        assert CHANNEL_FIELDS['occlusion'] == 'occlusionTexture'
        assert CHANNEL_FIELDS['emissive'] == 'emissiveTexture'

    def test_the_view_holds_the_set_fields_by_channel(self):
        base = ImageDataTexture(image=image())
        coat = ImageDataTexture(image=image())
        material = PhysicalMaterial(baseTexture=base, clearcoatTexture=coat)
        assert material.textures == {'baseColor': base, 'clearcoat': coat}
        assert material.texture('baseColor') is base
        assert material.texture('normal') is None

    def test_the_view_follows_the_fields(self):
        material = PhysicalMaterial()
        assert material.textures == {}
        texture = ImageDataTexture(image=image())
        material.normalTexture = texture
        assert material.textures == {'normal': texture}
        material.normalTexture = node.NULL
        assert material.textures == {}

    def test_the_view_is_not_assigned(self):
        with pytest.raises(AttributeError):
            PhysicalMaterial().textures = {}

    def test_an_image_texture_is_a_channel_too(self):
        texture = basenodes.ImageTexture(url=['stone.png'])
        material = PhysicalMaterial(baseTexture=texture)
        assert material.textures == {'baseColor': texture}


class TestVersions:
    def test_a_factor_moves_the_factor_version(self):
        material = PhysicalMaterial()
        before = material.factorVersion
        material.roughness = 0.25
        assert material.factorVersion != before

    def test_a_texture_moves_the_batching_version(self):
        material = PhysicalMaterial()
        before = material.batchingVersion()
        material.baseTexture = ImageDataTexture(image=image())
        assert material.batchingVersion() != before

    def test_a_mapping_moves_the_factor_version(self):
        material = PhysicalMaterial()
        before = material.factorVersion
        material.baseTextureMapping = 'TEXCOORD_1'
        assert material.factorVersion != before


class TestImageDataTexture:
    def test_it_is_an_x3d_2d_texture(self):
        assert issubclass(ImageDataTexture, x3d.X3DTexture2DNode)
        texture = ImageDataTexture(image=image())
        assert texture.repeatS and texture.repeatT
        assert texture.image.size == (4, 4)

    def test_mean_roughness_reads_the_green_channel(self):
        texture = ImageDataTexture(image=image((0, 51, 0, 255)))
        assert texture.mean_roughness() == pytest.approx(0.2)

    def test_a_new_image_is_measured_again(self):
        texture = ImageDataTexture(image=image((0, 51, 0, 255)))
        texture.mean_roughness()
        texture.image = image((0, 255, 0, 255))
        assert texture.mean_roughness() == pytest.approx(1.0)

    def test_the_measure_is_held_in_the_scenegraph_cache(self):
        from vrml import cache  # noqa: PLC0415 kept with its one use
        from OpenGLContext.scenegraph.imagedata import ROUGHNESS_KEY  # noqa: PLC0415 kept with its one use
        texture = ImageDataTexture(image=image((0, 51, 0, 255)))
        measured = texture.mean_roughness()
        assert cache.CACHE.getData(texture, ROUGHNESS_KEY) == measured

    def test_the_sampler_is_texture_properties(self):
        properties = x3d.TextureProperties(
            boundaryModeS='CLAMP_TO_EDGE', boundaryModeT='MIRRORED_REPEAT',
            minificationFilter='NEAREST_PIXEL', magnificationFilter='NEAREST_PIXEL')
        texture = ImageDataTexture(image=image(), textureProperties=properties)
        assert texture.sampler() == {
            'wrap_s': 'CLAMP_TO_EDGE', 'wrap_t': 'MIRRORED_REPEAT',
            'minification': 'NEAREST_PIXEL', 'magnification': 'NEAREST_PIXEL',
        }

    def test_without_properties_repeat_chooses_the_wrap(self):
        texture = ImageDataTexture(image=image(), repeatS=False)
        assert texture.sampler()['wrap_s'] == 'CLAMP_TO_EDGE'
        assert texture.sampler()['wrap_t'] == 'REPEAT'
