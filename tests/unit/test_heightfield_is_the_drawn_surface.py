"""The height a field reports is the height of the surface it draws.

A :class:`HeightField` answers three questions about the same ground, and every
one of them has to give the same answer:

* :meth:`~HeightField.mesh` is what the player *sees* -- a triangulated grid;
* :class:`~OpenGLContext.physics.heightfield.HeightFieldColliders` cuts what a
  car drives on out of that same grid;
* :meth:`~HeightField.sample` is what everything analytic stands on -- the
  walker's floor, the seat of every scattered plant, the slope a mask thins
  grass by.

A quad has no single flat surface through its four corners, so a grid of them is
drawn as two triangles and the answer within a cell depends on which triangle
the point is in. A sampler that interpolated the four corners instead would name
a height on a surface nothing draws: it rides above the drawn ground on one
diagonal and below it on the other, by a quarter of the cell's twist. Over eight
metre cells on real relief that is metres -- a camera under the ground looking
out through it, and vegetation buried to the tips.

The cases here pin the three to each other by reading what each one actually
produces: the triangles out of ``mesh()``, and a ray fired into a physics world.
"""
import numpy as np
import pytest

from omi_physics.raycast import raycast
from omi_physics.world import PhysicsWorld
from OpenGLContext.physics.heightfield import HeightFieldColliders
from OpenGLContext.scenegraph.terrain.heightfield import HeightField

EXTENT = 256.0


def _saddle(x, z):
    """Ground with a strong twist in every cell -- where the two surfaces differ.

    A saddle is the shape a bilinear patch and a pair of triangles disagree
    about most: flat ground, a ramp and a cylinder are all planar in one
    direction and both surfaces pass through them identically.
    """
    x = np.asarray(x, 'd')
    z = np.asarray(z, 'd')
    return 40.0 * np.sin(x * np.pi / 64.0) * np.sin(z * np.pi / 64.0)


def _field(res=9):
    return HeightField.from_function(_saddle, res=res, extent=EXTENT)


def _drawn_height(field, x, z):
    """The height of the surface ``mesh()`` draws, read off its own triangles.

    Brute force over the returned arrays on purpose: this is the reference the
    sampler is being held to, so it reads what the renderer is handed rather
    than recomputing what the sampler ought to say.
    """
    vertices, indices = field.mesh()
    points = np.asarray(vertices, 'd')[:, :3]
    triangles = np.asarray(indices).reshape(-1, 3)
    for face in triangles:
        a, b, c = points[face]
        # Barycentric coordinates in plan (XZ); inside means all three >= 0.
        area = ((b[0] - a[0]) * (c[2] - a[2]) - (c[0] - a[0]) * (b[2] - a[2]))
        if abs(area) < 1e-12:
            continue
        u = ((x - a[0]) * (c[2] - a[2]) - (c[0] - a[0]) * (z - a[2])) / area
        v = ((b[0] - a[0]) * (z - a[2]) - (x - a[0]) * (b[2] - a[2])) / area
        if u >= -1e-9 and v >= -1e-9 and u + v <= 1.0 + 1e-9:
            return float(a[1] + u * (b[1] - a[1]) + v * (c[1] - a[1]))
    raise AssertionError('no drawn triangle covers (%r, %r)' % (x, z))


def _spots(count=400, seed=0, margin=0.0):
    """Points scattered over the field's square."""
    rng = np.random.default_rng(seed)
    half = EXTENT / 2.0 - margin
    return rng.uniform(-half, half, size=(count, 2))


