"""Integer-hash placement tests for the world-anchored grass scatter (no GL).

Guards the property the module exists for: per-cell jitter/yaw/scale/keep are a
deterministic, world-anchored hash of the integer cell index that stays high
quality arbitrarily far from the origin, so grass never pops or bands as the disc
follows the camera.
"""
import math
import numpy as np
import pytest

from OpenGLContext.scenegraph.terrain import HeightField
from OpenGLContext.scenegraph.vegetation import world_grid_scatter
from OpenGLContext.scenegraph.vegetation.grid import (
    _cell_hash, _SEED_JITTER_X, _SEED_JITTER_Z, _SEED_KEEP, _SEED_YAW, _SEED_SCALE,
)


def flat_field():
    return HeightField(np.zeros((16, 16)), 1_000_000.0, 10.0)


# --- the integer hash itself ---------------------------------------------------

def test_hash_is_deterministic_and_world_anchored():
    I = np.array([0, 1, 2, 1_000_000, -7], np.int64)
    J = np.array([5, -3, 999_999, 42, 0], np.int64)
    a = _cell_hash(I, J, _SEED_YAW)
    b = _cell_hash(I, J, _SEED_YAW)
    np.testing.assert_array_equal(a, b)                     # same key -> same value
    # a single cell's value does not depend on which block it is queried within
    one = _cell_hash(np.array([1_000_000]), np.array([42]), _SEED_YAW)
    assert one[0] == a[3]


def test_hash_streams_are_independent():
    rng = np.random.default_rng(0)
    I = rng.integers(-10_000, 10_000, 4000).astype(np.int64)
    J = rng.integers(-10_000, 10_000, 4000).astype(np.int64)
    streams = [_cell_hash(I, J, s) for s in
               (_SEED_JITTER_X, _SEED_JITTER_Z, _SEED_KEEP, _SEED_YAW, _SEED_SCALE)]
    for a in range(len(streams)):
        for b in range(a + 1, len(streams)):
            c = np.corrcoef(streams[a], streams[b])[0, 1]
            assert abs(c) < 0.05                            # no cross-stream correlation


def test_hash_quality_far_from_origin_matches_origin():
    # A block of cells near world-index 1e6 must be as uniform as one at the origin:
    # the sin()-of-index hash collapsed to a few banded values out here.
    def block(o):
        i = np.arange(o, o + 200, dtype=np.int64)
        I, Jm = np.meshgrid(i, i)
        return _cell_hash(I.ravel(), Jm.ravel(), _SEED_JITTER_X)
    near = block(0)
    far = block(1_000_000)
    for h in (near, far):
        assert h.min() >= 0.0 and h.max() < 1.0
        assert abs(h.mean() - 0.5) < 0.02                   # uniform mean
        assert abs(h.var() - 1.0 / 12.0) < 0.01             # uniform variance ~1/12
        # no banding: values spread across the unit interval, not a few levels
        assert len(np.unique((h * 64).astype(int))) >= 60


# --- through world_grid_scatter ------------------------------------------------

def test_scatter_is_deterministic():
    hf = flat_field()
    args = (123.0, -456.0, 40.0, 1.0, hf)
    a = world_grid_scatter(*args)
    b = world_grid_scatter(*args)
    for x, y in zip(a, b):
        np.testing.assert_array_equal(x, y)


def test_scatter_world_anchored_far_from_origin():
    # two overlapping discs far out yield identical tufts in the shared region
    hf = flat_field()
    cx, cz = 500_000.0, -300_000.0
    p1, y1, s1 = world_grid_scatter(cx, cz, 40.0, 1.0, hf)
    p2, y2, s2 = world_grid_scatter(cx + 6.0, cz + 4.0, 40.0, 1.0, hf)

    def by_cell(pos, yaw, sca):
        return {(round(float(x), 3), round(float(z), 3)): (float(w), float(c))
                for x, z, w, c in zip(pos[:, 0], pos[:, 2], yaw, sca)}
    d1 = by_cell(p1, y1, s1)
    d2 = by_cell(p2, y2, s2)
    shared = set(d1) & set(d2)
    assert len(shared) > 0.8 * min(len(d1), len(d2))
    for k in shared:
        assert d1[k] == d2[k]              # position AND yaw AND scale identical


def test_scatter_outputs_within_documented_ranges():
    hf = flat_field()
    scale_mul = 0.7
    pos, yaw, sca = world_grid_scatter(1e6, 1e6, 60.0, 1.0, hf, scale_mul=scale_mul)
    assert len(pos) > 0
    assert (yaw >= 0.0).all() and (yaw < 2.0 * math.pi).all()
    assert (sca >= 0.5 * scale_mul - 1e-6).all() and (sca < 1.0 * scale_mul + 1e-6).all()
    d = np.hypot(pos[:, 0] - 1e6, pos[:, 2] - 1e6)
    assert (d <= 60.0 + 1e-3).all()


