"""Headless tests for Stage 2 grouping: batch by geometry + texture set, with a
per-group material table so instances differing only by material FACTORS still
collapse into one instanced draw (each instance indexes its own material).
"""
from OpenGLContext.passes.instancing import (
    geometry_texture_key, build_instance_groups, group_material_table,
)


class FakeGeometry:
    def __init__(self, name):
        self.name = name


class FakeMaterial:
    def __init__(self, name):
        self.name = name


def real_material(baseColor):
    """A material the packer actually reads.

    The table groups by what a material *says*, so telling two of them apart
    means giving them different factors rather than different names.
    """
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    return PBRMaterial(baseColor=baseColor)


class FakeShape:
    def __init__(self, geometry, material=None, texture=None):
        self.geometry = geometry
        self.appearance = type('A', (), {'material': material, 'texture': texture})()


def rec(shape):
    return ((False, [], 0.0), [[1]], [[1]], None, [shape])


def instanceable(path):
    return True


class TestTextureKeyGroupsAcrossMaterials:
    def test_same_geometry_same_texture_different_material_groups(self):
        g = FakeGeometry('g')
        a = rec(FakeShape(g, FakeMaterial('m1')))   # untextured, factors differ
        b = rec(FakeShape(g, FakeMaterial('m2')))
        assert geometry_texture_key(a[-1]) == geometry_texture_key(b[-1])

    def test_different_texture_splits(self):
        g = FakeGeometry('g')
        t1, t2 = object(), object()
        a = rec(FakeShape(g, FakeMaterial('m'), texture=t1))
        b = rec(FakeShape(g, FakeMaterial('m'), texture=t2))
        assert geometry_texture_key(a[-1]) != geometry_texture_key(b[-1])

    def test_different_geometry_splits(self):
        m = FakeMaterial('m')
        a = rec(FakeShape(FakeGeometry('g1'), m))
        b = rec(FakeShape(FakeGeometry('g2'), m))
        assert geometry_texture_key(a[-1]) != geometry_texture_key(b[-1])


class TestMaterialTable:
    def test_distinct_materials_indexed_in_first_seen_order(self):
        g = FakeGeometry('g')
        m1 = real_material((1.0, 0.0, 0.0))
        m2 = real_material((0.0, 0.0, 1.0))
        members = [rec(FakeShape(g, m1)), rec(FakeShape(g, m2)),
                   rec(FakeShape(g, m1))]
        groups, _ = build_instance_groups(
            members, min_instances=2, key=geometry_texture_key,
            instanceable=instanceable)
        assert len(groups) == 1
        materials, indices = group_material_table(groups[0])
        assert materials == [m1, m2]        # first-seen order
        assert indices == [0, 1, 0]         # per-member index into the table

    def test_single_material_group_all_index_zero(self):
        g = FakeGeometry('g')
        m = FakeMaterial('m')
        members = [rec(FakeShape(g, m)) for _ in range(4)]
        groups, _ = build_instance_groups(
            members, min_instances=2, key=geometry_texture_key,
            instanceable=instanceable)
        materials, indices = group_material_table(groups[0])
        assert materials == [m]
        assert indices == [0, 0, 0, 0]


class TestOneMaterialManyObjects:
    """A crowd out of one document carries a material object per figure."""

    def test_materials_that_say_the_same_thing_share_a_slot(self):
        g = FakeGeometry('g')
        copies = [real_material((0.2, 0.4, 0.6)) for _ in range(5)]
        members = [rec(FakeShape(g, m)) for m in copies]

        groups, _ = build_instance_groups(
            members, min_instances=2, key=geometry_texture_key,
            instanceable=instanceable)
        materials, indices = group_material_table(groups[0])

        assert len(materials) == 1
        assert indices == [0, 0, 0, 0, 0]
