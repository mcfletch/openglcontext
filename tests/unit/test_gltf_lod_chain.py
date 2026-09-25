"""A level-of-detail chain written by the engine and read back a level at a time.

``GLTFWriter.add_lod`` writes ``MSFT_lod``, and a node's ``buffer`` puts its
mesh in a file beside the ``.glb``; ``LODAsset`` opens such a file reading only
its JSON, and reads one level's bytes when asked. The claims that matter are
what a reader pays for a level it does not want -- asserted by taking the other
levels' files away -- and that what the writer writes is what both readers read.
"""
import base64
import json
import os
import struct

import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import lod
from OpenGLContext.loaders.gltf.lodasset import LOD_ERROR, LODAsset
from OpenGLContext.loaders.gltf.writer import GLTFWriter, SceneNode
from OpenGLContext.scenegraph.lod import ScreenCoverageLOD
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.loaders.documentvalues import DocumentError

SECRET = b'the private key nobody asked this model for'


def _mesh(points, faces):
    positions = np.asarray(points, 'f4')
    return PBRMesh(positions=positions,
                   normals=np.tile(np.array([0, 1, 0], 'f4'), (len(positions), 1)),
                   indices=np.asarray(faces, np.uint32))


LEVELS = [
    _mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 0, 0)],
          [0, 1, 2, 1, 3, 2, 1, 4, 3]),
    _mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], [0, 1, 2, 1, 3, 2]),
    _mesh([(0, 0, 0), (2, 0, 0), (0, 2, 0)], [0, 1, 2]),
]


def _write(directory, coverage=None, embed=1, levels=LEVELS):
    """The chain as a glb, the coarsest ``embed`` levels in it and each finer
    one in a file of its own beside it."""
    writer = GLTFWriter()
    finer = len(levels) - embed
    writer.add_lod([SceneNode(mesh=mesh, name='lod%d' % (index,),
                              buffer='bust.lod%d.bin' % (index,)
                              if index < finer else None)
                    for index, mesh in enumerate(levels)], coverage)
    writer.extras[LOD_ERROR] = [0.0, 0.01, 0.1][:len(levels)]
    path = str(directory / 'bust.glb')
    writer.write(path)
    return path


def _document(path):
    with open(path, 'rb') as handle:
        raw = handle.read()
    length, _kind = struct.unpack('<II', raw[12:20])
    return json.loads(raw[20:20 + length])


class TestWritingAChain:
    def test_the_finest_level_carries_the_extension(self, tmp_path):
        document = _document(_write(tmp_path))
        assert 'MSFT_lod' in document['extensionsUsed']
        assert document['scenes'][0]['nodes'] == [0]
        assert document['nodes'][0]['extensions']['MSFT_lod']['ids'] == [1, 2]
        assert document['nodes'][0]['mesh'] == 0

    def test_unmeasured_coverage_is_the_series_the_loader_guesses(self, tmp_path):
        """Ending at 0, so the coarsest level is never culled."""
        document = _document(_write(tmp_path))
        stated = document['nodes'][0]['extras']['MSFT_screencoverage']
        assert stated == lod.halving_coverage(3) == [0.5, 0.25, 0.0]

    def test_measured_coverage_is_written_as_given(self, tmp_path):
        document = _document(_write(tmp_path, coverage=[0.4, 0.1, 0.01]))
        assert document['nodes'][0]['extras']['MSFT_screencoverage'] == \
            [0.4, 0.1, 0.01]

    def test_a_coverage_per_level_is_required(self, tmp_path):
        with pytest.raises(ValueError):
            _write(tmp_path, coverage=[0.5, 0.1])

    def test_each_finer_level_is_a_file_beside_the_glb(self, tmp_path):
        document = _document(_write(tmp_path))
        assert document['buffers'][0] == {
            'byteLength': document['buffers'][0]['byteLength']}
        assert [one.get('uri') for one in document['buffers'][1:]] == [
            'bust.lod0.bin', 'bust.lod1.bin']
        for index in (0, 1):
            assert (tmp_path / ('bust.lod%d.bin' % (index,))).exists()

    def test_with_every_level_beside_it_no_empty_chunk_is_declared(self, tmp_path):
        """glTF requires a buffer to hold a byte, and buffer 0 with no uri to
        be the binary chunk."""
        document = _document(_write(tmp_path, embed=0))
        assert all(one['byteLength'] >= 1 for one in document['buffers'])
        assert all('uri' in one for one in document['buffers'])
        with open(tmp_path / 'bust.glb', 'rb') as handle:
            raw = handle.read()
        assert len(raw) == 20 + struct.unpack('<I', raw[12:16])[0]

    def test_a_buffer_name_with_a_directory_in_it_is_refused(self, tmp_path):
        writer = GLTFWriter()
        for name in ('../bust.bin', 'levels/bust.bin', '/tmp/bust.bin', '..'):
            with pytest.raises(ValueError):
                writer.add_node(SceneNode(mesh=LEVELS[0], buffer=name))

    def test_the_engine_loads_what_was_written(self, tmp_path):
        scene = gltf.load_gltf(_write(tmp_path))
        found = [node for node in _walk(scene.group)
                 if isinstance(node, ScreenCoverageLOD)]
        assert len(found) == 1
        assert list(found[0].screenCoverage) == pytest.approx([0.5, 0.25, 0.0])
        assert len(found[0].level) == 3


