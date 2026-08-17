"""Collision-world extraction from a scenegraph (:mod:`OpenGLContext.physics.gltf_world`).

Walks a scenegraph pulling world-space triangles out of every mesh and builds a
static ``trimesh`` collision world so a character can walk on a loaded model. These
tests drive the real extractor over hand-built scenegraphs: transformed meshes,
IndexedFaceSet ``coordIndex`` fan-triangulation, instanced geometry reached through
several transforms, the box-ify size threshold, and the empty-scene fast paths.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.transform import Transform
from OpenGLContext.physics.gltf_world import (
    extract_trimesh, collision_world_from_scene, _fan_triangulate,
    _mesh_positions_indices, _local_matrix,
)


def _quad_ifs(z=0.0):
    """A one-quad IndexedFaceSet in the y=const plane (two triangles via fan)."""
    return basenodes.IndexedFaceSet(
        coord=basenodes.Coordinate(point=[
            (-1, 0, -1 + z), (1, 0, -1 + z), (1, 0, 1 + z), (-1, 0, 1 + z)]),
        coordIndex=[0, 1, 2, 3, -1])


def _shape(geom):
    return basenodes.Shape(geometry=geom)


def test_fan_triangulate_splits_a_quad_into_two_triangles():
    tris = _fan_triangulate(np.array([0, 1, 2, 3, -1]))
    assert tris.tolist() == [0, 1, 2, 0, 2, 3]


def test_fan_triangulate_handles_trailing_face_without_separator():
    """A final face with no closing -1 is still triangulated."""
    tris = _fan_triangulate(np.array([0, 1, 2, 3]))
    assert tris.reshape(-1, 3).tolist() == [[0, 1, 2], [0, 2, 3]]


def test_fan_triangulate_empty_returns_empty():
    assert _fan_triangulate(np.array([-1])).size == 0


def test_mesh_positions_from_indexed_face_set():
    """coordIndex is fan-triangulated to an (M, 3) triangle array."""
    pos, tri = _mesh_positions_indices(_quad_ifs())
    assert pos.shape == (4, 3)
    assert tri.shape == (2, 3)


def test_mesh_positions_from_explicit_positions_without_indices():
    """A geometry with .positions but no faces triangulates its vertex run."""
    class _Geom:
        positions = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], dtype='d')
        indices = None
        coordIndex = None
    pos, tri = _mesh_positions_indices(_Geom())
    assert pos.shape == (3, 3)
    assert tri.tolist() == [[0, 1, 2]]


def test_mesh_positions_none_when_geometry_is_empty():
    assert _mesh_positions_indices(basenodes.Coordinate(point=[])) is None
    empty = basenodes.IndexedFaceSet(coord=basenodes.Coordinate(point=[]))
    assert _mesh_positions_indices(empty) is None


def test_local_matrix_identity_for_poseless_node():
    node = basenodes.Group()
    assert np.allclose(_local_matrix(node), np.eye(4))


def test_local_matrix_applies_translation():
    """A translated Transform's local matrix carries its translation."""
    node = Transform(translation=(3, 4, 5))
    m = _local_matrix(node)
    # row-vector convention: the translation lives in the last row
    assert np.allclose(m[3, :3], (3, 4, 5)) or np.allclose(m[:3, 3], (3, 4, 5))


def test_extract_applies_the_world_transform():
    """A mesh under a translated Transform is extracted in world space."""
    root = Transform(translation=(10, 0, 0), children=[_shape(_quad_ifs())])
    points, tris = extract_trimesh(root)
    assert points[:, 0].min() == pytest.approx(9.0)     # -1 + 10
    assert points[:, 0].max() == pytest.approx(11.0)
    assert len(tris) == 2


def test_instanced_geometry_collected_once_per_parent():
    """One shared mesh reached through two transforms yields two copies."""
    shared = _shape(_quad_ifs())
    root = basenodes.Group(children=[
        Transform(translation=(0, 0, 0), children=[shared]),
        Transform(translation=(20, 0, 0), children=[shared]),
    ])
    points, tris = extract_trimesh(root)
    assert len(points) == 8                              # 4 verts x 2 instances
    assert len(tris) == 4
    assert points[:, 0].max() == pytest.approx(21.0)     # the shifted instance


