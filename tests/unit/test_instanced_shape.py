"""Many placements of one shape, held as a single node.

A baked forest is one tree mesh put down a few dozen times per tile. Modelled as
a few dozen nodes it is a few dozen of everything the render pass does per object
-- a world matrix, a bounding volume, a frustum test, a batch key -- before the
instancing batcher collapses them into the one draw the card was always going to
do. ``InstancedShape`` is those placements as one object.
"""
import numpy as np
import pytest

from OpenGLContext.passes.instancing import (
    build_instance_groups, instance_counts, instance_matrices, record_placements,
)
from OpenGLContext.scenegraph.instancedshape import InstancedShape, placement_matrices
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.shape import Shape


def _mesh(size=1.0):
    return PBRMesh(positions=np.array(
        [(0, 0, 0), (size, 0, 0), (0, size, 0)], 'f'))


def _at(x=0.0, y=0.0, z=0.0):
    matrix = np.identity(4, 'f')
    matrix[3, :3] = (x, y, z)
    return matrix


def _record(shape, matrix=None):
    matrix = np.identity(4, 'f') if matrix is None else matrix
    return ((False, [], 0.0), matrix, matrix, None, [shape])


class TestBuildingThePlacements:
    def test_translations_become_matrices(self) -> None:
        matrices = placement_matrices(translations=[(1, 2, 3), (4, 5, 6)])
        assert matrices.shape == (2, 4, 4)
        assert np.allclose(matrices[0][3, :3], (1, 2, 3))
        assert np.allclose(matrices[1][3, :3], (4, 5, 6))

    def test_scales_go_down_the_diagonal(self) -> None:
        matrices = placement_matrices(translations=[(0, 0, 0)],
                                      scales=[(2.0, 3.0, 4.0)])
        assert np.allclose(np.diag(matrices[0])[:3], (2.0, 3.0, 4.0))

    def test_a_quarter_turn_about_y_moves_x_to_minus_z(self) -> None:
        half = np.sqrt(0.5)
        matrices = placement_matrices(translations=[(0, 0, 0)],
                                      rotations=[(0.0, half, 0.0, half)])
        point = np.array([1.0, 0.0, 0.0, 1.0]) @ matrices[0]
        assert np.allclose(point[:3], (0.0, 0.0, -1.0), atol=1e-6)

    def test_rotation_is_applied_before_the_translation(self) -> None:
        half = np.sqrt(0.5)
        matrices = placement_matrices(translations=[(10.0, 0.0, 0.0)],
                                      rotations=[(0.0, half, 0.0, half)])
        point = np.array([1.0, 0.0, 0.0, 1.0]) @ matrices[0]
        assert np.allclose(point[:3], (10.0, 0.0, -1.0), atol=1e-6)

    def test_the_count_comes_from_whichever_is_given(self) -> None:
        assert len(placement_matrices(scales=[(1, 1, 1)] * 5)) == 5
        assert len(placement_matrices(rotations=[(0, 0, 0, 1)] * 3)) == 3

    def test_nothing_at_all_is_no_placements(self) -> None:
        assert len(placement_matrices()) == 0


class TestTheNode:
    def test_it_is_a_shape(self) -> None:
        node = InstancedShape(geometry=_mesh())
        assert isinstance(node, Shape)

    def test_it_carries_its_placements(self) -> None:
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(0, 0, 0), (5, 0, 0)]))
        assert len(node.placements) == 2

    def test_its_bounds_cover_every_placement(self) -> None:
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(0, 0, 0), (100, 0, 0)]))
        points = np.asarray(node.boundingVolume(None).getPoints())
        assert points[:, 0].max() >= 100.0
        assert points[:, 0].min() <= 0.0

    def test_bounds_follow_a_change_of_placements(self) -> None:
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(0, 0, 0)]))
        near = np.asarray(node.boundingVolume(None).getPoints())[:, 0].max()
        node.placements = placement_matrices(translations=[(0, 0, 0), (50, 0, 0)])
        far = np.asarray(node.boundingVolume(None).getPoints())[:, 0].max()
        assert far > near

    def test_bounds_follow_a_change_of_geometry(self) -> None:
        node = InstancedShape(geometry=_mesh(1.0),
                              placements=placement_matrices(
                                  translations=[(0, 0, 0)]))
        small = np.asarray(node.boundingVolume(None).getPoints())[:, 0].max()
        node.geometry = _mesh(20.0)
        large = np.asarray(node.boundingVolume(None).getPoints())[:, 0].max()
        assert large > small

    def test_with_no_placements_it_bounds_nothing(self) -> None:
        node = InstancedShape(geometry=_mesh())
        assert not len(np.asarray(node.boundingVolume(None).getPoints()))

    def test_with_no_geometry_it_bounds_nothing(self) -> None:
        node = InstancedShape(placements=placement_matrices(
            translations=[(0, 0, 0)]))
        assert not len(np.asarray(node.boundingVolume(None).getPoints()))