def _walk(node):
    yield node
    for child in list(getattr(node, 'children', None) or []) + list(
            getattr(node, 'level', None) or []):
        yield from _walk(child)


class TestReadingOnlyWhatIsWanted:
    def test_opening_it_describes_every_level(self, tmp_path):
        asset = LODAsset.open(_write(tmp_path))
        assert [entry.triangle_count for entry in asset.levels] == [3, 2, 1]
        assert [entry.vertex_count for entry in asset.levels] == [5, 4, 3]
        assert [entry.error for entry in asset.levels] == pytest.approx(
            [0.0, 0.01, 0.1])
        assert [entry.screen_coverage for entry in asset.levels] == [0.5, 0.25, 0.0]
        assert asset.levels[-1].source is None
        assert asset.levels[0].source == 'bust.lod0.bin'

    def test_every_level_reads_back_what_was_written(self, tmp_path):
        asset = LODAsset.open(_write(tmp_path))
        for index, mesh in enumerate(LEVELS):
            attributes, indices = asset.load(index)
            np.testing.assert_allclose(attributes['POSITION'], mesh.positions)
            np.testing.assert_allclose(attributes['NORMAL'], mesh.normals)
            assert indices.dtype == np.uint32
            assert np.array_equal(indices, mesh.indices)

    def test_the_coarsest_level_needs_no_other_file(self, tmp_path):
        path = _write(tmp_path)
        for index in (0, 1):
            os.remove(tmp_path / ('bust.lod%d.bin' % (index,)))
        attributes, indices = LODAsset.open(path).load(2)
        assert np.array_equal(indices, LEVELS[2].indices)

    def test_one_level_does_not_need_the_others(self, tmp_path):
        path = _write(tmp_path)
        os.remove(tmp_path / 'bust.lod1.bin')
        asset = LODAsset.open(path)
        attributes, _indices = asset.load(0)
        np.testing.assert_allclose(attributes['POSITION'], LEVELS[0].positions)
        with pytest.raises(OSError):
            asset.load(1)

    def test_a_truncated_file_is_refused_rather_than_half_read(self, tmp_path):
        path = _write(tmp_path)
        with open(tmp_path / 'bust.lod0.bin', 'r+b') as handle:
            handle.truncate(16)
        with pytest.raises(ValueError, match='short'):
            LODAsset.open(path).load(0)

    def test_something_that_is_not_a_glb_is_refused(self, tmp_path):
        (tmp_path / 'nonsense.glb').write_bytes(b'not a glb at all, really')
        with pytest.raises(ValueError, match='not a glb'):
            LODAsset.open(str(tmp_path / 'nonsense.glb'))


def _rewrite(path, change):
    """Change the glb's JSON with ``change(document)`` and write it back."""
    with open(path, 'rb') as handle:
        raw = handle.read()
    length, _kind = struct.unpack('<II', raw[12:20])
    document = json.loads(raw[20:20 + length])
    change(document)
    encoded = json.dumps(document).encode('utf-8')
    encoded += b' ' * (-len(encoded) % 4)
    rest = raw[20 + length:]
    with open(path, 'wb') as handle:
        handle.write(struct.pack('<III', 0x46546C67, 2, 20 + len(encoded) + len(rest)))
        handle.write(struct.pack('<II', len(encoded), 0x4E4F534A))
        handle.write(encoded)
        handle.write(rest)


