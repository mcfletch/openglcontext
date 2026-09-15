"""Levels of detail on disk: what a reader pays for one it does not want.

The claims being tested are the ones that decide whether two hundred assets
can each carry an ultra-high-resolution original: opening the file reads the
JSON and nothing else, and reading one level touches only that level's bytes.
Both are asserted by taking the other levels' files away.
"""

import json
import os
import struct

import numpy as np
import pytest

from OpenGLContext.meshlod import LODAsset, sidecar_name, write_chain
from OpenGLContext.meshlod.chain import LODChain, LODLevel


def _level(points, faces, error=0.0):
    positions = np.asarray(points, dtype='f4')
    return LODLevel(
        attributes={
            'POSITION': positions,
            'NORMAL': np.tile(np.asarray([0.0, 1.0, 0.0], 'f4'), (len(positions), 1)),
        },
        indices=np.asarray(faces, dtype=np.uint32).reshape(-1),
        error=error,
        vertex_map=np.arange(len(positions), dtype=np.int64),
    )


@pytest.fixture
def chain():
    """Three levels whose arrays are all different, so a mix-up shows."""
    fine = _level(
        [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 0, 0)],
        [0, 1, 2, 1, 3, 2, 1, 4, 3],
        error=0.0,
    )
    middle = _level([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], [0, 1, 2, 1, 3, 2], 0.01)
    coarse = _level([(0, 0, 0), (2, 0, 0), (0, 2, 0)], [0, 1, 2], 0.1)
    return LODChain([fine, middle, coarse], centre=(0.5, 0.5, 0.0), radius=1.0)


class TestWriting:
    def test_the_coarsest_level_rides_inside_the_glb(self, chain, tmp_path):
        written = write_chain(str(tmp_path / 'thing.glb'), chain)
        assert os.path.basename(written[0]) == 'thing.glb'
        asset = LODAsset.open(written[0])
        assert asset.levels[-1].source is None
        assert all(entry.source is not None for entry in asset.levels[:-1])

    def test_each_finer_level_gets_its_own_sidecar(self, chain, tmp_path):
        written = write_chain(str(tmp_path / 'thing.glb'), chain)
        assert len(written) == 3  # the glb plus two sidecars
        for level in (0, 1):
            assert os.path.exists(sidecar_name(str(tmp_path / 'thing.glb'), level))

    def test_it_is_a_glb_with_a_json_chunk_and_a_binary_chunk(self, chain, tmp_path):
        path = str(tmp_path / 'thing.glb')
        write_chain(path, chain)
        with open(path, 'rb') as handle:
            magic, version, length = struct.unpack('<III', handle.read(12))
            assert magic == 0x46546C67
            assert version == 2
            assert length == os.path.getsize(path)
            json_length, json_kind = struct.unpack('<II', handle.read(8))
            assert json_kind == 0x4E4F534A
            document = json.loads(handle.read(json_length))
            _binary_length, binary_kind = struct.unpack('<II', handle.read(8))
            assert binary_kind == 0x004E4942
        assert document['asset']['version'] == '2.0'

    def test_the_levels_are_declared_the_way_the_ecosystem_declares_them(self, chain, tmp_path):
        path = str(tmp_path / 'thing.glb')
        write_chain(path, chain)
        document = LODAsset.open(path).document
        assert 'MSFT_lod' in document['extensionsUsed']
        # The node carrying the extension is the finest; `ids` lists the rest in
        # decreasing detail, so a reader that ignores the extension draws the
        # finest level, which is the right thing for it to do.
        assert document['nodes'][0]['mesh'] == 0
        assert document['nodes'][0]['extensions']['MSFT_lod']['ids'] == [1, 2]
        coverage = document['nodes'][0]['extras']['MSFT_screencoverage']
        assert len(coverage) == 3
        assert coverage == sorted(coverage, reverse=True)

    def test_a_chain_with_no_levels_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match='no levels'):
            write_chain(str(tmp_path / 'empty.glb'), LODChain([], centre=(0, 0, 0), radius=1.0))


class TestReadingBackOnlyWhatIsWanted:
    def test_opening_it_tells_you_the_sizes_without_reading_the_geometry(self, chain, tmp_path):
        path = str(tmp_path / 'thing.glb')
        write_chain(path, chain)
        asset = LODAsset.open(path)
        assert [entry.triangle_count for entry in asset.levels] == [3, 2, 1]
        assert [entry.vertex_count for entry in asset.levels] == [5, 4, 3]
        assert asset.levels[2].error == pytest.approx(0.1)

    def test_every_level_reads_back_exactly_what_was_written(self, chain, tmp_path):
        path = str(tmp_path / 'thing.glb')
        write_chain(path, chain)
        asset = LODAsset.open(path)
        for index, level in enumerate(chain):
            attributes, indices = asset.load(index)
            assert attributes['POSITION'] == pytest.approx(level.attributes['POSITION'])
            assert attributes['NORMAL'] == pytest.approx(level.attributes['NORMAL'])
            assert np.array_equal(indices, level.indices)

    def test_the_coarsest_level_loads_with_every_sidecar_deleted(self, chain, tmp_path):
        """What a file has to be able to draw when nothing has streamed in."""
        path = str(tmp_path / 'thing.glb')
        write_chain(path, chain)
        for level in (0, 1):
            os.remove(sidecar_name(path, level))
        asset = LODAsset.open(path)
        attributes, indices = asset.load(2)
        assert np.array_equal(indices, chain[2].indices)

    def test_one_level_does_not_need_the_others(self, chain, tmp_path):
        """The finest level reads while the middle one is not even on disk."""
        path = str(tmp_path / 'thing.glb')
        write_chain(path, chain)
        os.remove(sidecar_name(path, 1))
        asset = LODAsset.open(path)
        attributes, _indices = asset.load(0)
        assert attributes['POSITION'] == pytest.approx(chain[0].attributes['POSITION'])
        with pytest.raises(OSError):
            asset.load(1)

    def test_a_truncated_sidecar_is_refused_rather_than_half_read(self, chain, tmp_path):
        path = str(tmp_path / 'thing.glb')
        write_chain(path, chain)
        with open(sidecar_name(path, 0), 'r+b') as handle:
            handle.truncate(16)
        with pytest.raises(ValueError, match='short'):
            LODAsset.open(path).load(0)

    def test_it_is_not_fooled_by_something_that_is_not_a_glb(self, tmp_path):
        path = tmp_path / 'nonsense.glb'
        path.write_bytes(b'not a glb at all, really')
        with pytest.raises(ValueError, match='not a glb'):
            LODAsset.open(str(path))
