"""Collision-mesh extraction from a scenegraph: correctness of the vertex-offset
accounting (the O(M^2) fix) and the min-AABB box substitution for small static
sub-components. No GL.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.basenodes import Transform, Shape
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.physics import gltf_world


def _shape(offset, scale=1.0):
    tri = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype='f') * scale + offset
    return Shape(geometry=PBRMesh(positions=tri, indices=np.array([0, 1, 2], 'u4')))


class TestOffsetAccounting:
    def test_multi_mesh_indices_reference_correct_vertices(self):
        # three separated triangles; each combined triangle must reconstruct one
        # of the originals (indices offset per mesh, not collapsed onto mesh 0).
        g = Transform(children=[_shape(np.array([0, 0, 0], 'f')),
                                _shape(np.array([10, 0, 0], 'f')),
                                _shape(np.array([0, 10, 0], 'f'))])
        points, tris = gltf_world.extract_trimesh(g)
        assert points.shape == (9, 3)
        assert tris.shape == (3, 3)
        centroids = points[tris].mean(axis=1)
        centroids = centroids[np.lexsort(centroids.T)]
        expected = np.array([[1 / 3, 1 / 3, 0], [1 / 3, 10 + 1 / 3, 0],
                             [10 + 1 / 3, 1 / 3, 0]])
        expected = expected[np.lexsort(expected.T)]
        assert np.allclose(centroids, expected, atol=1e-5)

    def test_scales_linearly_not_quadratically(self):
        # O(M^2) offset accumulation makes 4x the meshes cost ~16x; the running
        # counter keeps it ~linear. Use a generous bound (linear ~4x, quad ~16x).
        import time

        def build(m):
            return Transform(children=[_shape(np.array([i * 0.5, 0, 0], 'f'))
                                       for i in range(m)])

        def timed(m):
            g = build(m)
            best = min(_time_once(g) for _ in range(3))
            return best

        def _time_once(g):
            t = time.perf_counter()
            gltf_world.extract_trimesh(g)
            return time.perf_counter() - t

        small = timed(1500)
        large = timed(6000)          # 4x the meshes
        assert large < small * 8.0, (
            "extract_trimesh scales super-linearly (%.1fx for 4x meshes)"
            % (large / small if small else float('inf')))


class TestMinAABBSubstitution:
    def _dense_mesh_shape(self, center, half):
        # a subdivided quad -> many triangles, but a small AABB
        n = 8
        xs = np.linspace(-half, half, n)
        zs = np.linspace(-half, half, n)
        pts = np.array([[x, 0.0, z] for x in xs for z in zs], dtype='f') + center
        tris = []
        for i in range(n - 1):
            for j in range(n - 1):
                a = i * n + j
                tris += [a, a + 1, a + n, a + 1, a + n + 1, a + n]
        return Shape(geometry=PBRMesh(positions=pts,
                                      indices=np.array(tris, 'u4'))), len(tris) // 3

    def test_small_component_becomes_aabb_box(self):
        shape, ntri = self._dense_mesh_shape(np.array([0, 0, 0], 'f'), 0.2)
        assert ntri > 12                                   # genuinely detailed
        g = Transform(children=[shape])
        # diagonal ~ 0.4*sqrt(2) ~ 0.57; threshold above it -> box-ify
        points, tris = gltf_world.extract_trimesh(g, min_hull_size=1.0)
        assert len(points) == 8                            # 8 AABB corners
        assert len(tris) == 12                             # 12 box triangles
        assert np.allclose(points.min(0), [-0.2, 0, -0.2], atol=1e-5)
        assert np.allclose(points.max(0), [0.2, 0, 0.2], atol=1e-5)

    def test_large_component_keeps_full_detail(self):
        shape, ntri = self._dense_mesh_shape(np.array([0, 0, 0], 'f'), 5.0)
        g = Transform(children=[shape])
        points, tris = gltf_world.extract_trimesh(g, min_hull_size=1.0)
        assert len(tris) == ntri                           # full mesh kept

    def test_default_keeps_full_detail(self):
        shape, ntri = self._dense_mesh_shape(np.array([0, 0, 0], 'f'), 0.1)
        g = Transform(children=[shape])
        points, tris = gltf_world.extract_trimesh(g)       # default min_hull_size=0
        assert len(tris) == ntri
