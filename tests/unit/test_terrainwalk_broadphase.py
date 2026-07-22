"""Spatial-hash broadphase for terrain-walk trunk collision (no GL context).

The grid in :class:`TerrainWalkMixin` narrows :meth:`_push_out` to the colliders in
the player's cell and its eight neighbours. These tests pin that narrowing to be
result-identical to a brute-force scan over every collider, across randomised
collider fields and query points, and check the empty/None fast paths.
"""
import math
import numpy as np
import pytest

from OpenGLContext import quaternion
from OpenGLContext.scenegraph.terrain import HeightField
from OpenGLContext.move.terrainwalk import TerrainWalkMixin


class _FakePlatform:
    def __init__(self, p):
        self._p = np.array(p, 'd')
        self.quaternion = quaternion.fromXYZR(0, 1, 0, 0.0)
    @property
    def position(self): return self._p
    def setPosition(self, p): self._p = np.array(p, 'd')


class _Walker(TerrainWalkMixin):
    def __init__(self, platform=None): self.platform = platform


def _brute_push_out(w, x, z):
    """Reference resolve: the deepest-penetration math over *all* colliders, no grid.

    Mirrors the pre-broadphase :meth:`_push_out` so the grid version can be held to
    an exact match."""
    cpos = w._tw_cpos
    if cpos is None or not len(cpos):
        return x, z
    dx = x - cpos[:, 0]; dz = z - cpos[:, 2]
    bp = w.collide_broadphase
    near = (np.abs(dx) < bp) & (np.abs(dz) < bp)
    if not np.any(near):
        return x, z
    i = np.where(near)[0]
    if w._tw_crad is not None:
        r = w._tw_crad[i] + w.player_radius
    else:
        r = np.full(len(i), w.player_radius, np.float32)
    d2 = dx[i] * dx[i] + dz[i] * dz[i]
    k = int(np.argmax(r * r - d2))
    if r[k] * r[k] > d2[k]:
        j = i[k]; d = math.sqrt(d2[k])
        if d < 1e-4:
            x += r[k]
        else:
            push = (r[k] - d) / d
            x += dx[j] * push; z += dz[j] * push
    return x, z


def _field(n, seed, spread=40.0, rmin=0.2, rmax=0.8):
    rng = np.random.default_rng(seed)
    pos = np.zeros((n, 3), np.float32)
    pos[:, 0] = rng.uniform(-spread, spread, n)
    pos[:, 2] = rng.uniform(-spread, spread, n)
    rad = rng.uniform(rmin, rmax, n).astype(np.float32)
    return pos, rad


def test_grid_query_matches_full_scan_over_random_points():
    """For many random query points the grid resolve equals the brute-force resolve."""
    for seed in range(20):
        pos, rad = _field(300, seed)
        w = _Walker(); w.init_walk(None, pos, rad)
        rng = np.random.default_rng(1000 + seed)
        for _ in range(200):
            x = float(rng.uniform(-45, 45)); z = float(rng.uniform(-45, 45))
            got = w._push_out(x, z)
            want = _brute_push_out(w, x, z)
            assert got == pytest.approx(want, abs=1e-6), (seed, x, z)


def test_walker_inside_trunk_pushed_to_reference_position():
    """A walker dropped inside a random trunk lands exactly where the brute-force
    resolver would put it, over many collider fields."""
    hf = HeightField(np.zeros((16, 16)), 200.0, 10.0)
    for seed in range(30):
        pos, rad = _field(150, seed)
        j = int(np.random.default_rng(seed).integers(len(pos)))
        tx, tz = float(pos[j, 0]), float(pos[j, 2])
        # start just off the trunk centre, well inside its radius
        x = tx + 0.05 * (rad[j] + TerrainWalkMixin.player_radius)
        z = tz
        w = _Walker(_FakePlatform((x, 0.0, z))); w.init_walk(hf, pos, rad)
        w.collide_and_clamp()
        gx, gz = float(w.platform.position[0]), float(w.platform.position[2])

        ref = _Walker(_FakePlatform((x, 0.0, z))); ref.init_walk(hf, pos, rad)
        rx, rz = _brute_push_out(ref, x, z)
        rh = hf.height_at(rx, rz) + ref.eye_height
        assert (gx, gz) == pytest.approx((rx, rz), abs=1e-5)
        assert w.platform.position[1] == pytest.approx(rh, abs=1e-4)


def test_dead_centre_ejects_along_x_like_reference():
    hf = HeightField(np.zeros((16, 16)), 200.0, 10.0)
    trunk = np.array([[3.0, 0.0, -2.0]], np.float32); rad = np.array([0.5], np.float32)
    w = _Walker(); w.init_walk(hf, trunk, rad)
    got = w._push_out(3.0, -2.0)
    assert got == pytest.approx((3.0 + rad[0] + w.player_radius, -2.0), abs=1e-6)


def test_deepest_of_many_selected_like_reference():
    pos = np.array([[0, 0, 0], [1.2, 0, 0], [-1.2, 0, 0]], np.float32)
    rad = np.array([0.5, 0.9, 0.9], np.float32)
    w = _Walker(); w.init_walk(None, pos, rad)
    for x in np.linspace(-2.0, 2.0, 41):
        assert w._push_out(float(x), 0.0) == pytest.approx(_brute_push_out(w, float(x), 0.0), abs=1e-6)


def test_no_colliders_variants_are_noops():
    for cpos, crad in ((None, None), (np.zeros((0, 3), np.float32), np.zeros(0, np.float32))):
        w = _Walker(); w.init_walk(None, cpos, crad)
        assert w._tw_grid is None
        assert w._push_out(1.0, 2.0) == (1.0, 2.0)


def test_player_far_outside_all_cells_is_noop():
    pos, rad = _field(50, 7)
    w = _Walker(); w.init_walk(None, pos, rad)
    assert w._push_out(1.0e6, 1.0e6) == (1.0e6, 1.0e6)


def test_uniform_radius_field_matches_reference():
    """collider_radius=None (uniform player-radius collider) resolves like the scan."""
    rng = np.random.default_rng(3)
    pos = np.zeros((120, 3), np.float32)
    pos[:, 0] = rng.uniform(-20, 20, 120); pos[:, 2] = rng.uniform(-20, 20, 120)
    w = _Walker(); w.init_walk(None, pos, None)
    assert w._tw_crad is None
    for _ in range(300):
        x = float(rng.uniform(-22, 22)); z = float(rng.uniform(-22, 22))
        assert w._push_out(x, z) == pytest.approx(_brute_push_out(w, x, z), abs=1e-6)


def test_cell_size_covers_broadphase_and_reach():
    pos, rad = _field(40, 1, rmin=1.0, rmax=5.0)
    w = _Walker(); w.init_walk(None, pos, rad)
    assert w._tw_cell >= w.collide_broadphase - 1e-9
    assert w._tw_cell >= float(rad.max()) + w.player_radius - 1e-9


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