def test_cycle_in_the_graph_does_not_recurse_forever():
    """A self-referential child is collected once, not endlessly."""
    g = basenodes.Group(children=[_shape(_quad_ifs())])
    g.children = list(g.children) + [g]                  # cycle back to itself
    points, _tris = extract_trimesh(g)
    assert len(points) == 4


def test_min_hull_size_boxifies_small_components():
    """A small mesh below the size threshold is replaced by its 8-corner AABB box."""
    root = Transform(children=[_shape(_quad_ifs())])
    # the quad's AABB diagonal is sqrt(8) ~= 2.83; a big threshold box-ifies it
    points, tris = extract_trimesh(root, min_hull_size=10.0)
    assert len(points) == 8                              # box corners, not 4 quad verts
    assert len(tris) == 12                               # 12 box triangles


def test_extract_returns_none_for_a_scene_without_meshes():
    assert extract_trimesh(basenodes.Group()) is None


def test_collision_world_builds_a_static_trimesh_body():
    """collision_world_from_scene adds one static body and returns the bounds."""
    root = Transform(children=[_shape(_quad_ifs())])
    world, bounds = collision_world_from_scene(root, gravity=9.81, ground_pad=0.5)
    assert world.body_count == 1
    assert world.motion_type[0] == 0                     # static
    lo, hi = bounds
    assert np.allclose(lo, (-1.5, -0.5, -1.5))           # padded AABB
    assert np.allclose(hi, (1.5, 0.5, 1.5))


def test_collision_world_empty_scene_has_no_body_and_no_bounds():
    world, bounds = collision_world_from_scene(basenodes.Group())
    assert world.body_count == 0
    assert bounds is None


def test_local_matrix_falls_back_to_identity_on_bad_pose():
    """A node whose pose cannot be built yields identity, not an exception."""
    class _BadTransform:
        translation = 'not-a-vector'                     # forces _local_matrix_rv to fail
    assert np.allclose(_local_matrix(_BadTransform()), np.eye(4))


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))


class TestAPlacementSetIsCollectedAtEveryPlacement:
    """An :class:`~OpenGLContext.scenegraph.instancedshape.InstancedShape` means
    the mesh is there once per placement. Collision has to agree with what is
    drawn, or a car drives through a tree it can see."""

    def _forest(self, spacing=20.0, count=3):
        from OpenGLContext.scenegraph.instancedshape import (
            InstancedShape, placement_matrices,
        )
        return InstancedShape(
            geometry=_quad_ifs(),
            placements=placement_matrices(
                translations=[(i * spacing, 0, 0) for i in range(count)]))

    def test_every_placement_contributes_its_triangles(self) -> None:
        points, tris = extract_trimesh(basenodes.Group(children=[self._forest()]))
        assert len(points) == 12          # three quads, fan-triangulated
        assert len(tris) == 6

    def test_they_land_where_the_placements_put_them(self) -> None:
        points, _tris = extract_trimesh(basenodes.Group(children=[self._forest()]))
        assert points[:, 0].min() == pytest.approx(-1.0)
        assert points[:, 0].max() == pytest.approx(41.0)

    def test_the_indices_stay_within_their_own_placement(self) -> None:
        _points, tris = extract_trimesh(basenodes.Group(children=[self._forest()]))
        assert tris.max() == 11
        assert sorted(set(tris.ravel().tolist())) == list(range(12))

    def test_the_parent_transform_still_applies(self) -> None:
        root = Transform(translation=(100, 0, 0), children=[self._forest()])
        points, _tris = extract_trimesh(root)
        assert points[:, 0].min() == pytest.approx(99.0)

    def test_a_set_with_no_placements_contributes_nothing(self) -> None:
        from OpenGLContext.scenegraph.instancedshape import InstancedShape
        empty = InstancedShape(geometry=_quad_ifs())
        assert extract_trimesh(basenodes.Group(children=[empty])) is None
