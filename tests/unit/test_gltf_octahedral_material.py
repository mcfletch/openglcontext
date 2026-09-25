"""A material that says it is an octahedral impostor is read as one.

The atlas travels as an ordinary base-colour texture, and what makes it an
impostor rather than a sticker is two numbers in the material's ``extras``:
how many views a side it holds and whether they are the upper hemisphere or
the whole sphere. A reader that does not know them draws a textured card, which
is why they are ``extras`` and not an extension -- and only a reader that
understood ``MSFT_lod`` reaches a chain's coarsest level at all.
"""
import base64
import json

import pytest
import numpy as np

from OpenGLContext.loaders import gltf


def _b64(data: bytes) -> str:
    return 'data:application/octet-stream;base64,' + base64.b64encode(data).decode()


def _document(extras=None):
    points = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], dtype='<f4')
    blob = points.tobytes()
    material = {'pbrMetallicRoughness': {'baseColorFactor': [1, 1, 1, 1]}}
    if extras is not None:
        material['extras'] = extras
    return {
        'asset': {'version': '2.0'},
        'buffers': [{'byteLength': len(blob), 'uri': _b64(blob)}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(blob)}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3,
                       'type': 'VEC3', 'min': [0, 0, 0], 'max': [1, 1, 0]}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0},
                                    'material': 0}]}],
        'materials': [material],
        'nodes': [{'mesh': 0}],
        'scenes': [{'nodes': [0]}],
        'scene': 0,
    }


def _material_of(tmp_path, document, name='impostor.gltf'):
    path = tmp_path / name
    path.write_text(json.dumps(document))
    scene = gltf.load_gltf(str(path))
    found = []

    def walk(node):
        appearance = getattr(node, 'appearance', None)
        if appearance is not None and getattr(appearance, 'material', None):
            found.append(appearance.material)
        for child in (getattr(node, 'children', None) or []):
            walk(child)
    walk(scene.sceneGraph)
    assert found, 'no material in the loaded scene'
    return found[0]


class TestAMaterialThatSaysItIsOne:
    def test_the_views_are_read(self, tmp_path):
        material = _material_of(tmp_path, _document(
            {'octahedralViews': 8, 'octahedralHemi': True}))

        assert material.octahedralViews == 8

    def test_the_layout_is_read(self, tmp_path):
        material = _material_of(tmp_path, _document(
            {'octahedralViews': 8, 'octahedralHemi': False}))

        # A VRML SFBool field holds 0/1 rather than a Python bool.
        assert not material.octahedralHemi

    def test_the_hemisphere_is_the_default(self, tmp_path):
        material = _material_of(tmp_path, _document({'octahedralViews': 4}))

        assert material.octahedralHemi


class TestAMaterialThatDoesNot:
    def test_an_ordinary_material_is_not_an_impostor(self, tmp_path):
        material = _material_of(tmp_path, _document())

        assert material.octahedralViews == 0

    def test_other_extras_are_stepped_over(self, tmp_path):
        material = _material_of(tmp_path, _document({'author': 'someone'}))

        assert material.octahedralViews == 0

    def test_one_view_is_not_an_atlas(self, tmp_path):
        """A single picture is an ordinary textured card."""
        material = _material_of(tmp_path, _document({'octahedralViews': 1}))

        assert material.octahedralViews == 0

    def test_a_count_that_is_not_a_number_is_refused_and_said(
            self, tmp_path, caplog):
        material = _material_of(tmp_path, _document(
            {'octahedralViews': 'lots'}))

        assert material.octahedralViews == 0
        assert 'lots' in caplog.text


class TestALayoutWrittenAsText:
    """A Blender custom property is as often the string ``"false"`` as the
    boolean, and the two mean the same layout."""

    @pytest.mark.parametrize('written, hemisphere', [
        ('false', False), ('False', False), ('0', False), ('no', False),
        ('true', True), ('yes', True), (0, False), (1, True),
    ])
    def test_the_layout_is_read_from_text(self, tmp_path, written, hemisphere):
        material = _material_of(tmp_path, _document(
            {'octahedralViews': 8, 'octahedralHemi': written}))

        assert bool(material.octahedralHemi) is hemisphere

    def test_a_layout_that_is_no_flag_is_the_hemisphere_and_said(
            self, tmp_path, caplog):
        material = _material_of(tmp_path, _document(
            {'octahedralViews': 8, 'octahedralHemi': 'upper'}))

        assert material.octahedralHemi
        assert 'upper' in caplog.text

    @pytest.mark.parametrize('views', [float('inf'), 1e999, 2.5, -8])
    def test_a_count_that_is_no_whole_number_is_no_impostor(self, tmp_path, views):
        document = _document({'octahedralViews': 8})
        document['materials'][0]['extras']['octahedralViews'] = views
        assert _material_of(tmp_path, document).octahedralViews == 0
