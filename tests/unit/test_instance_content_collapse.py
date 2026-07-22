"""Headless tests for Stage 3 opportunistic collapse: distinct geometry NODES
that carry identical vertex content batch together (glTF repeated meshes, or the
same primitive authored several times), keyed by content rather than identity.
"""
import numpy as np

from OpenGLContext.passes.instancing import (
    geometry_content_key, build_instance_groups,
)
from OpenGLContext.scenegraph.pbrmesh import PBRMesh


class FakeShape:
    def __init__(self, geometry, material=None):
        self.geometry = geometry
        self.appearance = type('A', (), {'material': material, 'texture': None})()


def mesh(seed=0):
    tri = np.array([(0, 0, 0), (1, 0, 0), (seed, 1, 0)], 'f')
    return PBRMesh(positions=tri, normals=[(0, 0, 1)] * 3, indices=[0, 1, 2])


def rec(shape):
    return ((False, [], 0.0), np.eye(4), np.eye(4), None, [shape])


class TestContentKey:
    def test_distinct_nodes_same_content_same_key(self):
        # Two separate PBRMesh objects, identical arrays -> identical content key.
        a, b = mesh(0), mesh(0)
        assert a is not b
        assert geometry_content_key([FakeShape(a)]) == geometry_content_key([FakeShape(b)])

    def test_different_content_different_key(self):
        assert (geometry_content_key([FakeShape(mesh(0))])
                != geometry_content_key([FakeShape(mesh(9))]))

    def test_key_is_cached_on_node(self):
        m = mesh(0)
        geometry_content_key([FakeShape(m)])
        assert getattr(m, '_instance_content_id', None) is not None


class TestCollapseGrouping:
    def test_identical_distinct_nodes_collapse(self):
        m1, m2, m3 = mesh(0), mesh(0), mesh(0)   # distinct nodes, same content
        recs = [rec(FakeShape(m1)), rec(FakeShape(m2)), rec(FakeShape(m3))]
        groups, singles = build_instance_groups(
            recs, min_instances=2, key=geometry_content_key,
            instanceable=lambda p: True)
        assert len(groups) == 1
        assert len(groups[0].members) == 3
        assert singles == []

    def test_identity_key_would_not_collapse(self):
        # Contrast: the identity key keeps distinct nodes separate (why Stage 3
        # needs a content key).
        from OpenGLContext.passes.instancing import geometry_instance_key
        recs = [rec(FakeShape(mesh(0))) for _ in range(3)]
        groups, singles = build_instance_groups(
            recs, min_instances=2, key=geometry_instance_key,
            instanceable=lambda p: True)
        assert groups == []
        assert len(singles) == 3