class TestTheSamplerIsTheDrawnSurface:
    def test_a_sampled_height_is_on_a_drawn_triangle(self) -> None:
        field = _field()
        for x, z in _spots():
            assert float(field.sample(x, z)) == pytest.approx(
                _drawn_height(field, x, z), abs=1e-6)

    def test_the_cell_centre_is_the_diagonal_not_the_corner_average(self) -> None:
        """Where the two surfaces differ most, and by a value that can be written down.

        ``mesh()`` splits each cell along the diagonal joining ``b`` (one step
        along x) and ``c`` (one step along z), so the centre of a cell sits on
        that edge and is the mean of those two corners alone. Averaging all four
        -- what a bilinear patch gives -- is off by a quarter of the twist.
        """
        field = _field()
        step = EXTENT / (field.res - 1)
        low = -EXTENT / 2.0
        a, b, c, d = [field.grid[row, column] * field.relief + field.base
                      for row, column in ((3, 3), (3, 4), (4, 3), (4, 4))]
        twist = a + d - b - c
        assert abs(twist) > 1.0, 'the fixture must have a twist to disagree about'
        centre = low + 3.5 * step
        assert float(field.sample(centre, centre)) == pytest.approx(
            (b + c) / 2.0, abs=1e-6)

    def test_the_corners_of_a_cell_are_the_grid(self) -> None:
        """Whatever happens inside a cell, its corners are the samples themselves."""
        field = _field()
        step = EXTENT / (field.res - 1)
        west = -EXTENT / 2.0
        for row in range(field.res):
            for column in range(field.res):
                expected = field.grid[row, column] * field.relief + field.base
                assert float(field.sample(west + column * step,
                                          west + row * step)) == pytest.approx(
                    expected, abs=1e-6)

    def test_an_array_of_points_answers_as_the_scalars_do(self) -> None:
        """Vegetation is seated a discful at a time, not one plant at a time."""
        field = _field()
        spots = _spots(count=200, seed=3)
        together = np.asarray(field.sample(spots[:, 0], spots[:, 1]), 'd')
        apart = np.array([float(field.sample(x, z)) for x, z in spots])
        assert np.allclose(together, apart, atol=1e-9)

    def test_ground_off_the_edge_holds_at_the_edge(self) -> None:
        """A field is the ground it covers; beyond it the border height stands."""
        field = _field()
        half = EXTENT / 2.0
        for x, z in ((-half - 50.0, 0.0), (half + 50.0, 0.0),
                     (0.0, -half - 50.0), (0.0, half + 50.0)):
            edge = (float(np.clip(x, -half, half)), float(np.clip(z, -half, half)))
            assert float(field.sample(x, z)) == pytest.approx(
                float(field.sample(*edge)), abs=1e-6)

    def test_a_single_sample_field_is_that_sample(self) -> None:
        """A one-cell grid has no cell to interpolate across, and is still ground."""
        field = HeightField(np.array([[0.5]]), EXTENT, 100.0, base=-10.0)
        assert float(field.sample(12.0, -30.0)) == pytest.approx(40.0)


class TestTheColliderIsTheDrawnSurface:
    def test_a_ray_lands_where_the_sampler_says_the_ground_is(self) -> None:
        """What the walker stands on and what a wheel rolls over are one surface."""
        field = _field(res=17)
        world = PhysicsWorld()
        ground = HeightFieldColliders(world, field, reach=EXTENT)
        ground.update((0.0, 0.0, 0.0))
        for x, z in _spots(count=60, seed=7, margin=1.0):
            hit = raycast(world, (x, 400.0, z), (0.0, -1.0, 0.0), max_distance=900.0)
            assert hit is not None, 'no ground under (%.2f, %.2f)' % (x, z)
            assert float(hit.point[1]) == pytest.approx(
                float(field.sample(x, z)), abs=1e-3)


class TestWhatStandsOnIt:
    def test_a_walker_at_eye_height_is_above_the_drawn_ground(self) -> None:
        """The camera clears the surface everywhere, so it never looks out through it."""
        field = _field(res=17)
        eye_height = 1.7
        spots = _spots(count=2000, seed=11)
        eyes = np.asarray(field.sample(spots[:, 0], spots[:, 1]), 'd') + eye_height
        drawn = np.array([_drawn_height(field, x, z) for x, z in spots])
        assert float((eyes - drawn).min()) == pytest.approx(eye_height, abs=1e-6)

    def test_a_plant_seated_by_the_sampler_meets_the_ground(self) -> None:
        """A scatter lifted to ``sample`` sits on the surface, not in or over it."""
        from OpenGLContext.loaders.tiles3d.vegetation import scatter_disc

        field = _field(res=17)
        placements = scatter_disc((0.0, 0.0, 0.0), 100.0, 0.02, seed=5,
                                  height_fn=field.sample, water_level=-1e9)
        assert len(placements) > 100
        drawn = np.array([_drawn_height(field, p[0], p[2])
                          for p in placements.positions])
        assert np.abs(placements.positions[:, 1] - drawn).max() < 1e-4


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
