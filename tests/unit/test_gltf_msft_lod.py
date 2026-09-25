"""The glTF loader reads MSFT_lod as one node that switches between the levels.

A baked chain ships as a glb whose node carries ``MSFT_lod``: the node itself is
the finest level, ``ids`` names the coarser ones in decreasing detail, and
``MSFT_screencoverage`` says how much of the window each is worth drawing at.
This is the loader turning that into a
:class:`~OpenGLContext.scenegraph.lod.ScreenCoverageLOD` -- headless, no GL.

The minimal documents here are built by hand so the reader is held to the
extension as it is specified rather than to what this engine's writer happens to
emit. A chain written by the baking tools is loaded back in
``openglcontext-editor``'s own suite, where the writer lives.
"""
import base64
import json

import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.passes.instancing import geometry_instance_key
from OpenGLContext.scenegraph.lod import ScreenCoverageLOD
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.loaders.gltf.transforms import _local_matrix_rv

COVERAGE = [0.5, 0.2, 0.01]


def _b64(data: bytes) -> str:
    return 'data:application/octet-stream;base64,' + base64.b64encode(data).decode('ascii')


def _triangle(scale=1.0, offset=(0, 0, 0)):
    points = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], dtype='<f4') * scale
    return points + np.asarray(offset, dtype='<f4')


def _document(levels=3, coverage=COVERAGE, ids=None, scene_nodes=(0,), children=None):
    """A document of ``levels`` one-triangle meshes, the first carrying the extension."""
    meshes = [_triangle(scale=1.0 / (index + 1)) for index in range(levels)]
    blob = b''.join(mesh.tobytes() for mesh in meshes)
    node = {
        'mesh': 0,
        'extensions': {'MSFT_lod': {
            'ids': list(range(1, levels)) if ids is None else list(ids)}},
    }
    if coverage is not None:
        node['extras'] = {'MSFT_screencoverage': list(coverage)}
    if children is not None:
        node['children'] = list(children)
    nodes = [node] + [{'mesh': index} for index in range(1, levels)]
    nodes.extend({} for _ in range(len(nodes), max(scene_nodes, default=0) + 1))
    return {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['MSFT_lod'],
        'buffers': [{'byteLength': len(blob), 'uri': _b64(blob)}],
        'bufferViews': [
            {'buffer': 0, 'byteOffset': index * meshes[0].nbytes,
             'byteLength': meshes[0].nbytes}
            for index in range(levels)
        ],
        'accessors': [
            {'bufferView': index, 'componentType': 5126, 'count': 3, 'type': 'VEC3',
             'min': mesh.min(axis=0).tolist(), 'max': mesh.max(axis=0).tolist()}
            for index, mesh in enumerate(meshes)
        ],
        'meshes': [{'primitives': [{'attributes': {'POSITION': index}}]}
                   for index in range(levels)],
        'nodes': nodes,
        'scenes': [{'nodes': list(scene_nodes)}],
        'scene': 0,
    }


def _flatten(node, out=None):
    out = [] if out is None else out
    out.append(node)
    for child in getattr(node, 'children', None) or []:
        _flatten(child, out)
    for level in getattr(node, 'level', None) or []:
        _flatten(level, out)
    return out


def _loaded(tmp_path, document, name='lod.gltf'):
    path = tmp_path / name
    path.write_text(json.dumps(document))
    return gltf.load_gltf(str(path))


def _the_lod(scene):
    found = [n for n in _flatten(scene.group) if isinstance(n, ScreenCoverageLOD)]
    assert len(found) == 1, found
    return found[0]


def _shapes(node):
    return [n for n in _flatten(node) if isinstance(n, Shape)]


def _key(node, level):
    """What the pass would batch this level of ``node`` by."""
    return geometry_instance_key(_shapes(node.level[level])[0])


