"""Coverage tests for KHR_draco_mesh_compression decode edge paths.

Real DracoPy encodes the positions/normals/texcoords cases (see the sibling
test_gltf_draco.py); DracoPy.encode cannot emit tangents / skin joints / vertex
colours, so those attribute branches -- plus the point-cloud, missing-attribute and
no-POSITION guards -- are driven with a fake decoded mesh substituted for the
Draco decode step. The attribute map, accessors and normalization policy are the
real code under test.
"""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")
DracoPy = pytest.importorskip("DracoPy")
from pygltflib import GLTF2, Primitive, Attributes, Accessor  # noqa: E402

from OpenGLContext.loaders.gltf import draco as draco_mod  # noqa: E402


class _FakeMesh:
    """Stand-in for a decoded DracoPy mesh: ``faces`` plus a unique-id -> data map."""

    def __init__(self, faces, attrs):
        self.faces = faces
        self._attrs = attrs

    def get_attribute_by_unique_id(self, uid):
        data = self._attrs.get(uid)
        return {'data': data} if data is not None else None


class TestDracoExtension:
    def test_non_dict_extensions_yield_none(self):
        prim = Primitive(attributes=Attributes(POSITION=0))
        prim.extensions = ['not', 'a', 'dict']
        assert draco_mod.draco_extension(prim) is None


class TestWarnMissingDedup:
    def test_resolver_already_warned_stays_silent(self, caplog):
        class _Res:
            _draco_warned = True

        with caplog.at_level('WARNING'):
            draco_mod._warn_missing_once(_Res())
        assert not [r for r in caplog.records if 'draco' in r.getMessage().lower()]


class TestDecodeBlobGuards:
    def test_missing_bufferview_raises(self):
        with pytest.raises(ValueError, match='no bufferView'):
            draco_mod._decode_blob(GLTF2(), {'attributes': {}}, None)


def _prim(attr_map, **attr_indices):
    prim = Primitive(attributes=Attributes(**attr_indices))
    prim.extensions = {draco_mod.DRACO_EXTENSION:
                       {'bufferView': 0, 'attributes': attr_map}}
    return prim


class TestDracoArraysAttributeBranches:
    def test_point_cloud_without_faces_raises(self, monkeypatch):
        monkeypatch.setattr(draco_mod, '_decode_blob',
                            lambda g, ext, r: _FakeMesh(None, {10: np.zeros((3, 3))}))
        prim = _prim({'POSITION': 10}, POSITION=0)
        with pytest.raises(ValueError, match='point cloud'):
            draco_mod.draco_arrays(GLTF2(), prim, None)

    def test_missing_position_attribute_id_raises(self, monkeypatch):
        # The map lists POSITION but the stream has no matching unique id.
        monkeypatch.setattr(draco_mod, '_decode_blob',
                            lambda g, ext, r: _FakeMesh(np.array([[0, 1, 2]]), {}))
        prim = _prim({'POSITION': 10}, POSITION=0)
        with pytest.raises(ValueError, match='no POSITION'):
            draco_mod.draco_arrays(GLTF2(), prim, None)

    def test_tangents_colors_joints_texcoords_decoded(self, monkeypatch):
        n = 3
        pos = np.arange(n * 3, dtype=np.float64).reshape(n, 3)
        tan = np.ones((n, 4), dtype=np.float64)
        col = np.tile([1.0, 0.0, 0.0, 1.0], (n, 1))
        joints = np.zeros((n, 4), dtype=np.float64)
        tex = np.tile([0.25, 0.75], (n, 1))
        faces = np.array([[0, 1, 2]], dtype=np.uint32)
        mesh = _FakeMesh(faces, {10: pos, 11: tan, 12: col, 13: joints, 14: tex})
        monkeypatch.setattr(draco_mod, '_decode_blob', lambda g, ext, r: mesh)

        g = GLTF2()
        g.accessors = [
            Accessor(componentType=5126, type='VEC3', count=n),   # POSITION
            Accessor(componentType=5126, type='VEC4', count=n),   # COLOR_0 (float)
            Accessor(componentType=5126, type='VEC2', count=n),   # TEXCOORD_0
        ]
        prim = _prim(
            {'POSITION': 10, 'TANGENT': 11, 'COLOR_0': 12,
             'JOINTS_0': 13, 'TEXCOORD_0': 14},
            POSITION=0, COLOR_0=1, TEXCOORD_0=2)
        out = draco_mod.draco_arrays(g, prim, None)
        assert out['positions'].shape == (n, 3)
        assert out['tangents'].shape == (n, 4)
        assert out['tangents'].dtype == np.float32
        assert out['skin_joints'].dtype == np.uint32
        assert out['texcoords'].shape == (n, 2)
        # VEC4 colour comes through RGBA.
        assert out['colors'].shape == (n, 4)
        assert np.allclose(out['colors'][0], [1, 0, 0, 1])

    def test_attribute_missing_id_warns_and_skips_non_position(self, monkeypatch, caplog):
        # NORMAL is listed in the map but absent from the stream -> warn, skip it,
        # while the mesh still decodes from POSITION.
        pos = np.zeros((3, 3), dtype=np.float64)
        mesh = _FakeMesh(np.array([[0, 1, 2]], dtype=np.uint32), {10: pos})
        monkeypatch.setattr(draco_mod, '_decode_blob', lambda g, ext, r: mesh)
        prim = _prim({'POSITION': 10, 'NORMAL': 99}, POSITION=0, NORMAL=1)
        with caplog.at_level('WARNING'):
            out = draco_mod.draco_arrays(GLTF2(), prim, None)
        assert 'normals' not in out
        assert any('attribute id' in r.getMessage() for r in caplog.records)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
