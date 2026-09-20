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
    from OpenGLContext.loaders.gltf.transforms import _local_matrix_rv

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