class TestReadingTheExtension:
    def test_the_levels_become_one_switching_node(self, tmp_path):
        node = _the_lod(_loaded(tmp_path, _document()))

        assert len(node.level) == 3

    def test_the_finest_level_is_the_node_that_carries_the_extension(self, tmp_path):
        """``ids`` names the alternatives; the node itself is level zero."""
        node = _the_lod(_loaded(tmp_path, _document()))

        positions = _shapes(node.level[0])[0].geometry.positions

        assert positions.max() == pytest.approx(1.0)

    def test_the_levels_are_in_the_order_the_file_named_them(self, tmp_path):
        node = _the_lod(_loaded(tmp_path, _document()))

        sizes = [_shapes(level)[0].geometry.positions.max() for level in node.level]

        assert sizes == pytest.approx([1.0, 0.5, 1.0 / 3.0])

    def test_the_coverages_are_what_the_file_said(self, tmp_path):
        node = _the_lod(_loaded(tmp_path, _document()))

        assert list(node.screenCoverage) == pytest.approx(COVERAGE)

    def test_a_file_that_names_no_coverage_gets_a_halving_series(self, tmp_path):
        """The extension calls coverage a hint, so a file may leave it out; the
        levels are still worth switching between."""
        node = _the_lod(_loaded(tmp_path, _document(coverage=None)))

        assert list(node.screenCoverage) == pytest.approx([0.5, 0.25, 0.0])

    def test_a_guessed_series_never_culls(self, tmp_path):
        """Vanishing an object is the file's decision, never the reader's."""
        node = _the_lod(_loaded(tmp_path, _document(coverage=None)))

        assert node.levelForCoverage(1e-9) == 2

    def test_the_object_is_measured_from_its_finest_level(self, tmp_path):
        """The accessor's own min/max, which is what they are written for."""
        node = _the_lod(_loaded(tmp_path, _document()))

        assert node.coverageRadius() == pytest.approx(np.sqrt(2.0) / 2.0)

    def test_the_distance_is_measured_to_the_geometry(self, tmp_path):
        """A model the file put far from its own origin is judged where it is."""
        document = _document()
        far = _triangle(offset=(100, 0, 0))
        document['accessors'][0]['min'] = far.min(axis=0).tolist()
        document['accessors'][0]['max'] = far.max(axis=0).tolist()

        node = _the_lod(_loaded(tmp_path, document))

        assert list(node.center) == pytest.approx([100.5, 0.5, 0.0])


class TestWhatElseTheNodeCarries:
    def test_a_child_of_the_node_is_drawn_at_every_level(self, tmp_path):
        """The extension offers alternatives for the node's own geometry. What
        hangs off it -- a light, a mounted object -- belongs to the node."""
        document = _document(levels=3, children=[3])
        document['nodes'].append({'mesh': 1})

        scene = _loaded(tmp_path, document)
        node = _the_lod(scene)

        assert len(_shapes(scene.group)) == len(_shapes(node)) + 1

    def test_an_alternative_listed_in_the_scene_is_still_drawn_once(self, tmp_path):
        """A level belongs to its LOD, wherever else the file mentions it."""
        scene = _loaded(tmp_path, _document(scene_nodes=(0, 1, 2)))

        assert len(_shapes(scene.group)) == 3

    def test_an_id_that_names_nothing_leaves_the_rest(self, tmp_path, caplog):
        scene = _loaded(tmp_path, _document(ids=[1, 99]))
        node = _the_lod(scene)

        assert len(node.level) == 2
        assert 'MSFT_lod' in caplog.text


class TestBatchingCopiesOfOneModel:
    """Two copies of a model drawing the same level batch into one draw.

    The pass groups opaque records by the geometry and appearance they share
    (:func:`OpenGLContext.passes.instancing.geometry_instance_key`), and the
    levels of a chain are decoded once and shared between every node that names
    them -- so two copies at the same level land in one instanced draw, and two
    copies at different levels are drawn separately, which is what drawing
    different geometry means.
    """

    def _two_copies(self, tmp_path):
        document = _document()
        document['nodes'].append({
            'mesh': 0,
            'extensions': {'MSFT_lod': {'ids': [1, 2]}},
            'extras': {'MSFT_screencoverage': COVERAGE},
        })
        document['scenes'][0]['nodes'] = [0, 3]
        scene = _loaded(tmp_path, document)
        return [n for n in _flatten(scene.group) if isinstance(n, ScreenCoverageLOD)]

    def test_the_same_level_of_each_copy_batches_together(self, tmp_path):
        first, second = self._two_copies(tmp_path)

        for level in range(3):
            assert _key(first, level) == _key(second, level)

    def test_different_levels_are_different_draws(self, tmp_path):
        first, second = self._two_copies(tmp_path)

        assert _key(first, 0) != _key(second, 1)

    def test_a_level_is_decoded_once_however_many_copies_name_it(self, tmp_path):
        first, second = self._two_copies(tmp_path)

        assert _shapes(first.level[1])[0].geometry is _shapes(second.level[1])[0].geometry


