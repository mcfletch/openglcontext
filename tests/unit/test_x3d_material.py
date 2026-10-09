"""X3D 4's Material, with its texture fields, drawn by the PBR pass.

`diffuseTexture`, `emissiveTexture`, `normalTexture` and `occlusionTexture`
are the base colour, emissive, normal and occlusion maps, each with its
`...TextureMapping` label; without a `diffuseTexture`, the appearance's
`texture` is the base colour map, as in VRML97.
"""
import numpy as np
from vrml.x3d import nodes as x3d

from OpenGLContext.passes.pbrpass import _material_factors
from OpenGLContext.scenegraph.basenodes import Appearance, ImageTexture, Material
from OpenGLContext.scenegraph.physicalmaterial import pbr_material
from OpenGLContext.scenegraph.texturemapping import CHANNELS, texture_mapping


def unpack(mapping, channel):
    index = CHANNELS.index(channel)
    code = (mapping.codes[index // 6] >> (5 * (index % 6))) & 31
    return code & 3, code >> 2


class TestTheMaps:
    def test_each_texture_field_is_its_channel(self):
        maps = {name: ImageTexture() for name in
                ('diffuseTexture', 'emissiveTexture', 'normalTexture', 'occlusionTexture')}
        look = Appearance(material=Material(**maps))
        found = pbr_material(look).textures
        assert found == {'baseColor': maps['diffuseTexture'], 'emissive': maps['emissiveTexture'],
                         'normal': maps['normalTexture'], 'occlusion': maps['occlusionTexture']}

    def test_the_appearances_texture_is_the_base_colour_without_a_diffuse_texture(self):
        texture = ImageTexture()
        look = Appearance(material=Material(), texture=texture)
        found = pbr_material(look).textures
        assert found == {'baseColor': texture}

    def test_a_diffuse_texture_is_the_base_colour_over_the_appearances(self):
        diffuse = ImageTexture()
        look = Appearance(material=Material(diffuseTexture=diffuse), texture=ImageTexture())
        found = pbr_material(look).textures
        assert found['baseColor'] is diffuse

    def test_a_texture_set_later_is_read(self):
        material = Material()
        look = Appearance(material=material)
        view = pbr_material(look)
        normal = ImageTexture()
        material.normalTexture = normal
        assert view.textures == {'normal': normal}


class TestTheMappingLabels:
    def test_a_channel_reads_the_coordinate_set_its_label_names(self):
        material = Material(normalTexture=ImageTexture(), normalTextureMapping='TEXCOORD_1',
                            diffuseTexture=ImageTexture())
        look = Appearance(material=material)
        found = texture_mapping(look, None)
        assert unpack(found, 'normal') == (1, 0)
        assert unpack(found, 'baseColor') == (0, 0)

    def test_a_channel_reads_the_transform_its_label_names(self):
        material = Material(diffuseTexture=ImageTexture(), diffuseTextureMapping='moving')
        shift = x3d.TextureTransformMatrix3D(mapping='moving', matrix=np.array(
            [[1, 0, 0, 0.5], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], 'f'))
        appearance = Appearance(material=material, textureTransform=x3d.MultiTextureTransform(
            textureTransform=[shift]))
        found = texture_mapping(appearance, None)
        assert unpack(found, 'baseColor') == (0, 1)
        assert np.allclose(found.transforms[0], [[1, 0, 0.5], [0, 1, 0]])


def test_normal_scale_and_occlusion_strength_are_factors():
    look = Appearance(material=Material(normalScale=0.5, occlusionStrength=0.25))
    factors = _material_factors(pbr_material(look))
    assert factors['normal_scale'] == 0.5
    assert factors['occlusion'] == 0.25


class TestThePhongMaps:
    """ambientTexture, shininessTexture and specularTexture, under X3D's lighting

    The Phong program reads them through the samplers a Phong draw leaves
    free: the lightmap's, the metallic/roughness map's and the specular
    colour map's (``pbr.frag``).
    """

    @staticmethod
    def maps():
        return {name: ImageTexture() for name in
                ('ambientTexture', 'shininessTexture', 'specularTexture')}

    def test_each_is_a_channel_under_x3ds_lighting(self):
        from OpenGLContext import lighting  # noqa: PLC0415 kept with its use
        maps = self.maps()
        look = Appearance(material=Material(**maps))
        lighting.use('x3d')
        try:
            found = pbr_material(look).textures
        finally:
            lighting.use('auto')
        assert found == {'lightmap': maps['ambientTexture'],
                         'metallicRoughness': maps['shininessTexture'],
                         'specularColor': maps['specularTexture']}

    def test_none_is_read_under_the_engines_lighting(self):
        from OpenGLContext import lighting  # noqa: PLC0415 kept with its use
        lighting.use('engine')
        try:
            assert pbr_material(Appearance(material=Material(**self.maps()))).textures == {}
        finally:
            lighting.use('auto')

    def test_each_reads_its_mapping_label(self):
        from OpenGLContext import lighting  # noqa: PLC0415 kept with its use
        material = Material(ambientTexture=ImageTexture(), ambientTextureMapping='TEXCOORD_1',
                            specularTexture=ImageTexture())
        lighting.use('x3d')
        try:
            found = texture_mapping(Appearance(material=material), None)
        finally:
            lighting.use('auto')
        assert unpack(found, 'lightmap') == (1, 0)
        assert unpack(found, 'specularColor') == (0, 0)
