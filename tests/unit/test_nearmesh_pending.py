"""``InstancedMeshLOD.compute_pending`` — the pure near-set selection (no GL).

The near-mesh LOD selects the trees within a radius of the camera and packs their
per-instance rows for upload. ``compute_pending`` is the selection alone: it reads
only the immutable position/yaw/scale/species tables and returns fresh arrays, so a
background streaming thread can build the next near-set off the render thread.
Constructing the node touches no GL, so these run without a context.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.vegetation.nearmesh import InstancedMeshLOD


def _node():
    # Three trees near the origin (species 0,1,1) and one far away (species 0).
    pos = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 2], [100, 0, 100]], "f4")
    yaw = np.array([0.1, 0.2, 0.3, 0.4], "f4")
    scale = np.array([1, 2, 3, 4], "f4")
    species_id = np.array([0, 1, 1, 0])
    return InstancedMeshLOD(pos, yaw, scale, species=[{}, {}], species_id=species_id)


def test_compute_pending_selects_within_radius_by_species():
    d = _node().compute_pending(0.0, 0.0, radius=10.0)
    assert set(d) == {0, 1}
    assert d[0].shape == (1, 6)      # only the origin tree is species 0 within radius
    assert d[1].shape == (2, 6)      # the two nearby species-1 trees
    assert d[0][0, 3] == np.float32(0.1)   # row layout is (x, y, z, yaw, scale)
    assert d[0][0, 4] == np.float32(1.0)


def test_compute_pending_excludes_trees_outside_radius():
    # Radius 1.5 keeps only the origin (0) and the (1,0,0) tree (species 0 and 1).
    d = _node().compute_pending(0.0, 0.0, radius=1.5)
    assert d[0].shape == (1, 6)
    assert d[1].shape == (1, 6)


def test_compute_pending_does_not_mutate_node_state():
    n = _node()
    n.compute_pending(0.0, 0.0, 5.0)
    assert n._pending is None        # pure: staging is the caller's job


def test_update_stages_the_computed_pending():
    n = _node()
    n.update(0.0, 0.0, 10.0)
    assert n._pending is not None
    assert set(n._pending) == {0, 1}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