def _placed(document, translation, rotation=None, on=(0, 1, 2)):
    """Put ``translation`` on each of the nodes ``on`` names."""
    for index in on:
        document['nodes'][index]['translation'] = list(translation)
        if rotation is not None:
            document['nodes'][index]['rotation'] = list(rotation)
    return document


def _world_of(scene, node, level):
    """Where level ``level`` of ``node`` actually lands, walking the graph."""

    target = _shapes(node.level[level])[0]

    def walk(current, matrix):
        if current is target:
            return matrix
        local = (_local_matrix_rv(current)
                 if hasattr(current, 'translation') else np.identity(4))
        here = local @ matrix
        for child in (getattr(current, 'children', None) or []):
            found = walk(child, here)
            if found is not None:
                return found
        for one in (getattr(current, 'level', None) or []):
            found = walk(one, here)
            if found is not None:
                return found
        return None

    return walk(scene.group, np.identity(4))


class TestWhereALevelIsDrawn:
    """Every level stands where the node carrying the extension stands.

    An alternative is a replacement for that node, so its own transform is in
    the *parent's* space and not on top of the node's. Applied twice, a bust
    two metres along a hall is drawn four metres along it -- and, with a
    rotation in play, somewhere else entirely.
    """

    def test_a_placed_node_puts_its_finest_level_where_it_is(self, tmp_path):
        scene = _loaded(tmp_path, _placed(_document(), (2.0, 0.0, 3.0)))

        where = _world_of(scene, _the_lod(scene), 0)

        assert where[3][:3] == pytest.approx([2.0, 0.0, 3.0])

    def test_a_coarser_level_lands_in_the_same_place(self, tmp_path):
        scene = _loaded(tmp_path, _placed(_document(), (2.0, 0.0, 3.0)))

        where = _world_of(scene, _the_lod(scene), 2)

        assert where[3][:3] == pytest.approx([2.0, 0.0, 3.0])

    def test_no_level_is_placed_twice(self, tmp_path):
        """The translation doubling that the extension invites."""
        scene = _loaded(tmp_path, _placed(_document(), (2.0, 0.0, 3.0)))
        lod = _the_lod(scene)

        places = [_world_of(scene, lod, level)[3][:3] for level in range(3)]

        for place in places:
            assert place == pytest.approx([2.0, 0.0, 3.0])

    def test_a_turned_node_does_not_turn_its_levels_twice(self, tmp_path):
        """A quarter turn applied twice is a half turn, which moves a level
        across the object it is a level of rather than merely facing it away."""
        quarter = [0.0, 0.7071068, 0.0, 0.7071068]
        scene = _loaded(tmp_path,
                        _placed(_document(), (4.0, 0.0, 0.0), rotation=quarter))
        lod = _the_lod(scene)

        finest = _world_of(scene, lod, 0)
        coarsest = _world_of(scene, lod, 2)

        assert coarsest[3][:3] == pytest.approx(finest[3][:3])
        assert coarsest[:3, :3] == pytest.approx(finest[:3, :3], abs=1e-6)

    def test_an_alternative_with_no_transform_of_its_own_still_lands_there(
            self, tmp_path):
        """The shape the canonical example is in: a bare mesh node."""
        document = _placed(_document(), (2.0, 0.0, 3.0), on=(0,))
        scene = _loaded(tmp_path, document)

        where = _world_of(scene, _the_lod(scene), 1)

        assert where[3][:3] == pytest.approx([2.0, 0.0, 3.0])


