"""Alpha on the Appearance, sidedness on the geometry, unlit as UnlitMaterial.

X3D 4 puts a surface's alpha treatment on its `Appearance` (`alphaMode`,
`alphaCutoff`), its sidedness on the geometry's `solid`, and unlit shading in
its own material node. glTF puts all three on the material, so the glTF loader
and writer translate between the two.
"""
import json

import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf.writer import write_glb
from OpenGLContext.passes import pbrpass
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.imagedata import ImageDataTexture
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.physicalmaterial import (
    PhysicalMaterial, appearance_alpha, pbr_material,
)
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.unlitmaterial import UnlitMaterial

TRIANGLE = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]


def appearance(material=None, **named):
    return basenodes.Appearance(material=material or PhysicalMaterial(), **named)


def shapes(scene):
    found, stack = [], [scene.group]
    while stack:
        node = stack.pop()
        if isinstance(node, Shape):
            found.append(node)
        stack.extend(getattr(node, 'children', None) or ())
    return found


def round_trip(*meshes):
    return shapes(gltf.load_gltf(write_glb(list(meshes) if len(meshes) > 1 else meshes[0])))


class TestTheMaterialCarriesNone:
    @pytest.mark.parametrize('name', ['alphaMode', 'alphaCutoff', 'doubleSided', 'unlit'])
    def test_physical_material_has_no(self, name):
        assert not hasattr(PhysicalMaterial, name)


class TestAppearanceAlpha:
    def test_auto_is_opaque_without_transparency(self):
        assert appearance_alpha(appearance()) == ('OPAQUE', 0.5)

    def test_auto_blends_a_transparent_material(self):
        found = appearance_alpha(appearance(PhysicalMaterial(transparency=0.5)))
        assert found == ('BLEND', 0.5)

    def test_an_explicit_mode_is_kept(self):
        found = appearance_alpha(appearance(alphaMode='MASK', alphaCutoff=0.3))
        assert found == ('MASK', pytest.approx(0.3))

    def test_opaque_ignores_transparency(self):
        found = appearance_alpha(appearance(PhysicalMaterial(transparency=0.5),
                                            alphaMode='OPAQUE'))
        assert found[0] == 'OPAQUE'

    def test_no_appearance_is_opaque(self):
        assert appearance_alpha(None) == ('OPAQUE', 0.5)


def _image(mode):
    from PIL import Image  # noqa: PLC0415 kept with its use
    return Image.new(mode, (2, 2))


class TestAutoReadsTheBaseTexturesAlpha:
    """X3D 4's AUTO blends a base colour texture with an alpha channel."""

    @pytest.mark.parametrize('mode, expected', [('RGBA', 'BLEND'), ('LA', 'BLEND'),
                                                ('RGB', 'OPAQUE'), ('L', 'OPAQUE')])
    def test_a_vrml97_image_texture(self, mode, expected):
        look = basenodes.Appearance(material=basenodes.Material(),
                                    texture=basenodes.ImageTexture(image=_image(mode)))
        assert appearance_alpha(look)[0] == expected

    @pytest.mark.parametrize('components, expected', [(4, 'BLEND'), (2, 'BLEND'),
                                                      (3, 'OPAQUE'), (1, 'OPAQUE')])
    def test_a_pixel_texture(self, components, expected):
        look = basenodes.Appearance(material=basenodes.Material(), texture=basenodes.PixelTexture(
            image=[1, 1, components, 0]))
        assert appearance_alpha(look)[0] == expected

    def test_a_physical_materials_base_texture(self):
        material = PhysicalMaterial(baseTexture=ImageDataTexture(image=_image('RGBA')))
        assert appearance_alpha(appearance(material))[0] == 'BLEND'

    def test_another_channels_alpha_is_not_read(self):
        material = PhysicalMaterial(emissiveTexture=ImageDataTexture(image=_image('RGBA')))
        assert appearance_alpha(appearance(material))[0] == 'OPAQUE'

    def test_an_image_not_yet_loaded_is_opaque(self):
        look = basenodes.Appearance(material=basenodes.Material(), texture=basenodes.ImageTexture())
        assert appearance_alpha(look)[0] == 'OPAQUE'

    def test_an_explicit_opaque_ignores_the_alpha(self):
        material = PhysicalMaterial(baseTexture=ImageDataTexture(image=_image('RGBA')))
        assert appearance_alpha(appearance(material, alphaMode='OPAQUE'))[0] == 'OPAQUE'

    def test_the_texture_loading_changes_the_answer(self):
        texture = basenodes.ImageTexture()
        look = basenodes.Appearance(material=basenodes.Material(), texture=texture)
        assert appearance_alpha(look)[0] == 'OPAQUE'
        texture.image = _image('RGBA')
        assert appearance_alpha(look)[0] == 'BLEND'


