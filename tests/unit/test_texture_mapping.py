"""Which texture coordinates each material channel reads, and through which transform.

X3D names a texture's coordinates with a mapping label: the material's
`...TextureMapping` field names a coordinate set the geometry provides and a
transform the appearance's `textureTransform` provides. The pass reads one
`TextureMapping` per draw: a coordinate set and a transform slot per channel.
"""
import math
import os
import re

import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf.writer import write_glb
from OpenGLContext.scenegraph import texturemapping
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.imagedata import ImageDataTexture
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.texturemapping import (
    CHANNELS, MAX_TRANSFORMS, coordinate_set, texture_mapping, transform_for,
    transform_matrix,
)
from OpenGLContext.testing.memo import check_memo_inputs

QUAD = dict(
    positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], 'f'),
    texcoords=np.array([(0, 0), (1, 0), (1, 1), (0, 1)], 'f'),
    texcoords1=np.array([(0, 1), (1, 1), (1, 0), (0, 0)], 'f'),
    indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
)


def mesh(**named):
    return PBRMesh(**dict(QUAD, **named))


def textured(**mappings):
    """A material with every core channel textured, and the given mappings."""
    material = PhysicalMaterial()
    for channel in ('baseColor', 'metallicRoughness', 'normal', 'occlusion', 'emissive'):
        material.setTexture(channel, ImageDataTexture())
    for name, label in mappings.items():
        setattr(material, name, label)
    return material


def shifted(dx, mapping=''):
    """A TextureTransformMatrix3D moving coordinates by dx along s."""
    matrix = np.identity(4, 'f')
    matrix[0, 3] = dx
    return x3d.TextureTransformMatrix3D(matrix=matrix, mapping=mapping)