class TestMalformedValues:
    """One bad value in an MSFT_lod block costs the chain, never the load."""

    def test_ids_that_are_no_node_indices_are_passed_over(self, tmp_path):
        node = _the_lod(_loaded(tmp_path, _document(ids=['a', 1, 2.5, None, 2])))
        assert len(node.level) == 3

    def test_an_extension_that_is_no_object_loads_the_finest_level(self, tmp_path):
        document = _document()
        document['nodes'][0]['extensions']['MSFT_lod'] = [1, 2]
        scene = _loaded(tmp_path, document)
        assert [n for n in _flatten(scene.group) if isinstance(n, ScreenCoverageLOD)] == []
        assert _shapes(scene.group)

    @pytest.mark.parametrize('coverage', ['abc', 0.5, [0.5, 'x', 0.1],
                                          [float('nan'), 0.2, 0.1]])
    def test_a_coverage_that_is_no_list_of_numbers_is_guessed(self, tmp_path, coverage):
        document = _document()
        document['nodes'][0]['extras'] = {'MSFT_screencoverage': coverage}
        node = _the_lod(_loaded(tmp_path, document))
        assert list(node.screenCoverage) == pytest.approx([0.5, 0.25, 0.0])

    @pytest.mark.parametrize('declared', [['a', 0, 0], [0, 0], 'abc'])
    def test_bounds_that_are_no_numbers_are_not_read(self, tmp_path, declared):
        """The chain and its shape are then measured from the points."""
        document = _document()
        document['accessors'][0]['min'] = declared
        scene = _loaded(tmp_path, document)
        node = _the_lod(scene)
        assert node.coverageRadius() == pytest.approx(np.sqrt(2.0) / 2.0)
        assert np.all(np.isfinite(scene.minimum)) and np.isfinite(scene.radius)


class TestAnAnimatedFinestLevel:
    """The finest level is the node's own mesh, so a morph or a skin on the
    node drives it as it would without the extension."""

    def _morphed(self):
        document = _document(levels=2)
        blob = base64.b64decode(document['buffers'][0]['uri'].split(',', 1)[1])
        delta = np.array([(0, 0, 1)] * 3, dtype='<f4')
        document['bufferViews'].append({'buffer': 0, 'byteOffset': len(blob),
                                        'byteLength': delta.nbytes})
        blob += delta.tobytes()
        document['buffers'] = [{'byteLength': len(blob), 'uri': _b64(blob)}]
        document['accessors'].append({
            'bufferView': 2, 'componentType': 5126, 'count': 3, 'type': 'VEC3',
            'min': [0, 0, 1], 'max': [0, 0, 1]})
        mesh = document['meshes'][0]
        mesh['primitives'][0]['targets'] = [{'POSITION': 2}]
        mesh['weights'] = [1.0]
        return document

    def test_a_morph_on_the_node_drives_its_finest_level(self, tmp_path):
        scene = _loaded(tmp_path, self._morphed())
        node = _the_lod(scene)

        assert 0 in scene.node_morph
        positions = _shapes(node.level[0])[0].geometry.positions
        assert positions[:, 2] == pytest.approx([1.0, 1.0, 1.0])

    def test_a_skin_on_the_node_skins_its_finest_level(self, tmp_path):
        document = _document(levels=2)
        blob = base64.b64decode(document['buffers'][0]['uri'].split(',', 1)[1])
        joints = np.zeros((3, 4), dtype='<u2')
        weights = np.tile(np.array([1, 0, 0, 0], dtype='<f4'), (3, 1))
        for data, kind in ((joints, 5123), (weights, 5126)):
            document['bufferViews'].append({'buffer': 0, 'byteOffset': len(blob),
                                            'byteLength': data.nbytes})
            blob += data.tobytes()
            document['accessors'].append({
                'bufferView': len(document['bufferViews']) - 1,
                'componentType': kind, 'count': 3, 'type': 'VEC4'})
        document['buffers'] = [{'byteLength': len(blob), 'uri': _b64(blob)}]
        document['meshes'][0]['primitives'][0]['attributes'].update(
            {'JOINTS_0': 2, 'WEIGHTS_0': 3})
        document['nodes'][0]['skin'] = 0
        document['nodes'].append({'name': 'bone'})
        document['skins'] = [{'joints': [2]}]
        document['scenes'][0]['nodes'] = [0, 2]

        scene = _loaded(tmp_path, document)

        assert [skin.mesh_node for skin in scene.skins] == [0]


