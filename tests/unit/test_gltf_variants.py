"""KHR_materials_variants: a document's material variants, selected at run time.

Documents are built in the test; the Khronos MaterialVariantsShoe sample is
read where the network allows.
"""
import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.gltf import GLTFWriter, SceneNode, load_gltf, load_gltf_url
from OpenGLContext.loaders.gltf.writer import _pack_glb
from OpenGLContext.testing.network import unreachable

RED, GREEN, BLUE = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
TRIANGLE = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)


def _material(colour, double_sided=False):
    material = {'pbrMetallicRoughness': {'baseColorFactor': list(colour) + [1.0]},
                'extensions': {'KHR_materials_unlit': {}}}
    if double_sided:
        material['doubleSided'] = True
    return material


def _variant_document(names=('Green', 'Blue', 'Unmapped'), nodes=1, scale=(1, 1, 1),
                      offset=(0, 0, 0)):
    """One unlit triangle, red by default; variant 0 maps it green and variant 1
    blue (double-sided). Each of ``nodes`` nodes draws the same mesh."""
    blob = TRIANGLE.tobytes()
    doc = {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['KHR_materials_variants'],
        'extensions': {'KHR_materials_variants': {
            'variants': [{'name': name} for name in names]}},
        'scene': 0, 'scenes': [{'nodes': list(range(nodes))}],
        'nodes': [{'mesh': 0, 'scale': list(scale),
                   'translation': [offset[0] + 2.0 * n, offset[1], offset[2]]}
                  for n in range(nodes)],
        'meshes': [{'primitives': [{
            'attributes': {'POSITION': 0}, 'material': 0,
            'extensions': {'KHR_materials_variants': {'mappings': [
                {'material': 1, 'variants': [0]},
                {'material': 2, 'variants': [1]}]}}}]}],
        'materials': [_material(RED), _material(GREEN), _material(BLUE, True)],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'type': 'VEC3',
                       'count': 3, 'min': [0, 0, 0], 'max': [1, 1, 0]}],
        'bufferViews': [{'buffer': 0, 'byteLength': len(blob)}],
        'buffers': [{'byteLength': len(blob)}],
    }
    return _pack_glb(doc, blob)


def _shapes(scene):
    found, stack = [], [scene.group]
    while stack:
        node = stack.pop()
        if getattr(node, 'geometry', None) is not None:
            found.append(node)
        stack.extend(getattr(node, 'children', None) or [])
    return found


def _colour(shape):
    material = shape.appearance.material         # an UnlitMaterial
    return tuple(round(float(v), 3) for v in material.emissiveColor)


class TestSelecting:
    def test_variant_names_in_document_order(self):
        scene = load_gltf(_variant_document())
        assert scene.variants == ('Green', 'Blue', 'Unmapped')
        assert scene.variant is None

    def test_default_material_before_any_selection(self):
        (shape,) = _shapes(load_gltf(_variant_document()))
        assert _colour(shape) == RED

    def test_selecting_a_variant_dresses_the_primitive(self):
        scene = load_gltf(_variant_document())
        (shape,) = _shapes(scene)
        scene.select_variant('Green')
        assert scene.variant == 'Green'
        assert _colour(shape) == GREEN
        assert shape.geometry.appearance is shape.appearance

    def test_a_variant_the_primitive_does_not_map_falls_back(self):
        scene = load_gltf(_variant_document())
        (shape,) = _shapes(scene)
        scene.select_variant('Blue')
        scene.select_variant('Unmapped')
        assert _colour(shape) == RED

    def test_selecting_none_restores_the_default(self):
        scene = load_gltf(_variant_document())
        (shape,) = _shapes(scene)
        scene.select_variant('Blue')
        scene.select_variant(None)
        assert scene.variant is None
        assert _colour(shape) == RED

    def test_selecting_by_index(self):
        scene = load_gltf(_variant_document())
        (shape,) = _shapes(scene)
        scene.select_variant(1)
        assert scene.variant == 'Blue' and _colour(shape) == BLUE

    def test_double_sidedness_follows_the_variant(self):
        scene = load_gltf(_variant_document())
        (shape,) = _shapes(scene)
        assert shape.geometry.solid
        scene.select_variant('Blue')
        assert not shape.geometry.solid
        scene.select_variant(None)
        assert shape.geometry.solid

    @pytest.mark.parametrize('variant', ['Purple', 3, -1, 1.0])
    def test_an_unknown_variant_is_refused(self, variant):
        scene = load_gltf(_variant_document())
        with pytest.raises((KeyError, IndexError, TypeError)):
            scene.select_variant(variant)
        assert scene.variant is None

    def test_every_node_drawing_the_mesh_changes(self):
        scene = load_gltf(_variant_document(nodes=3))
        scene.select_variant('Green')
        assert {_colour(shape) for shape in _shapes(scene)} == {GREEN}

    def test_a_document_without_variants(self):
        doc = _variant_document(names=())
        scene = load_gltf(doc)
        assert scene.variants == ()
        with pytest.raises(KeyError):
            scene.select_variant('Green')

    def test_a_mapping_naming_a_missing_variant_or_material_is_skipped(self, caplog):
        import json
        glb = bytearray(_variant_document())
        length = int.from_bytes(glb[12:16], 'little')
        doc = json.loads(bytes(glb[20:20 + length]))
        blob = bytes(glb[28 + length:])
        doc['meshes'][0]['primitives'][0]['extensions']['KHR_materials_variants'][
            'mappings'] = [{'material': 9, 'variants': [0]},
                           {'material': 1, 'variants': [7, 2]}]
        scene = load_gltf(_pack_glb(doc, blob))
        (shape,) = _shapes(scene)
        scene.select_variant('Green')
        assert _colour(shape) == RED
        scene.select_variant('Unmapped')
        assert _colour(shape) == GREEN
        assert 'KHR_materials_variants' in caplog.text