class TestHowMuchInstancesVaryInSize:
    """A scatter of identical plants reads as a printed pattern, so every
    instance is scaled by a hash of its own cell. What that spread is around
    has to be the caller's, though: a species that says it is 0.4 m tall and
    comes out averaging 0.28 m is 0.4 m of nothing."""

    def test_the_default_spread_is_the_one_it_always_had(self) -> None:
        hf = flat_field()
        scale = world_grid_scatter(0.0, 0.0, 40.0, 1.0, hf, scale_mul=2.0)[2]
        assert scale.min() >= 1.0 - 1e-6
        assert scale.max() <= 2.0 + 1e-6

    def test_a_named_spread_is_what_comes_out(self) -> None:
        hf = flat_field()
        scale = world_grid_scatter(0.0, 0.0, 40.0, 1.0, hf, scale_mul=2.0,
                                   scale_range=(0.7, 1.3))[2]
        assert scale.min() >= 1.4 - 1e-6
        assert scale.max() <= 2.6 + 1e-6

    def test_a_spread_about_one_averages_what_was_asked_for(self) -> None:
        hf = flat_field()
        scale = world_grid_scatter(0.0, 0.0, 60.0, 1.0, hf, scale_mul=0.4,
                                   scale_range=(0.7, 1.3))[2]
        assert float(scale.mean()) == pytest.approx(0.4, abs=0.02)

    def test_plants_still_vary(self) -> None:
        hf = flat_field()
        scale = world_grid_scatter(0.0, 0.0, 60.0, 1.0, hf, scale_mul=0.4,
                                   scale_range=(0.7, 1.3))[2]
        assert float(scale.std()) > 0.02


class TestOneGridPerSpecies:
    """A salt gives each kind of plant its own world-anchored grid.

    Ground cover is several species at once, each at its own density. Scattering
    them from one stream would make every species land on the same cells; a salt
    mixed into the cell hash gives each its own, so the ferns and the grass are
    placed independently and each keeps the pop-free property on its own.
    """

    def test_the_default_salt_places_what_it_always_placed(self) -> None:
        """Nothing shipped moves: an unsalted scatter is the old scatter."""
        hf = flat_field()
        plain = world_grid_scatter(10.0, -20.0, 40.0, 1.0, hf)
        salted = world_grid_scatter(10.0, -20.0, 40.0, 1.0, hf, salt=0)
        for a, b in zip(plain, salted):
            np.testing.assert_array_equal(a, b)

    def test_two_species_do_not_stand_in_the_same_places(self) -> None:
        hf = flat_field()
        one = world_grid_scatter(0.0, 0.0, 50.0, 1.0, hf, salt=1)[0]
        two = world_grid_scatter(0.0, 0.0, 50.0, 1.0, hf, salt=2)[0]
        here = {(round(float(x), 4), round(float(z), 4))
                for x, z in zip(one[:, 0], one[:, 2])}
        there = {(round(float(x), 4), round(float(z), 4))
                 for x, z in zip(two[:, 0], two[:, 2])}
        assert len(here & there) < 0.02 * len(here)

    def test_a_salted_scatter_is_still_world_anchored(self) -> None:
        """The property the module exists for holds per species, not just once."""
        hf = flat_field()
        first = world_grid_scatter(0.0, 0.0, 60.0, 1.0, hf, salt=7)[0]
        watched = {tuple(np.round(one, 3)) for one in first
                   if abs(one[0]) < 20.0 and abs(one[2]) < 20.0}
        moved = world_grid_scatter(25.0, 0.0, 60.0, 1.0, hf, salt=7)[0]
        assert watched and watched <= {tuple(np.round(one, 3)) for one in moved}

    def test_a_salted_scatter_is_as_uniform_as_an_unsalted_one(self) -> None:
        hf = flat_field()
        for salt in (0, 3, 2 ** 31 + 11):
            yaw = world_grid_scatter(1e6, 1e6, 60.0, 1.0, hf, salt=salt)[1]
            assert abs(float(yaw.mean()) - math.pi) < 0.12
            assert len(np.unique((yaw * 10).astype(int))) >= 60

    def test_a_salt_may_be_any_integer(self) -> None:
        """Species are salted by index or by a name's hash; neither is bounded."""
        hf = flat_field()
        for salt in (-5, 0, 2 ** 63 - 1):
            assert len(world_grid_scatter(0.0, 0.0, 20.0, 1.0, hf,
                                          salt=salt)[0]) > 0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