def unpack(mapping, channel):
    """(coordinate set, transform slot) of a channel from the packed codes."""
    index = CHANNELS.index(channel)
    code = (mapping.codes[index // 6] >> (5 * (index % 6))) & 31
    return code & 3, code >> 2


class TestCoordinateSets:
    def test_an_empty_label_is_the_first_set(self):
        assert coordinate_set(mesh(), '') == 0

    def test_a_texcoord_label_names_its_set(self):
        assert coordinate_set(mesh(), 'TEXCOORD_1') == 1

    def test_a_texcoord_label_with_a_suffix_names_the_same_set(self):
        assert coordinate_set(mesh(), 'TEXCOORD_1:2') == 1

    def test_an_unknown_label_is_the_first_set(self, caplog):
        assert coordinate_set(mesh(), 'bark') == 0

    def test_a_geometry_may_answer_for_itself(self):
        class Named:
            def textureCoordinateSet(self, label):
                return {'bark': 1}.get(label, 0)
        assert coordinate_set(Named(), 'bark') == 1


class TestTransforms:
    def test_no_transform(self):
        assert transform_for(Appearance(), '') is None

    def test_a_single_transform_with_no_mapping_applies_to_every_label(self):
        transform = x3d.TextureTransform(translation=(0.5, 0))
        appearance = Appearance(textureTransform=transform)
        assert transform_for(appearance, '') is transform
        assert transform_for(appearance, 'TEXCOORD_1') is transform

    def test_a_multi_transform_chooses_by_mapping(self):
        first, second = shifted(0.25, 'a'), shifted(0.5, 'b')
        appearance = Appearance(textureTransform=x3d.MultiTextureTransform(
            textureTransform=[first, second]))
        assert transform_for(appearance, 'b') is second
        assert transform_for(appearance, 'c') is None

    def test_a_matrix_transform_reads_as_its_affine_part(self):
        found = transform_matrix(shifted(0.25))
        assert found.shape == (2, 3)
        assert np.allclose(found, [[1, 0, 0.25], [0, 1, 0]])

    def test_a_vrml97_transform_reads_as_vrml97_composes_it(self):
        found = transform_matrix(x3d.TextureTransform(rotation=math.pi / 2,
                                                      translation=(0.5, 0)))
        # translate first, then rotate a quarter turn about the origin
        assert np.allclose(found @ [1, 0, 1], [0, 1.5], atol=1e-6)


class TestTheMapping:
    def test_by_default_every_channel_reads_the_first_set_untransformed(self):
        found = texture_mapping(Appearance(material=textured()), mesh())
        assert all(unpack(found, channel) == (0, 0) for channel in CHANNELS)

    def test_a_channel_reads_its_set_and_transform(self):
        material = textured(normalTextureMapping='TEXCOORD_1:0')
        appearance = Appearance(material=material, textureTransform=x3d.MultiTextureTransform(
            textureTransform=[shifted(0.25, 'TEXCOORD_1:0')]))
        found = texture_mapping(appearance, mesh())
        assert unpack(found, 'normal') == (1, 1)
        assert unpack(found, 'baseColor') == (0, 0)
        assert np.allclose(found.transforms[0], [[1, 0, 0.25], [0, 1, 0]])

    def test_channels_sharing_a_transform_share_a_slot(self):
        material = textured(baseTextureMapping='t', emissiveTextureMapping='t')
        appearance = Appearance(material=material, textureTransform=x3d.MultiTextureTransform(
            textureTransform=[shifted(0.25, 't')]))
        found = texture_mapping(appearance, mesh())
        assert unpack(found, 'baseColor') == unpack(found, 'emissive') == (0, 1)

    def test_past_four_transforms_the_rest_are_untransformed(self, caplog):
        labels = ['t%d' % index for index in range(MAX_TRANSFORMS + 1)]
        material = textured(**{name: label for name, label in zip(
            ('baseTextureMapping', 'metallicRoughnessTextureMapping', 'normalTextureMapping',
             'occlusionTextureMapping', 'emissiveTextureMapping'), labels)})
        appearance = Appearance(material=material, textureTransform=x3d.MultiTextureTransform(
            textureTransform=[shifted(0.1 * (index + 1), label) for index, label in enumerate(labels)]))
        found = texture_mapping(appearance, mesh())
        assert unpack(found, 'emissive')[1] == 0
        assert 'transforms' in caplog.text

    def test_a_vrml97_appearance_transforms_its_texture(self):
        appearance = Appearance(texture=x3d.ImageTexture(),
                                textureTransform=x3d.TextureTransform(scale=(2, 2)))
        found = texture_mapping(appearance, mesh())
        assert unpack(found, 'baseColor') == (0, 1)

    def test_the_mapping_follows_every_input(self):
        material = textured()
        transform = shifted(0.25, 't')
        appearance = Appearance(material=material, textureTransform=x3d.MultiTextureTransform(
            textureTransform=[transform]))
        geometry = mesh()

        def ask():
            return texture_mapping(appearance, geometry)

        check_memo_inputs(ask, [
            ('material.baseTextureMapping', lambda: setattr(material, 'baseTextureMapping', 't')),
            ('transform.matrix', lambda: setattr(transform, 'matrix', np.identity(4, 'f') * 2)),
            ('material.normalTexture', lambda: setattr(material, 'normalTextureMapping', 't')),
            ('appearance.textureTransform', lambda: setattr(
                appearance, 'textureTransform', shifted(0.5))),
        ], fresh=lambda: texturemapping._compute(appearance, geometry),  # noqa: SLF001 the computation the memo stands in front of
           same=lambda a, b: a.key == b.key)

    def test_the_back_faces_read_the_back_materials_mapping(self):
        back = textured(baseTextureMapping='TEXCOORD_1')
        appearance = Appearance(material=textured(), backMaterial=back)
        geometry = mesh()
        assert unpack(texture_mapping(appearance, geometry), 'baseColor')[0] == 0
        assert unpack(texture_mapping(appearance, geometry, back=True), 'baseColor')[0] == 1

        def ask():
            return texture_mapping(appearance, geometry, back=True)

        check_memo_inputs(ask, [
            ('backMaterial.baseTextureMapping', lambda: setattr(back, 'baseTextureMapping', '')),
            ('appearance.backMaterial', lambda: setattr(
                appearance, 'backMaterial', textured(baseTextureMapping='TEXCOORD_1'))),
        ], fresh=lambda: texturemapping._compute(appearance, geometry, back=True),  # noqa: SLF001 the computation the memo stands in front of
           same=lambda a, b: a.key == b.key)

    def test_the_mapping_follows_the_geometrys_coordinate_nodes(self):
        from OpenGLContext.scenegraph.meshgeometry import IndexedTriangleSet  # noqa: PLC0415 kept with its use
        material = textured(baseTextureMapping='detail')
        appearance = Appearance(material=material)
        first = x3d.TextureCoordinate(point=[(0, 0), (1, 0), (1, 1)])
        second = x3d.TextureCoordinate(point=[(0, 0), (2, 0), (2, 2)], mapping='detail')
        multiple = x3d.MultiTextureCoordinate(texCoord=[first, second])
        geometry = IndexedTriangleSet(
            index=[0, 1, 2], coord=x3d.Coordinate(point=[(0, 0, 0), (1, 0, 0), (1, 1, 0)]),
            texCoord=multiple)

        def ask():
            return texture_mapping(appearance, geometry)

        third = x3d.TextureCoordinate(mapping='detail')
        assert unpack(ask(), 'baseColor')[0] == 1
        check_memo_inputs(ask, [
            ('a coordinate node\'s mapping', lambda: setattr(first, 'mapping', 'detail')),
            ('the coordinate nodes', lambda: setattr(
                multiple, 'texCoord', [x3d.TextureCoordinate(), third])),
            ('a later coordinate node\'s mapping', lambda: setattr(third, 'mapping', 'other')),
            ('geometry.texCoord', lambda: setattr(geometry, 'texCoord', x3d.MultiTextureCoordinate(
                texCoord=[x3d.TextureCoordinate(), x3d.TextureCoordinate(mapping='detail')]))),
        ], fresh=lambda: texturemapping._compute(appearance, geometry),  # noqa: SLF001 the computation the memo stands in front of
           same=lambda a, b: a.key == b.key)


class TestGLTF:
    def test_a_transform_is_a_matrix_transform_named_by_the_channels_mapping(self):
        material = PhysicalMaterial(baseTexture=ImageDataTexture(image=_image()))
        material.baseTextureMapping = 'TEXCOORD_0'
        look = Appearance(material=material)
        look.textureTransform = x3d.MultiTextureTransform(textureTransform=[shifted(0.25, 'TEXCOORD_0')])
        shape = _round_trip(mesh(appearance=look))
        found = shape.appearance
        label = found.material.baseTextureMapping
        transform = transform_for(found, label)
        assert transform is not None
        assert np.allclose(transform_matrix(transform), [[1, 0, 0.25], [0, 1, 0]], atol=1e-6)

    def test_a_second_coordinate_set_survives_a_round_trip(self):
        material = PhysicalMaterial(normalTexture=ImageDataTexture(image=_image()))
        material.normalTextureMapping = 'TEXCOORD_1'
        shape = _round_trip(mesh(appearance=Appearance(material=material)))
        assert coordinate_set(shape.geometry, shape.appearance.material.normalTextureMapping) == 1


def _image():
    from PIL import Image  # noqa: PLC0415 kept with its one use
    return Image.new('RGBA', (2, 2), (255, 0, 0, 255))


def _round_trip(geometry):
    scene = gltf.load_gltf(write_glb(geometry))
    stack = [scene.group]
    while stack:
        node = stack.pop()
        if isinstance(node, Shape):
            return node
        stack.extend(getattr(node, 'children', None) or ())
    raise AssertionError('no shape')


class TestTheChannelOrder:
    """The shader numbers channels as texturemapping.CHANNELS does."""

    def test_it_is_the_pass_texture_order(self):
        from OpenGLContext.passes.pbrpass import PBR_EXT_UNITS, PBR_UNITS  # noqa: PLC0415 the pass is GL; the mapping is not
        assert CHANNELS == tuple(PBR_UNITS) + tuple(PBR_EXT_UNITS)

    def test_the_shader_numbers_them_alike(self):
        from OpenGLContext.passes.shadersource import SHADER_DIR  # noqa: PLC0415 the pass is GL; the mapping is not
        with open(os.path.join(SHADER_DIR, 'pbr.frag'), encoding='utf-8') as stream:
            source = stream.read()
        found = {name: int(number) for name, number in
                 re.findall(r'#define (CH_[A-Z_]+)\s+(\d+)', source)}
        expected = {'CH_' + re.sub(r'([A-Z])', r'_\1', channel).upper(): index
                    for index, channel in enumerate(CHANNELS)}
        assert found == expected


def test_no_appearance_reads_the_first_set_untransformed():
    from vrml.node import NULL  # noqa: PLC0415 kept with its one use
    assert texture_mapping(NULL, mesh()) is texturemapping.IDENTITY
    assert texture_mapping(None, mesh()) is texturemapping.IDENTITY


def test_a_transform_3d_moves_a_2d_maps_s_and_t():
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.texturemapping import transform_matrix  # noqa: PLC0415 kept with its use
    found = transform_matrix(x3d.TextureTransform3D(translation=(0.5, 0.25, 9), scale=(2, 1, 1)))
    flat = transform_matrix(x3d.TextureTransform(translation=(0.5, 0.25), scale=(2, 1)))
    assert np.allclose(found, flat)
    assert np.allclose(found, [[2, 0, 1.0], [0, 1, 0.25]])