def test_the_drawn_frame_follows_the_selection(gl_context):
    from OpenGLContext.testing.scenes import drawn_image, scene_context
    # A triangle large enough to cover the middle of the default view.
    scene = load_gltf(_variant_document(scale=(20, 20, 1), offset=(-5, -5, 0)))
    with scene_context([scene.group], size=(32, 32)) as context:
        drawn_image(context)
        before = drawn_image(context)[16, 16].astype(int)
        scene.select_variant('Green')
        after = drawn_image(context)[16, 16].astype(int)
    assert before[0] > 200 and before[1] < 50
    assert after[1] > 200 and after[0] < 50


class TestWriting:
    def test_variants_round_trip_through_the_writer(self):
        (shape,) = _shapes(load_gltf(_variant_document()))
        writer = GLTFWriter()
        writer.add_node(SceneNode(mesh=shape.geometry))
        document = writer.document()
        assert 'KHR_materials_variants' in document['extensionsUsed']
        assert [v['name'] for v in
                document['extensions']['KHR_materials_variants']['variants']] == [
            'Green', 'Blue']
        again = load_gltf(writer.to_glb())
        (written,) = _shapes(again)
        assert _colour(written) == RED
        again.select_variant('Blue')
        assert _colour(written) == BLUE and not written.geometry.solid

    def test_the_default_is_written_whichever_variant_is_selected(self):
        scene = load_gltf(_variant_document())
        (shape,) = _shapes(scene)
        scene.select_variant('Green')
        writer = GLTFWriter()
        writer.add_node(SceneNode(mesh=shape.geometry))
        again = load_gltf(writer.to_glb())
        assert _colour(_shapes(again)[0]) == RED

    def test_a_mesh_without_variants_writes_no_extension(self):
        doc = _variant_document(names=())
        (shape,) = _shapes(load_gltf(doc))
        writer = GLTFWriter()
        writer.add_node(SceneNode(mesh=shape.geometry))
        assert 'KHR_materials_variants' not in writer.document().get('extensionsUsed', [])


@pytest.mark.network
def test_khronos_materials_variants_shoe(tmp_path):
    url = ('https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/'
           'Models/MaterialsVariantsShoe/glTF-Binary/MaterialsVariantsShoe.glb')
    reason = unreachable(url, str(tmp_path))
    if reason:
        pytest.skip(reason)
    scene = load_gltf_url(url, str(tmp_path))
    assert scene.variants == ('midnight', 'beach', 'street')
    shapes = _shapes(scene)
    dressed = []
    for name in scene.variants:
        scene.select_variant(name)
        dressed.append([shape.appearance for shape in shapes])
    for first, second in ((0, 1), (1, 2), (0, 2)):
        assert any(a is not b for a, b in zip(dressed[first], dressed[second]))
