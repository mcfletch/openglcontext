"""Headless tests for cluster culling of instanced records.

Off-screen instances are ALREADY removed per-object by the pass's
``frustumVisibilityFilter`` before grouping (verified separately), so cluster
culling is not about correctness -- it is a per-frame *cost* optimization for
large static fields: spatially sort instances (Morton/Z-order), partition into
contiguous clusters with a combined AABB, and skip the per-instance frustum test
for every instance in a cluster that is wholly outside the frustum ("optimise out
clusters when not in frame"). These tests exercise the pure algorithm with fake
frustum tests -- no GL.
"""
import numpy as np

from OpenGLContext.passes.instancing import (
    morton_order, build_clusters, cluster_cull,
)


class TestMortonOrder:
    def test_preserves_all_indices(self):
        pts = np.random.RandomState(0).rand(50, 3)
        order = morton_order(pts)
        assert sorted(order) == list(range(50))

    def test_neighbours_are_spatially_close(self):
        # A line of points along x: Morton order keeps consecutive points adjacent.
        pts = np.array([(x, 0.0, 0.0) for x in range(20)], 'f')
        order = morton_order(pts)
        # Adjacent in Morton order => adjacent in x (monotone along a single axis).
        xs = pts[order][:, 0]
        assert np.all(np.diff(xs) > 0) or np.all(np.diff(xs) < 0)

    def test_single_point(self):
        assert list(morton_order(np.array([(1.0, 2.0, 3.0)], 'f'))) == [0]


class TestBuildClusters:
    def test_partitions_into_size_capped_clusters(self):
        pts = np.random.RandomState(1).rand(100, 3)
        clusters = build_clusters(pts, cluster_size=16)
        # Every index appears exactly once across clusters.
        seen = sorted(i for c in clusters for i in c.indices)
        assert seen == list(range(100))
        assert all(len(c.indices) <= 16 for c in clusters)
        assert len(clusters) == 7  # ceil(100/16)

    def test_cluster_aabb_bounds_its_members(self):
        pts = np.random.RandomState(2).rand(40, 3) * 10
        for c in build_clusters(pts, cluster_size=8):
            members = pts[c.indices]
            assert np.all(c.aabb_min <= members.min(axis=0) + 1e-6)
            assert np.all(c.aabb_max >= members.max(axis=0) - 1e-6)


class TestClusterCull:
    def _run(self, positions, cluster_visible, instance_visible, cluster_size=8):
        records = list(range(len(positions)))
        calls = {'instance': 0, 'cluster': 0}

        def cvis(mn, mx):
            calls['cluster'] += 1
            return cluster_visible(mn, mx)

        def ivis(rec):
            calls['instance'] += 1
            return instance_visible(rec)

        kept = cluster_cull(records, positions, cvis, ivis, cluster_size=cluster_size)
        return kept, calls

    def test_all_visible_keeps_everything(self):
        pts = np.random.RandomState(3).rand(30, 3)
        kept, _ = self._run(pts, lambda mn, mx: True, lambda r: True)
        assert sorted(kept) == list(range(30))

    def test_offscreen_cluster_skips_per_instance_tests(self):
        # Two well-separated blobs; make one blob's cluster test say "outside".
        near = np.random.RandomState(4).rand(16, 3)
        far = np.random.RandomState(5).rand(16, 3) + 1000.0
        pts = np.concatenate([near, far])

        def cluster_visible(mn, mx):
            return mn[0] < 500.0  # far blob (x ~ 1000) is outside

        kept, calls = self._run(pts, cluster_visible, lambda r: True, cluster_size=16)
        # The far instances are culled without any per-instance test on them.
        assert all(r < 16 for r in kept)
        assert calls['instance'] <= 16   # only the near cluster is expanded

    def test_boundary_cluster_falls_back_to_per_instance(self):
        pts = np.random.RandomState(6).rand(8, 3)
        # Cluster is "maybe visible"; per-instance test keeps only even records.
        kept, calls = self._run(pts, lambda mn, mx: True,
                                lambda r: r % 2 == 0, cluster_size=8)
        assert sorted(kept) == [0, 2, 4, 6]
        assert calls['instance'] == 8