class TestUnlitMaterial:
    def test_it_is_x3ds(self):
        from vrml.x3d import nodes as x3d
        assert issubclass(UnlitMaterial, x3d.UnlitMaterial)
        assert basenodes.UnlitMaterial is UnlitMaterial

    def test_its_emissive_texture_is_drawn_as_the_base_colour(self):
        texture = ImageDataTexture()
        material = UnlitMaterial(emissiveTexture=texture)
        assert material.textures == {'baseColor': texture}

    def test_the_pass_draws_it_unlit_in_its_emissive_colour(self):
        material = UnlitMaterial(emissiveColor=(0.2, 0.4, 0.6), transparency=0.25)
        assert pbr_material(appearance(material)) is material
        factors = pbrpass._material_factors(material)  # noqa: SLF001 the factor table the block is packed from
        assert factors['unlit'] == 1
        assert factors['base_color'] == pytest.approx((0.2, 0.4, 0.6))

    def test_a_set_field_moves_its_version(self):
        material = UnlitMaterial()
        before = material.factorVersion
        material.emissiveColor = (1, 0, 0)
        assert material.factorVersion != before


class TestAMeshCarriesAnAppearance:
    def test_a_mesh_takes_an_appearance(self):
        look = appearance(alphaMode='BLEND')
        mesh = PBRMesh(positions=TRIANGLE, appearance=look)
        assert mesh.appearance is look

    def test_a_blended_bare_mesh_sorts_as_transparent(self):
        mesh = PBRMesh(positions=TRIANGLE, appearance=appearance(alphaMode='BLEND'))
        assert mesh.sortKey(None, None)[0] is True

    def test_a_mesh_has_no_material_of_its_own(self):
        with pytest.raises(AttributeError):
            PBRMesh(positions=TRIANGLE, material=PhysicalMaterial())


class TestGLTF:
    def test_alpha_and_sidedness_survive_a_round_trip(self):
        mesh = PBRMesh(positions=TRIANGLE, solid=False,
                       appearance=appearance(alphaMode='MASK', alphaCutoff=0.25))
        shape = round_trip(mesh)[0]
        assert shape.appearance.alphaMode == 'MASK'
        assert shape.appearance.alphaCutoff == pytest.approx(0.25)
        assert shape.geometry.solid is False

    def test_the_written_material_says_what_glTF_says(self):
        mesh = PBRMesh(positions=TRIANGLE, solid=False,
                       appearance=appearance(alphaMode='BLEND'))
        document = _json(write_glb(mesh))
        assert document['materials'][0]['alphaMode'] == 'BLEND'
        assert document['materials'][0]['doubleSided'] is True

    def test_one_material_drawn_two_ways_is_two_glTF_materials(self):
        material = PhysicalMaterial()
        blended = PBRMesh(positions=TRIANGLE, appearance=appearance(material, alphaMode='BLEND'))
        opaque = PBRMesh(positions=TRIANGLE, appearance=appearance(material))
        assert len(_json(write_glb([blended, opaque]))['materials']) == 2

    def test_primitives_of_one_glTF_material_share_an_appearance(self):
        look = appearance(alphaMode='MASK')
        first = PBRMesh(positions=TRIANGLE, appearance=look)
        second = PBRMesh(positions=TRIANGLE, appearance=look)
        found = round_trip(first, second)
        assert found[0].appearance is found[1].appearance
        assert found[0].geometry.appearance is found[0].appearance

    def test_a_mask_material_keeps_its_base_alpha(self):
        mesh = PBRMesh(positions=TRIANGLE, appearance=appearance(
            PhysicalMaterial(transparency=0.25), alphaMode='MASK'))
        material = round_trip(mesh)[0].appearance.material
        assert material.transparency == pytest.approx(0.25)

    def test_unlit_survives_a_round_trip(self):
        mesh = PBRMesh(positions=TRIANGLE, appearance=appearance(
            UnlitMaterial(emissiveColor=(0.5, 0.25, 0.125))))
        document = _json(write_glb(mesh))
        assert 'KHR_materials_unlit' in document['materials'][0]['extensions']
        material = round_trip(mesh)[0].appearance.material
        assert isinstance(material, UnlitMaterial)
        assert tuple(material.emissiveColor) == pytest.approx((0.5, 0.25, 0.125))


def _json(glb):
    import struct  # noqa: PLC0415 kept with its one use
    length = struct.unpack_from('<I', glb, 12)[0]
    return json.loads(glb[20:20 + length])


class TestAnUnlitImpostor:
    """An impostor baked with its light is an unlit material with views."""

    def test_an_unlit_material_carries_impostor_views(self):
        material = UnlitMaterial(octahedralViews=8, octahedralHemi=False)
        assert (material.octahedralViews, material.octahedralHemi) == (8, False)

    def test_it_survives_a_glTF_round_trip(self):
        mesh = PBRMesh(positions=TRIANGLE, appearance=appearance(
            UnlitMaterial(octahedralViews=8)))
        material = round_trip(mesh)[0].appearance.material
        assert isinstance(material, UnlitMaterial)
        assert material.octahedralViews == 8