class TestTheStorageAnotherToolMayUse:
    def test_sixteen_bit_indices(self, tmp_path):
        """What most exporters write for a mesh under 65536 vertices."""
        path = _write(tmp_path)
        attributes, indices = LODAsset.open(path).load(2)
        assert _document(path)['accessors'][
            _document(path)['meshes'][2]['primitives'][0]['indices']][
                'componentType'] == 5123
        assert np.array_equal(indices, [0, 1, 2])

    def test_an_unknown_component_type_is_refused(self, tmp_path):
        path = _write(tmp_path)

        def corrupt(document):
            index = document['meshes'][2]['primitives'][0]['indices']
            document['accessors'][index]['componentType'] = 5124
        _rewrite(path, corrupt)
        with pytest.raises(ValueError, match='componentType'):
            LODAsset.open(path).load(2)

    def test_quantized_positions_are_scaled_back(self, tmp_path):
        """KHR_mesh_quantization: a normalized unsigned short per component."""
        path = _write(tmp_path)
        quantized = np.array([(0, 0, 0), (65535, 0, 0), (0, 65535, 0)], '<u2')
        extra = tmp_path / 'quantized.bin'
        extra.write_bytes(quantized.tobytes())

        def point_at_it(document):
            document['buffers'].append({'uri': 'quantized.bin',
                                        'byteLength': quantized.nbytes})
            document['bufferViews'].append({'buffer': len(document['buffers']) - 1,
                                            'byteLength': quantized.nbytes})
            primitive = document['meshes'][2]['primitives'][0]
            document['accessors'][primitive['attributes']['POSITION']].update(
                bufferView=len(document['bufferViews']) - 1,
                componentType=5123, normalized=True)
        _rewrite(path, point_at_it)
        attributes, _indices = LODAsset.open(path).load(2)
        np.testing.assert_allclose(attributes['POSITION'],
                                   [(0, 0, 0), (1, 0, 0), (0, 1, 0)])


class TestWhereALevelsBytesMayLive:
    """A uri in a document is data; a level's file must be beside the glb."""

    @pytest.fixture
    def repointed(self, tmp_path):
        (tmp_path / 'secret.bin').write_bytes(SECRET)
        (tmp_path / 'model').mkdir()
        path = _write(tmp_path / 'model')

        def to(uri):
            def change(document):
                document['buffers'][1]['uri'] = uri
            _rewrite(path, change)
            return LODAsset.open(path)
        return to

    @pytest.mark.parametrize('uri', ['../secret.bin', '%2e%2e%2fsecret.bin',
                                     'http://169.254.169.254/latest/meta-data/'])
    def test_a_reference_out_of_the_directory_is_refused(self, repointed, uri):
        with pytest.raises(OSError):
            repointed(uri).load(0)

    def test_an_absolute_path_is_refused(self, repointed, tmp_path):
        with pytest.raises(OSError):
            repointed(str(tmp_path / 'secret.bin')).load(0)

    def test_a_data_uri_is_read_and_capped(self, repointed, tmp_path):
        payload = (tmp_path / 'model' / 'bust.lod0.bin').read_bytes()
        asset = repointed('data:application/octet-stream;base64,'
                          + base64.b64encode(payload).decode('ascii'))
        attributes, _indices = asset.load(0)
        np.testing.assert_allclose(attributes['POSITION'], LEVELS[0].positions)
        capped = LODAsset.open(asset.path, max_resource_bytes=8)
        with pytest.raises(ValueError):
            capped.load(0)

    def test_the_glbs_own_chunk_is_capped_too(self, tmp_path):
        asset = LODAsset.open(_write(tmp_path), max_resource_bytes=8)
        with pytest.raises(ValueError):
            asset.load(2)


@pytest.mark.parametrize('document, complaint', [
    ({'nodes': [{'mesh': 'a'}], 'meshes': []}, "mesh is 'a', which is not a finite number"),
    ({'nodes': [{'mesh': 2}], 'meshes': [{}]}, 'meshes 2 is named and there are 1'),
    ({'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [
        {'attributes': {'POSITION': -1}}]}]}, 'POSITION is -1, which is negative'),
    ({'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [
        {'attributes': {'POSITION': 0}}]}], 'accessors': [{'count': 1.5}]},
     'accessor count is 1.5, which is not a whole number'),
])
def test_a_document_naming_what_is_not_there_is_refused(document, complaint):
    with pytest.raises(DocumentError, match=complaint):
        LODAsset('chain.glb', document, 0)
