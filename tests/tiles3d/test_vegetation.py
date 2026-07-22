"""Instanced vegetation group built from surface scatter (no GL).

Checks that scatter placements become per-instance transforms over one shared
prototype (the shape the instancing engine collapses), positioned on the surface.
"""
import numpy as np

from OpenGLContext.scenegraph.basenodes import Shape, Box
from OpenGLContext.loaders.tiles3d.vegetation import build_vegetation_group
from OpenGLContext.loaders.tiles3d.scatter import scatter_on_mesh


def _quad(size=10.0):
    p = np.array([[0, 0, 0], [size, 0, 0], [size, 0, size], [0, 0, size]], "f4")
    return p, np.array([[0, 1, 2], [0, 2, 3]], "u4")


def test_group_has_one_transform_per_instance():
    p, t = _quad()
    proto = Shape(geometry=Box(size=(1, 1, 1)))
    expected = len(scatter_on_mesh(p, t, density=1.0, seed=4))
    group = build_vegetation_group(p, t, proto, density=1.0, seed=4)
    assert len(group.children) == expected
    assert expected > 0


def test_instances_share_the_prototype():
    p, t = _quad()
    proto = Shape(geometry=Box(size=(1, 1, 1)))
    group = build_vegetation_group(p, t, proto, density=1.0, seed=4)
    for child in group.children:
        assert child.children[0] is proto  # shared -> instancing collapses to 1 draw


def test_instance_positions_match_scatter():
    p, t = _quad()
    proto = Shape(geometry=Box(size=(1, 1, 1)))
    placements = scatter_on_mesh(p, t, density=1.0, seed=11)
    group = build_vegetation_group(p, t, proto, density=1.0, seed=11)
    got = np.array([c.translation for c in group.children])
    assert np.allclose(got, placements.positions, atol=1e-4)


def test_partition_by_distance_splits_near_and_far():
    import numpy as np
    from OpenGLContext.loaders.tiles3d.scatter import scatter_on_mesh
    from OpenGLContext.loaders.tiles3d.vegetation import partition_by_distance
    p, t = _quad(size=200.0)
    s = scatter_on_mesh(p, t, density=0.01, seed=3)
    cam = (0.0, 0.0, 0.0)
    near, far = partition_by_distance(s, cam, near_distance=100.0)
    assert len(near) + len(far) == len(s)
    assert (np.linalg.norm(near.positions - np.array(cam, "f4"), axis=1) <= 100.0).all()
    assert (np.linalg.norm(far.positions - np.array(cam, "f4"), axis=1) > 100.0).all()
    assert len(near) > 0 and len(far) > 0


def test_vegetation_lod_uses_two_prototypes():
    from OpenGLContext.scenegraph.basenodes import Shape, Box
    from OpenGLContext.loaders.tiles3d.vegetation import build_vegetation_lod
    p, t = _quad(size=200.0)
    near_proto = Shape(geometry=Box(size=(2, 6, 2)))
    far_proto = Shape(geometry=Box(size=(1, 1, 1)))
    g = build_vegetation_lod(p, t, near_proto, far_proto, density=0.008, seed=5,
                             camera=(0, 0, 0), near_distance=90.0)
    near_group, far_group = g.children
    for c in near_group.children:
        assert c.children[0] is near_proto
    for c in far_group.children:
        assert c.children[0] is far_proto
    assert len(near_group.children) > 0 and len(far_group.children) > 0


def test_grass_patch_is_dense_and_local():
    import numpy as np
    from OpenGLContext.scenegraph.basenodes import Shape, Box
    from OpenGLContext.loaders.tiles3d.vegetation import build_grass_patch
    p, t = _quad(size=400.0)
    blade = Shape(geometry=Box(size=(0.1, 1.0, 0.1)))
    cam = (200.0, 0.0, 200.0)          # centre of the quad
    g = build_grass_patch(p, t, blade, camera=cam, radius=40.0, density=0.05, seed=2)
    assert len(g.children) > 20        # dense
    pos = np.array([c.translation for c in g.children])
    d = np.linalg.norm(pos[:, [0, 2]] - np.array([cam[0], cam[2]]), axis=1)
    assert (d <= 40.0 + 1e-3).all()    # all within the radius


def test_conifer_is_a_multipart_tree():
    from OpenGLContext.loaders.tiles3d.vegetation import conifer
    g = conifer(height=10.0)
    assert len(g.children) == 4          # trunk + 3 foliage layers
    # foliage sits above the trunk
    ys = [c.translation[1] for c in g.children]
    assert max(ys) > min(ys) + 3.0


def test_scatter_disc_seats_on_surface_within_radius():
    import numpy as np
    from OpenGLContext.loaders.tiles3d.vegetation import scatter_disc
    hf = lambda x, z: np.full(np.shape(x), 12.0)
    s = scatter_disc((100.0, 0.0, -50.0), radius=40.0, density=0.05, seed=1,
                     height_fn=hf)
    assert len(s) > 50
    d = np.linalg.norm(s.positions[:, [0, 2]] - np.array([100.0, -50.0]), axis=1)
    assert (d <= 40.0 + 1e-3).all()
    assert np.allclose(s.positions[:, 1], 12.0, atol=1e-3)   # on the surface


def test_scatter_disc_keep_filter():
    import numpy as np
    from OpenGLContext.loaders.tiles3d.vegetation import scatter_disc
    hf = lambda x, z: np.asarray(x) * 0 + np.asarray(z) * 0.0 + 5.0
    # keep only the +x half
    s = scatter_disc((0.0, 0.0, 0.0), 50.0, 0.05, seed=2, height_fn=hf,
                     keep=lambda p: p[:, 0] > 0)
    assert len(s) > 0 and (s.positions[:, 0] > 0).all()


def test_grass_and_bush_prototypes():
    from OpenGLContext.loaders.tiles3d.vegetation import grass_tuft, bush
    assert len(grass_tuft().children) == 3       # crossed blades
    assert len(bush().children) >= 2             # foliage blobs


def test_build_forest_patch_has_all_layers():
    import numpy as np
    from OpenGLContext.loaders.tiles3d.vegetation import build_forest_patch
    hf = lambda x, z: np.full(np.shape(x), 30.0)
    forest = build_forest_patch((0.0, 0.0, 0.0), hf, seed=5)
    assert len(forest.children) == 3             # grass, shrubs, trees
    grass, shrubs, trees = forest.children
    assert len(grass.children) > 20              # dense grass
    assert len(trees.children) == 2              # near + far LOD
