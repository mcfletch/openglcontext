"""Folding the directions you can look at something from onto a square.

An impostor replaces a model with a picture of it, and the picture that is
right depends on where you are looking from. Keeping one picture per direction
means keeping a *sphere* of them, and a sphere does not fit in a texture. The
octahedral map is how it is made to: inflate an octahedron to the sphere, cut
it along its equator, unfold it flat. Directions near each other in space land
near each other on the square, which is what lets four neighbouring pictures be
blended into the view you actually have.

Two layouts. The **hemi** one holds the upper hemisphere only, which is what a
thing standing on the ground needs -- nobody walks under a bust -- and spends
the whole square on it. The **full** one holds the sphere, folded so the lower
half occupies the corners.

No GL: this is the arithmetic the shader and the baker have to agree on, and
they only agree if it is the same arithmetic.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph import octahedral

UP = (0.0, 1.0, 0.0)


def unit(vector):
    array = np.asarray(vector, dtype='d')
    return array / np.linalg.norm(array)


class TestTheHemisphereLayout:
    def test_straight_up_is_the_middle_of_the_square(self, ):
        assert octahedral.direction_to_uv(UP) == pytest.approx([0.5, 0.5])

    @pytest.mark.parametrize('direction,corner', [
        ((1, 0, 0), [1.0, 0.0]),
        ((0, 0, 1), [1.0, 1.0]),
        ((-1, 0, 0), [0.0, 1.0]),
        ((0, 0, -1), [0.0, 0.0]),
    ])
    def test_the_horizon_goes_to_the_edges(self, direction, corner):
        """The four compass points land on the square's four corners."""
        assert octahedral.direction_to_uv(direction) == pytest.approx(corner)

    def test_every_direction_lands_inside_the_square(self):
        rng = np.random.default_rng(7)
        for _try in range(200):
            direction = unit(rng.normal(size=3))
            direction[1] = abs(direction[1])
            u, v = octahedral.direction_to_uv(direction)

            assert -1e-9 <= u <= 1 + 1e-9 and -1e-9 <= v <= 1 + 1e-9

    def test_it_comes_back_the_way_it_went_in(self):
        rng = np.random.default_rng(11)
        for _try in range(200):
            direction = unit(rng.normal(size=3))
            direction[1] = abs(direction[1])

            back = octahedral.uv_to_direction(
                octahedral.direction_to_uv(direction))

            assert back == pytest.approx(direction, abs=1e-9)

    def test_near_in_space_is_near_on_the_square(self):
        """What makes blending between neighbouring views mean anything."""
        first = octahedral.direction_to_uv(unit((1.0, 1.0, 0.0)))
        near = octahedral.direction_to_uv(unit((1.0, 1.02, 0.0)))
        far = octahedral.direction_to_uv(unit((-1.0, 1.0, 0.0)))

        assert np.linalg.norm(np.subtract(first, near)) < \
            np.linalg.norm(np.subtract(first, far))

    def test_a_direction_below_the_horizon_is_folded_up_to_it(self):
        """A hemi atlas has no picture from underneath; the nearest it has is
        the horizon, which is what a thing on the ground is seen against."""
        found = octahedral.direction_to_uv((0.3, -0.9, 0.0))

        assert 0.0 <= found[0] <= 1.0 and 0.0 <= found[1] <= 1.0


class TestTheWholeSphereLayout:
    def test_straight_up_is_the_middle(self):
        assert octahedral.direction_to_uv(UP, hemi=False) == \
            pytest.approx([0.5, 0.5])

    def test_straight_down_is_the_corners(self):
        u, v = octahedral.direction_to_uv((0.0, -1.0, 0.0), hemi=False)

        assert (round(u), round(v)) in {(0, 0), (0, 1), (1, 0), (1, 1)}

    def test_it_comes_back_the_way_it_went_in(self):
        rng = np.random.default_rng(13)
        for _try in range(200):
            direction = unit(rng.normal(size=3))

            back = octahedral.uv_to_direction(
                octahedral.direction_to_uv(direction, hemi=False), hemi=False)

            assert back == pytest.approx(direction, abs=1e-9)

    def test_the_two_layouts_disagree_below_the_horizon(self):
        under = (0.2, -0.95, 0.1)

        assert octahedral.direction_to_uv(under) != \
            pytest.approx(octahedral.direction_to_uv(under, hemi=False))


class TestTheViewsAnAtlasHolds:
    def test_a_grid_of_them(self):
        assert len(octahedral.view_directions(4)) == 16

    def test_each_is_a_unit_vector(self):
        for direction in octahedral.view_directions(3):
            assert np.linalg.norm(direction) == pytest.approx(1.0)

    def test_a_hemi_atlas_looks_only_from_above(self):
        for direction in octahedral.view_directions(5):
            assert direction[1] >= -1e-9

    def test_a_full_atlas_looks_from_everywhere(self):
        below = [d for d in octahedral.view_directions(5, hemi=False)
                 if d[1] < 0]

        assert below

    def test_they_are_the_cell_centres(self):
        """A view is the middle of the square it fills, not its corner: a view
        baked at the corner is the same view as its neighbour's corner."""
        directions = octahedral.view_directions(2)
        corners = [octahedral.uv_to_direction((0.0, 0.0)),
                   octahedral.uv_to_direction((1.0, 1.0))]

        for direction in directions:
            for corner in corners:
                assert np.linalg.norm(np.subtract(direction, corner)) > 1e-6

    def test_one_view_is_straight_up(self):
        """An odd grid has a middle cell, and the middle is the pole."""
        directions = octahedral.view_directions(3)

        assert any(np.allclose(d, UP, atol=1e-9) for d in directions)


class TestFindingTheViewToDrawFrom:
    def test_the_cell_a_direction_falls_in(self):
        cell = octahedral.cell_of(UP, grid=3)

        assert cell == (1, 1)

    def test_a_direction_at_a_view_picks_that_view(self):
        for index, direction in enumerate(octahedral.view_directions(4)):
            row, column = divmod(index, 4)

            assert octahedral.cell_of(direction, grid=4) == (row, column)

    def test_a_cell_is_never_off_the_grid(self):
        rng = np.random.default_rng(3)
        for _try in range(200):
            direction = unit(rng.normal(size=3))
            direction[1] = abs(direction[1])
            row, column = octahedral.cell_of(direction, grid=6)

            assert 0 <= row < 6 and 0 <= column < 6


class TestWhereAViewSitsInTheImage:
    def test_a_grid_fills_the_image(self):
        assert octahedral.tile_size(256, grid=8) == 32

    def test_an_image_that_does_not_divide_is_refused(self):
        with pytest.raises(ValueError):
            octahedral.tile_size(250, grid=8)

    def test_the_first_tile_is_the_top_left(self):
        assert octahedral.tile_origin(0, 0, 256, grid=8) == (0, 0)

    def test_tiles_do_not_overlap(self):
        seen = {octahedral.tile_origin(row, column, 256, grid=8)
                for row in range(8) for column in range(8)}

        assert len(seen) == 64

    def test_a_tile_of_a_single_pixel_is_refused(self):
        """Below a few pixels a view is not a picture of anything."""
        with pytest.raises(ValueError):
            octahedral.tile_size(8, grid=8)
