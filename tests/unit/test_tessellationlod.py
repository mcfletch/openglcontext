"""Distance-based tessellation LOD.

The metric is eye-space camera distance to the object centre, normalized by the
object radius. These GL-free tests pin the mapping and the disable switches.
"""
import types

import numpy as np
import pytest

from OpenGLContext.scenegraph import tessellationlod as lod


def _mode(modelview):
    return types.SimpleNamespace(matrix=np.asarray(modelview, dtype='d'))


def _translate_z(dz):
    """Row-vector modelview translating the origin to eye-space (0,0,dz)."""
    m = np.eye(4)
    m[3, 2] = dz
    return m


class TestDistanceMetric:
    def test_distance_is_scale_invariant_in_radii(self):
        # camera 40 units from the centre; a radius-1 object is 40 radii away,
        # a radius-4 object only 10 radii away -> the big one gets a finer level.
        mv = _translate_z(-40.0)
        near = lod.camera_distance_radii((0, 0, 0), 4.0, mv)
        far = lod.camera_distance_radii((0, 0, 0), 1.0, mv)
        assert np.isclose(near, 10.0)
        assert np.isclose(far, 40.0)

    def test_offset_center_uses_transformed_point(self):
        mv = _translate_z(-10.0)
        d = lod.camera_distance_radii((0, 0, 0), 1.0, mv)
        assert np.isclose(d, 10.0)


class TestLevelMapping:
    @pytest.mark.parametrize("dist,level", [
        (1.0, 0), (13.9, 0),
        (14.0, 1), (25.9, 1),
        (26.0, 2), (49.9, 2),
        (50.0, 3), (1000.0, 3),
    ])
    def test_thresholds(self, dist, level):
        assert lod.level_from_distance(dist) == level

    def test_closer_is_finer(self):
        assert lod.level_from_distance(2.0) < lod.level_from_distance(200.0)


class TestLodLevelPipeline:
    def test_near_object_is_level_zero(self):
        assert lod.lod_level(_mode(_translate_z(-3.0)), (0, 0, 0), 1.0) == 0

    def test_far_object_is_coarsest(self):
        assert lod.lod_level(_mode(_translate_z(-500.0)), (0, 0, 0), 1.0) == lod.COARSEST_LEVEL

    def test_env_off_forces_finest(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_LOD', 'off')
        # far away, but LOD disabled -> never coarser than the caller's default
        assert lod.lod_level(_mode(_translate_z(-500.0)), (0, 0, 0), 1.0) == 0

    @pytest.mark.parametrize("val", ['0', 'off', 'false', 'no', 'none', 'OFF'])
    def test_env_disable_values(self, monkeypatch, val):
        monkeypatch.setenv('OPENGLCONTEXT_LOD', val)
        assert lod.lod_enabled() is False

    def test_env_on_by_default(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_LOD', raising=False)
        assert lod.lod_enabled() is True

    def test_missing_matrix_is_finest(self):
        assert lod.lod_level(types.SimpleNamespace(), (0, 0, 0), 1.0) == 0

    def test_malformed_matrix_falls_back_to_finest(self):
        # A present-but-unusable matrix must not crash the draw; the distance
        # computation raises and the level degrades to finest (0).
        bad = types.SimpleNamespace(matrix=np.zeros((2, 2), dtype='d'))
        assert lod.lod_level(bad, (0, 0, 0), 1.0) == 0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
