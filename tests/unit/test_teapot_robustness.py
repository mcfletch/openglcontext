"""Findings 4.24 / 4.25 for the NURBS teapot.

4.24: a transient tessellation failure (e.g. no current GL context at first
render) must not latch NURBS off process-wide -- it should retry on later frames,
latching only after repeated failures.

4.25: the bounding volume must be computed from the tessellated vertices already
in memory, not eyeballed constants that risk frustum-culling the visible teapot.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.teapot import Teapot
import OpenGLContext.scenegraph.teapot_nurbs as teapot_nurbs


def _reset():
    # Per-LOD-level caches: {level: (base, lid)} etc.
    Teapot._arrays = {}
    Teapot._tessellate_attempts = {}
    Teapot._buffers = {}


class TestTessellateRetry:
    def setup_method(self):
        _reset()

    def teardown_method(self):
        _reset()

    def test_transient_failure_then_success_retries(self, monkeypatch):
        real = teapot_nurbs.tessellate_teapot
        calls = {'n': 0}

        def flaky(*a, **k):
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError("no current context")
            return real(*a, **k)
        monkeypatch.setattr(teapot_nurbs, 'tessellate_teapot', flaky)

        assert Teapot._ensure_tessellated(0) is False     # first attempt fails
        assert 0 not in Teapot._arrays                    # NOT latched
        assert Teapot._ensure_tessellated(0) is True      # retried, succeeded
        assert Teapot._arrays[0][0] is not None

    def test_permanent_failure_latches_after_max(self, monkeypatch):
        calls = {'n': 0}

        def always(*a, **k):
            calls['n'] += 1
            raise RuntimeError("boom")
        monkeypatch.setattr(teapot_nurbs, 'tessellate_teapot', always)

        for _ in range(Teapot._MAX_TESSELLATE_ATTEMPTS):
            assert Teapot._ensure_tessellated(0) is False
        assert Teapot._arrays.get(0) == (None, None)      # now latched off
        before = calls['n']
        assert Teapot._ensure_tessellated(0) is False
        assert calls['n'] == before                       # no further attempts


class TestBoundingVolumeFromMesh:
    def setup_method(self):
        _reset()

    def teardown_method(self):
        _reset()

    def test_aabb_matches_tessellated_vertices(self):
        lo, hi = Teapot._mesh_aabb()
        base_array, lid_array = Teapot._arrays[0]
        from OpenGLContext.scenegraph.teapot_nurbs import FLOATS_PER_VERTEX
        verts = np.concatenate([  # T2F_N3F_V3F: position is floats 5..8
            np.asarray(base_array, 'f').reshape(-1, FLOATS_PER_VERTEX)[:, 5:8],
            np.asarray(lid_array, 'f').reshape(-1, FLOATS_PER_VERTEX)[:, 5:8],
        ])
        assert np.allclose(lo, verts.min(0))
        assert np.allclose(hi, verts.max(0))

    def test_bounding_volume_uses_mesh_extents_scaled(self):
        t = Teapot()
        t.size = 2.0
        vol = t.boundingVolume(None)
        lo, hi = Teapot._mesh_aabb()
        expected_size = (np.asarray(hi) - np.asarray(lo)) * 2.0
        expected_center = (np.asarray(hi) + np.asarray(lo)) * 0.5 * 2.0
        assert np.allclose(vol.size, expected_size, atol=1e-4)
        assert np.allclose(vol.center, expected_center, atol=1e-4)

    def test_extents_differ_from_old_eyeballed_constants(self):
        # the point of 4.25: the real mesh extents are not the [3.0,1.6,2.0] guess
        lo, hi = Teapot._mesh_aabb()
        size = np.asarray(hi) - np.asarray(lo)
        assert not np.allclose(size, [3.0, 1.6, 2.0], atol=0.05)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