class TestReconcilingTheCoverage:
    def test_a_level_left_out_takes_its_coverage_with_it(self, tmp_path):
        """Three thresholds for two levels would cull a level early."""
        node = _the_lod(_loaded(tmp_path, _document(ids=[1, 99])))

        assert len(node.level) == 2
        assert list(node.screenCoverage) == pytest.approx([0.5, 0.2])

    def test_a_list_of_the_wrong_length_is_reported(self, tmp_path, caplog):
        document = _document()
        document['nodes'][0]['extras'] = {'MSFT_screencoverage': [0.5]}

        node = _the_lod(_loaded(tmp_path, document))

        assert 'MSFT_screencoverage' in caplog.text
        assert list(node.screenCoverage) == pytest.approx([0.5, 0.25, 0.0])

    def test_one_more_threshold_than_levels_is_the_cull(self, tmp_path):
        document = _document(coverage=[0.5, 0.2, 0.01, 0.001])

        node = _the_lod(_loaded(tmp_path, document))

        assert list(node.screenCoverage) == pytest.approx([0.5, 0.2, 0.01, 0.001])


class TestAChainNamingItself:
    def test_a_node_naming_itself_keeps_its_place(self, tmp_path, caplog):
        """Its own index among the alternatives would take it out of the scene."""
        scene = _loaded(tmp_path, _document(ids=[0, 1, 2]))

        node = _the_lod(scene)

        assert len(node.level) == 3
        assert 'MSFT_lod' in caplog.text


class TestQuantizedBounds:
    def test_normalized_positions_are_measured_in_the_units_they_are_drawn_in(
            self, tmp_path):
        """KHR_mesh_quantization: a normalized accessor's min/max are integers."""
        points = np.array([(0, 0, 0), (32767, 0, 0), (0, 32767, 0)], dtype='<i2')
        padded = np.zeros((3, 4), dtype='<i2')
        padded[:, :3] = points
        blob = padded.tobytes()
        document = {
            'asset': {'version': '2.0'},
            'extensionsUsed': ['MSFT_lod', 'KHR_mesh_quantization'],
            'extensionsRequired': ['KHR_mesh_quantization'],
            'buffers': [{'byteLength': len(blob), 'uri': _b64(blob)}],
            'bufferViews': [{'buffer': 0, 'byteLength': len(blob),
                             'byteStride': 8}],
            'accessors': [{'bufferView': 0, 'componentType': 5122,
                           'normalized': True, 'count': 3, 'type': 'VEC3',
                           'min': [0, 0, 0], 'max': [32767, 32767, 0]}],
            'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
            'nodes': [{'mesh': 0, 'extensions': {'MSFT_lod': {'ids': [1]}}},
                      {'mesh': 0}],
            'scenes': [{'nodes': [0]}],
            'scene': 0,
        }

        scene = _loaded(tmp_path, document)
        node = _the_lod(scene)

        assert node.coverageRadius() == pytest.approx(np.sqrt(2.0) / 2.0)
        assert scene.radius < 2.0


class TestAnAlternativePlacedElsewhere:
    def test_the_warning_names_the_node_once_and_says_where_it_is_drawn(
            self, tmp_path, caplog):
        document = _document()
        document['nodes'][0]['name'] = 'bust'
        document['nodes'][2]['translation'] = [5.0, 0.0, 0.0]

        _loaded(tmp_path, document)

        warned = [record.getMessage() for record in caplog.records
                  if 'places itself' in record.getMessage()
                  or 'placement of its own' in record.getMessage()]
        assert len(warned) == 1
        assert warned[0].count("'bust'") == 1
        assert 'offers alternatives' not in warned[0]
