"""The shipped landscape, with its shapes as numbers a caller can change.

The terrain is hills, ridged mountains under a mask, a meandering canyon and a
lake basin. Each of those has a size, and a landscape whose mountains are twice
as tall or whose canyon is not there is the same generator with different
numbers -- which is what a library of dramatic starting landscapes is made of.

Pure arithmetic over a grid, so none of it needs a window.
"""
import numpy as np
import pytest

from OpenGLContext.loaders.tiles3d.procedural import (
    SHIPPED_TERRAIN,
    TerrainProfile,
    _fbm,
    _ridged,
    _smooth,
    terrain_height,
    terrain_height_for,
)


def _as_shipped(x, z):
    """The landscape as the module generated it before it had a profile.

    Written out rather than called, because it is the thing the profile has to
    keep reproducing: every world already baked came from these numbers, and a
    regression here moves ground somebody has driven on.
    """
    x = np.asarray(x, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    hills = 45.0 * (_fbm(x * 0.0016, z * 0.0016, seed=1, octaves=5) - 0.5)
    mask = _smooth(np.clip(
        (_fbm(x * 0.0006 + 5, z * 0.0006 - 3, seed=7, octaves=3) - 0.40) / 0.28,
        0.0, 1.0))
    mountains = 360.0 * _ridged(x * 0.0011, z * 0.0011, seed=3, octaves=6) * mask
    h = 20.0 + hills + mountains
    path = 240.0 * np.sin(z * 0.0016) + 120.0 * np.sin(z * 0.0007 + 1.3)
    h = h - 120.0 * np.exp(-((x - path) / 70.0) ** 2)
    basin = _smooth(np.clip(
        (_fbm(x * 0.0009 - 8, z * 0.0009 + 4, seed=9, octaves=4) - 0.5) / 0.25,
        0.0, 1.0))
    return h - 60.0 * basin


def _grid(half=1500.0, steps=41):
    axis = np.linspace(-half, half, steps)
    return np.meshgrid(axis, axis, indexing='ij')


class TestTheShippedLandscape:
    def test_it_is_the_profile_the_module_ships(self) -> None:
        """Every world already baked was made by this; it must not move."""
        x, z = _grid()
        assert np.allclose(terrain_height_for(SHIPPED_TERRAIN)(x, z),
                           _as_shipped(x, z), atol=1e-9)

    def test_the_module_level_function_is_that_profile(self) -> None:
        x, z = _grid()
        assert np.array_equal(terrain_height(x, z), _as_shipped(x, z))

    def test_the_profile_is_readable_as_numbers(self) -> None:
        assert SHIPPED_TERRAIN.mountains > 0.0
        assert SHIPPED_TERRAIN.canyon > 0.0


class TestChangingTheShapes:
    def _range(self, profile):
        x, z = _grid()
        ground = terrain_height_for(profile)(x, z)
        return float(ground.max() - ground.min())

    def test_taller_mountains_make_a_taller_landscape(self) -> None:
        low = TerrainProfile(mountains=100.0)
        high = TerrainProfile(mountains=800.0)
        assert self._range(high) > self._range(low)

    def test_a_landscape_with_no_features_is_flat(self) -> None:
        flat = TerrainProfile(hills=0.0, mountains=0.0, canyon=0.0, basin=0.0)
        x, z = _grid()
        assert np.allclose(terrain_height_for(flat)(x, z), flat.datum)

    def test_the_datum_lifts_the_whole_landscape(self) -> None:
        x, z = _grid()
        low = terrain_height_for(TerrainProfile(datum=0.0))(x, z)
        high = terrain_height_for(TerrainProfile(datum=50.0))(x, z)
        assert np.allclose(high - low, 50.0)

    def test_a_canyon_cuts_below_what_is_around_it(self) -> None:
        x, z = _grid()
        plain = TerrainProfile(hills=0.0, mountains=0.0, basin=0.0, canyon=0.0)
        cut = TerrainProfile(hills=0.0, mountains=0.0, basin=0.0, canyon=200.0)
        difference = terrain_height_for(cut)(x, z) - terrain_height_for(plain)(x, z)
        assert difference.min() < -100.0
        assert difference.max() <= 1e-9

    def test_a_wider_canyon_cuts_more_of_the_map(self) -> None:
        x, z = _grid()
        narrow = TerrainProfile(hills=0.0, mountains=0.0, basin=0.0,
                                canyon=200.0, canyon_width=40.0)
        wide = TerrainProfile(hills=0.0, mountains=0.0, basin=0.0,
                              canyon=200.0, canyon_width=200.0)
        deep = -20.0
        assert ((terrain_height_for(wide)(x, z) < deep).sum()
                > (terrain_height_for(narrow)(x, z) < deep).sum())

    def test_a_basin_lowers_one_broad_region(self) -> None:
        x, z = _grid()
        plain = TerrainProfile(hills=0.0, mountains=0.0, canyon=0.0, basin=0.0)
        dished = TerrainProfile(hills=0.0, mountains=0.0, canyon=0.0, basin=120.0)
        difference = terrain_height_for(dished)(x, z) - terrain_height_for(plain)(x, z)
        assert difference.min() < -50.0
        assert (difference < -1.0).mean() > 0.05

    def test_a_different_seed_is_a_different_landscape(self) -> None:
        x, z = _grid()
        one = terrain_height_for(TerrainProfile(seed=1))(x, z)
        other = terrain_height_for(TerrainProfile(seed=99))(x, z)
        assert not np.allclose(one, other)

    def test_the_same_seed_is_the_same_landscape_every_time(self) -> None:
        x, z = _grid()
        profile = TerrainProfile(seed=7)
        assert np.array_equal(terrain_height_for(profile)(x, z),
                              terrain_height_for(profile)(x, z))


class TestHowItAnswers:
    def test_the_answer_is_the_shape_of_the_question(self) -> None:
        x, z = _grid(steps=7)
        assert terrain_height_for(TerrainProfile())(x, z).shape == x.shape

    def test_a_profile_can_be_written_down_and_read_back(self) -> None:
        profile = TerrainProfile(mountains=500.0, canyon=0.0, seed=4)
        assert TerrainProfile.from_json(profile.to_json()) == profile