class TestWhatTheRenderPassSeesOfIt:
    def test_a_plain_shape_carries_no_placements(self) -> None:
        assert record_placements(_record(Shape(geometry=_mesh()))) is None

    def test_an_instanced_shape_carries_them(self) -> None:
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(0, 0, 0), (5, 0, 0)]))
        assert len(record_placements(_record(node))) == 2

    def test_an_empty_instanced_shape_carries_none(self) -> None:
        """Nothing to draw, so nothing for the batcher to expand."""
        assert record_placements(_record(InstancedShape(geometry=_mesh()))) is None

    def test_a_plain_shape_counts_as_one(self) -> None:
        assert instance_counts([_record(Shape(geometry=_mesh()))]) == [1]

    def test_an_instanced_shape_counts_as_its_placements(self) -> None:
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(0, 0, 0)] * 7))
        assert instance_counts([_record(node)]) == [7]


class TestTheMatricesItDrawsAt:
    def test_a_plain_record_gives_its_own(self) -> None:
        matrix = _at(3.0)
        out = instance_matrices([_record(Shape(geometry=_mesh()), matrix)])
        assert out.shape == (1, 4, 4)
        assert np.allclose(out[0], matrix)

    def test_each_placement_sits_inside_the_record(self) -> None:
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(1, 0, 0), (2, 0, 0)]))
        out = instance_matrices([_record(node, _at(10.0))])
        assert out.shape == (2, 4, 4)
        assert np.allclose(out[0][3, :3], (11, 0, 0))
        assert np.allclose(out[1][3, :3], (12, 0, 0))

    def test_records_come_out_in_order(self) -> None:
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(1, 0, 0), (2, 0, 0)]))
        plain = Shape(geometry=_mesh())
        out = instance_matrices([_record(node), _record(plain, _at(99.0))])
        assert [float(m[3, 0]) for m in out] == [1.0, 2.0, 99.0]

    def test_a_further_matrix_is_applied_to_all_of_them(self) -> None:
        """How the depth pass gets light space out of world transforms."""
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(1, 0, 0), (2, 0, 0)]))
        out = instance_matrices([_record(node)], index=2, after=_at(0.0, 5.0))
        assert [float(m[3, 1]) for m in out] == [5.0, 5.0]

    def test_no_records_is_an_empty_array_not_an_error(self) -> None:
        assert instance_matrices([]).shape == (0, 4, 4)


class TestGroupingCountsInstances:
    def test_one_node_of_many_placements_is_worth_a_group(self) -> None:
        """A single record, but twelve draws: the threshold is about the draws."""
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(i, 0, 0) for i in range(12)]))
        groups, singles = build_instance_groups(
            [_record(node)], min_instances=8,
            instanceable=lambda path: True)
        assert len(groups) == 1 and singles == []
        assert len(groups[0]) == 12

    def test_too_few_placements_falls_through_to_singles(self) -> None:
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(0, 0, 0), (1, 0, 0)]))
        groups, singles = build_instance_groups(
            [_record(node)], min_instances=8, instanceable=lambda path: True)
        assert groups == [] and len(singles) == 1

    def test_placements_and_plain_shapes_count_together(self) -> None:
        geometry = _mesh()
        node = InstancedShape(geometry=geometry,
                              placements=placement_matrices(
                                  translations=[(0, 0, 0)] * 6))
        plain = [Shape(geometry=geometry) for _ in range(3)]
        groups, _ = build_instance_groups(
            [_record(node)] + [_record(s) for s in plain],
            min_instances=8, instanceable=lambda path: True)
        assert len(groups) == 1
        assert len(groups[0]) == 9

    def test_a_group_still_reports_its_members(self) -> None:
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(0, 0, 0)] * 6))
        groups, _ = build_instance_groups(
            [_record(node)], min_instances=2, instanceable=lambda path: True)
        assert len(groups[0].members) == 1


class TestDrawingItWithoutInstancing:
    """Instancing can be off -- an old driver, a pass that does not batch -- and
    the node still has to draw every placement."""

    def test_it_renders_once_per_placement(self) -> None:
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(1, 0, 0), (2, 0, 0), (3, 0, 0)]))
        seen = []

        class Mode:
            shader_mode = True
            shader_program = object()
            matrix = np.identity(4, 'f')
            projection = np.identity(4, 'f')
            shadow_pass = True

        mode = Mode()

        def watch(mode=None, **named):
            seen.append(np.array(mode.matrix))

        node.geometry.render = watch
        node.Render(mode=mode)
        assert len(seen) == 3
        assert [float(m[3, 0]) for m in seen] == [1.0, 2.0, 3.0]

    def test_the_pass_matrix_is_left_as_it_was(self) -> None:
        node = InstancedShape(geometry=_mesh(),
                              placements=placement_matrices(
                                  translations=[(1, 0, 0)]))

        class Mode:
            shader_mode = True
            shader_program = object()
            matrix = _at(7.0)
            projection = np.identity(4, 'f')
            shadow_pass = True

        mode = Mode()
        before = np.array(mode.matrix)
        node.geometry.render = lambda mode=None, **named: None
        node.Render(mode=mode)
        assert np.allclose(mode.matrix, before)

    def test_with_no_placements_it_draws_nothing(self) -> None:
        node = InstancedShape(geometry=_mesh())
        seen = []
        node.geometry.render = lambda mode=None, **named: seen.append(1)

        class Mode:
            shader_mode = True
            shader_program = object()
            matrix = np.identity(4, 'f')
            projection = np.identity(4, 'f')
            shadow_pass = True

        node.Render(mode=Mode())
        assert seen == []


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
