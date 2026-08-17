"""Headless tests for the instanced-geometry grouping engine.

The renderer collapses many render records that share one geometry (and a
compatible appearance) into a single instanced draw. This engine decides which
records group together, honouring a minimum-instance threshold and a predicate
for which geometry can actually be drawn instanced. No GL required.
"""
from OpenGLContext.passes.instancing import (
    build_instance_groups, geometry_instance_key, InstanceGroup,
)


class FakeGeometry:
    """A geometry node; instanceability is flagged for the test predicate."""
    def __init__(self, name, instanceable=True):
        self.name = name
        self._instanceable = instanceable


class FakeShape:
    def __init__(self, geometry, material=None, texture=None):
        self.geometry = geometry
        self.appearance = type('A', (), {'material': material, 'texture': texture})()


def rec(shape, mv=None):
    # (sortKey, mvmatrix, tmatrix, bvolume, path); path[-1] is the shape.
    key = (False, [], 0.0)
    return (key, mv or [[1]], [[1]], None, [shape])


def instanceable(path):
    return getattr(path[-1].geometry, '_instanceable', False)


class TestGeometryKey:
    def test_same_geometry_and_appearance_same_key(self):
        g = FakeGeometry('g')
        m = object()
        a, b = rec(FakeShape(g, m)), rec(FakeShape(g, m))
        assert geometry_instance_key(a[-1]) == geometry_instance_key(b[-1])

    def test_different_material_differs(self):
        g = FakeGeometry('g')
        a = rec(FakeShape(g, object()))
        b = rec(FakeShape(g, object()))
        assert geometry_instance_key(a[-1]) != geometry_instance_key(b[-1])

    def test_different_geometry_differs(self):
        m = object()
        a = rec(FakeShape(FakeGeometry('g1'), m))
        b = rec(FakeShape(FakeGeometry('g2'), m))
        assert geometry_instance_key(a[-1]) != geometry_instance_key(b[-1])


class TestGrouping:
    def test_two_shared_records_form_one_group(self):
        g = FakeGeometry('g')
        m = object()
        records = [rec(FakeShape(g, m)), rec(FakeShape(g, m))]
        groups, singles = build_instance_groups(
            records, min_instances=2, instanceable=instanceable)
        assert len(groups) == 1
        assert isinstance(groups[0], InstanceGroup)
        assert len(groups[0].members) == 2
        assert groups[0].geometry is g
        assert singles == []

    def test_below_threshold_stays_single(self):
        g = FakeGeometry('g')
        records = [rec(FakeShape(g, object()))]  # unique material -> group of 1
        groups, singles = build_instance_groups(
            records, min_instances=2, instanceable=instanceable)
        assert groups == []
        assert len(singles) == 1

    def test_threshold_of_three(self):
        g = FakeGeometry('g')
        m = object()
        records = [rec(FakeShape(g, m)) for _ in range(3)]
        # min 4 -> not grouped; min 3 -> grouped.
        groups4, singles4 = build_instance_groups(
            records, min_instances=4, instanceable=instanceable)
        assert groups4 == [] and len(singles4) == 3
        groups3, singles3 = build_instance_groups(
            records, min_instances=3, instanceable=instanceable)
        assert len(groups3) == 1 and singles3 == []

    def test_non_instanceable_geometry_never_grouped(self):
        g = FakeGeometry('g', instanceable=False)
        m = object()
        records = [rec(FakeShape(g, m)) for _ in range(5)]
        groups, singles = build_instance_groups(
            records, min_instances=2, instanceable=instanceable)
        assert groups == []
        assert len(singles) == 5

    def test_mixed_scene_partitions_correctly(self):
        shared = FakeGeometry('shared')
        m = object()
        unique = FakeGeometry('unique')
        records = [
            rec(FakeShape(shared, m)),
            rec(FakeShape(shared, m)),
            rec(FakeShape(shared, m)),
            rec(FakeShape(unique, object())),      # one-off
        ]
        groups, singles = build_instance_groups(
            records, min_instances=2, instanceable=instanceable)
        assert len(groups) == 1
        assert len(groups[0].members) == 3
        assert len(singles) == 1
        assert singles[0][-1][-1].geometry is unique

    def test_every_record_accounted_for_once(self):
        g1, g2 = FakeGeometry('a'), FakeGeometry('b')
        m1, m2 = object(), object()
        records = [rec(FakeShape(g1, m1)), rec(FakeShape(g1, m1)),
                   rec(FakeShape(g2, m2)), rec(FakeShape(g2, m2)),
                   rec(FakeShape(g1, object()))]
        groups, singles = build_instance_groups(
            records, min_instances=2, instanceable=instanceable)
        grouped = sum(len(gr.members) for gr in groups)
        assert grouped + len(singles) == len(records)


class TestOneShapeIsKeyedOnce:
    """A baked forest is one Shape placed a few dozen times per tile, and every
    placement is its own record. The batch key reads nothing but the Shape, so
    asking it of each placement asks the same question a few dozen times -- and
    a content key hashes vertex data to answer it."""

    def test_the_key_is_asked_once_per_shape(self):
        g = FakeGeometry('g')
        m = object()
        shape = FakeShape(g, m)
        asked = []

        def counting(path):
            asked.append(path[-1])
            return geometry_instance_key(path)

        records = [rec(shape) for _ in range(24)]
        build_instance_groups(records, min_instances=2, key=counting,
                              instanceable=instanceable)
        assert len(asked) == 1

    def test_distinct_shapes_are_each_asked(self):
        g = FakeGeometry('g')
        m = object()
        asked = []

        def counting(path):
            asked.append(path[-1])
            return geometry_instance_key(path)

        records = [rec(FakeShape(g, m)) for _ in range(5)]
        build_instance_groups(records, min_instances=2, key=counting,
                              instanceable=instanceable)
        assert len(asked) == 5

    def test_the_grouping_is_the_same_either_way(self):
        g1, g2 = FakeGeometry('a'), FakeGeometry('b')
        m1, m2 = object(), object()
        one, two = FakeShape(g1, m1), FakeShape(g2, m2)
        records = ([rec(one) for _ in range(3)] + [rec(two) for _ in range(4)]
                   + [rec(one)])
        groups, singles = build_instance_groups(
            records, min_instances=2, instanceable=instanceable)
        assert sorted(len(gr.members) for gr in groups) == [4, 4]
        assert singles == []

    def test_a_shape_that_cannot_be_instanced_is_asked_about_once_too(self):
        shape = FakeShape(FakeGeometry('g', instanceable=False), object())
        asked = []

        def counting(path):
            asked.append(path[-1])
            return geometry_instance_key(path)

        records = [rec(shape) for _ in range(6)]
        groups, singles = build_instance_groups(
            records, min_instances=2, key=counting, instanceable=instanceable)
        assert groups == [] and len(singles) == 6
        assert len(asked) == 1
