"""Reading a baked irradiance grid, and what a scene does with one.

The grid exists for the objects a lightmap cannot reach: they have no baked
texture coordinate, so without it they are lit by whatever ambient the scene
happens to carry, which in a level that bakes its own lighting is nothing at
all.  What matters about the reading is therefore not precision for its own
sake but that it is defined everywhere -- inside the grid, between samples,
and outside it -- because an object that walks past the last sample must not
go black.
"""

import numpy as np
import pytest

from OpenGLContext.scenegraph.lightgrid import LightGrid, bound_grid


def grid(**named):
    """A 2x2x2 grid one metre on a side, dark at the origin and bright away."""
    counts = named.pop('counts', [2, 2, 2])
    total = int(np.prod(counts))
    ambient = named.pop('ambient', np.zeros((total, 3), dtype='f'))
    directional = named.pop('directional', np.zeros((total, 3), dtype='f'))
    direction = named.pop('direction',
                          np.tile((0.0, 1.0, 0.0), (total, 1)).astype('f'))
    return LightGrid(counts=counts, ambient=ambient, directional=directional,
                     direction=direction, **named)


class TestWhetherThereIsAnythingToLightWith:

    def test_a_node_with_no_samples_is_empty(self):
        assert not LightGrid().filled

    def test_a_node_with_samples_is_filled(self):
        assert grid().filled

    def test_counts_that_are_not_three_axes_are_no_grid(self):
        assert not grid(counts=[2, 2]).filled

    def test_a_zero_count_is_no_grid(self):
        assert not LightGrid(counts=[2, 0, 2]).filled

    def test_samples_short_of_the_counts_are_no_grid(self):
        """Half a grid read as a whole one would index past the end."""
        short = LightGrid(counts=[4, 4, 4], ambient=np.zeros((8, 3), dtype='f'))
        assert not short.filled

    def test_an_empty_grid_still_answers(self):
        ambient, directional, direction = LightGrid().sample((3.0, 4.0, 5.0))
        assert not ambient.any()
        assert not directional.any()
        assert direction == pytest.approx(LightGrid.DEFAULT_DIRECTION)


class TestWhereAPointFallsInTheGrid:

    def test_the_origin_is_the_first_sample(self):
        node = grid(origin=(10.0, 20.0, 30.0), spacing=(2.0, 2.0, 2.0))
        assert node.cell((10.0, 20.0, 30.0)) == pytest.approx([0, 0, 0])

    def test_a_point_a_cell_along_is_the_next_sample(self):
        node = grid(origin=(10.0, 20.0, 30.0), spacing=(2.0, 4.0, 8.0))
        assert node.cell((12.0, 24.0, 38.0)) == pytest.approx([1, 1, 1])

    def test_a_point_outside_lands_on_the_edge(self):
        """An object past the last sample keeps the light of the nearest."""
        node = grid(spacing=(1.0, 1.0, 1.0))
        assert node.cell((-50.0, 0.5, 900.0)) == pytest.approx([0, 0.5, 1])

    def test_a_grid_of_no_extent_reads_as_its_first_sample(self):
        node = grid(spacing=(0.0, 1.0, 1.0))
        assert node.cell((7.0, 0.0, 0.0))[0] == pytest.approx(0.0)


class TestTheLightThatComesBack:

    def _lit(self, **named):
        """A grid whose x=1 samples are white and whose x=0 samples are black."""
        ambient = np.zeros((8, 3), dtype='f')
        ambient[1::2] = 1.0                     # x varies fastest
        return grid(ambient=ambient, **named)

    def test_a_sample_point_reads_its_own_sample(self):
        ambient, _directional, _direction = self._lit().sample((1.0, 0.0, 0.0))
        assert ambient == pytest.approx([1.0, 1.0, 1.0])

    def test_the_far_corner_reads_the_far_sample(self):
        ambient, _d, _dir = self._lit().sample((0.0, 1.0, 1.0))
        assert ambient == pytest.approx([0.0, 0.0, 0.0])

    def test_halfway_between_two_samples_is_halfway_between_them(self):
        ambient, _d, _dir = self._lit().sample((0.5, 0.0, 0.0))
        assert ambient == pytest.approx([0.5, 0.5, 0.5])

    def test_the_axis_the_light_does_not_vary_along_changes_nothing(self):
        node = self._lit()
        near = node.sample((0.5, 0.0, 0.0))[0]
        far = node.sample((0.5, 1.0, 1.0))[0]
        assert near == pytest.approx(far)

    def test_intensity_scales_what_is_read(self):
        ambient, _d, _dir = self._lit(intensity=0.25).sample((1.0, 0.0, 0.0))
        assert ambient == pytest.approx([0.25, 0.25, 0.25])

    def test_the_directional_term_is_read_too(self):
        directional = np.zeros((8, 3), dtype='f')
        directional[:] = (0.4, 0.5, 0.6)
        _a, read, _dir = grid(directional=directional).sample((0.5, 0.5, 0.5))
        assert read == pytest.approx([0.4, 0.5, 0.6], abs=1e-6)

    def test_the_direction_comes_back_a_unit_vector(self):
        direction = np.zeros((8, 3), dtype='f')
        direction[:] = (0.0, 3.0, 4.0)          # deliberately not unit length
        _a, _d, read = grid(direction=direction).sample((0.5, 0.5, 0.5))
        assert np.linalg.norm(read) == pytest.approx(1.0)
        assert read == pytest.approx([0.0, 0.6, 0.8], abs=1e-6)

    def test_two_samples_pointing_opposite_ways_fall_back(self):
        """Their average is no direction at all, and shading needs one."""
        direction = np.tile((0.0, 1.0, 0.0), (8, 1)).astype('f')
        direction[1::2] = (0.0, -1.0, 0.0)
        _a, _d, read = grid(direction=direction).sample((0.5, 0.0, 0.0))
        assert read == pytest.approx(LightGrid.DEFAULT_DIRECTION)


class TestChoosingTheGridAScenePutsIn:

    def test_no_paths_is_no_grid(self):
        assert bound_grid(()) is None

    def test_an_empty_node_is_passed_over(self):
        assert bound_grid([[LightGrid()]]) is None

    def test_the_first_filled_grid_wins(self):
        first, second = grid(), grid()
        assert bound_grid([[LightGrid()], [first], [second]]) is first
