"""Tests for the terrain/vegetation engine logic (no GL context required).

Covers the parts that decide what the player sees and how they move: height-field
sampling/slope/mesh, the baked shadow terms, the world-anchored grass scatter, and
the terrain-walk collide-and-clamp. The GL render paths are exercised by the
forest-demo capture/bench runs, not here.
"""
import os
import math
import numpy as np
import pytest

from OpenGLContext import quaternion
from OpenGLContext.scenegraph.terrain import HeightField
from OpenGLContext.scenegraph.vegetation import world_grid_scatter
from OpenGLContext.scenegraph.vegetation.clumps import _decimate_ribbons
from OpenGLContext.scenegraph.instancedgl import SHADER_DIR
from OpenGLContext.move.terrainwalk import TerrainWalkMixin
from OpenGLContext.loaders.tiles3d.vegetation import poisson_thin


def ramp_field(R=5, E=4.0, relief=10.0):
    """HeightField whose height rises linearly in +x: world u = x + E/2, so at a
    world x the height is (u/(R-1))*relief with u = (x+E/2)/E*(R-1)."""
    u = np.arange(R) / (R - 1)
    grid = np.tile(u, (R, 1))          # varies along x (columns), constant in z
    return HeightField(grid, E, relief)


# --- HeightField ---------------------------------------------------------------

def test_sample_matches_grid_points_and_interpolates():
    hf = ramp_field()
    # at x=0 the sample lands on grid column u=2 -> height 2/4*10 = 5.0
    assert hf.height_at(0.0, 0.0) == pytest.approx(5.0)
    # midway between columns interpolates linearly
    assert hf.height_at(0.5, 0.0) == pytest.approx((2.5 / 4) * 10.0)
    # edges clamp, not wrap
    assert hf.height_at(-2.0, 0.0) == pytest.approx(0.0)
    assert hf.height_at(2.0, 0.0) == pytest.approx(10.0)


def test_sample_vectorised_equals_scalar():
    hf = ramp_field()
    xs = np.array([-1.0, 0.0, 0.7, 1.9]); zs = np.array([0.0, 0.3, -0.4, 1.0])
    vec = hf.sample(xs, zs)
    scal = np.array([hf.height_at(float(x), float(z)) for x, z in zip(xs, zs)])
    np.testing.assert_allclose(vec, scal, rtol=1e-6)


def test_slope_of_linear_ramp():
    hf = ramp_field()
    # d(height)/dx = relief/E = 10/4 = 2.5 per world unit; no z variation.
    # (eps kept well inside the 4-unit-wide field so the probes don't clamp.)
    assert float(hf.slope(0.0, 0.0, eps=0.5)) == pytest.approx(2.5, rel=1e-6)


def test_mesh_counts_and_unit_normals():
    R = 5; hf = ramp_field(R=R)
    verts, idx = hf.mesh()
    assert verts.shape == (R * R, 6)
    assert idx.shape == ((R - 1) * (R - 1) * 6,)
    assert idx.max() == R * R - 1
    normals = verts[:, 3:6]
    np.testing.assert_allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-5)


def test_from_image(tmp_path):
    from PIL import Image
    arr = (np.linspace(0, 65535, 16 * 16).reshape(16, 16)).astype(np.uint16)
    p = tmp_path / "h.png"; Image.fromarray(arr, mode="I;16").save(p)
    hf = HeightField.from_image(str(p), 8, 100.0, 50.0)
    assert hf.res == 8 and hf.extent == 100.0 and hf.relief == 50.0
    assert 0.0 <= hf.height_at(0, 0) <= 50.0


def test_sun_shadow_range_and_shape():
    R = 32
    grid = np.zeros((R, R)); grid[R // 2, R // 2] = 1.0     # a lone peak
    hf = HeightField(grid, 100.0, 40.0)
    lit = hf.sun_shadow((-0.5, -0.72, -0.48), steps=40)
    assert lit.shape == (R, R)
    assert lit.min() >= 0.0 and lit.max() <= 1.0
    assert lit.min() < 1.0            # the peak casts *some* shadow


def test_canopy_shadow_darkens_under_trees():
    R = 32
    hf = HeightField(np.zeros((R, R)), 100.0, 40.0)
    lit = np.ones((R, R), np.float32)
    trees = np.zeros((200, 3), np.float32)      # a clump of trees at the origin
    shaded = hf.canopy_shadow(lit, trees, (-0.5, -0.72, -0.48))
    assert shaded.min() < 1.0                   # ground under the clump is darker
    assert shaded.max() == pytest.approx(1.0)   # far from trees stays lit


# --- world_grid_scatter --------------------------------------------------------

def test_grass_grid_is_world_anchored():
    hf = HeightField(np.zeros((16, 16)), 1000.0, 10.0)
    p1, _, _ = world_grid_scatter(0.0, 0.0, 40.0, 1.0, hf)
    p2, _, _ = world_grid_scatter(6.0, 4.0, 40.0, 1.0, hf)
    s1 = {(round(x, 3), round(z, 3)) for x, z in p1[:, [0, 2]]}
    s2 = {(round(x, 3), round(z, 3)) for x, z in p2[:, [0, 2]]}
    shared = s1 & s2
    # overlapping region tufts must be identical (no re-randomisation -> no popping)
    assert len(shared) > 0.8 * min(len(s1), len(s2))


def test_grass_grid_within_radius_and_on_ground():
    hf = ramp_field(R=17, E=200.0, relief=30.0)
    radius = 30.0
    pos, yaw, sca = world_grid_scatter(5.0, -5.0, radius, 0.5, hf)
    d = np.hypot(pos[:, 0] - 5.0, pos[:, 2] + 5.0)
    assert (d <= radius + 1e-4).all()
    np.testing.assert_allclose(pos[:, 1], hf.sample(pos[:, 0], pos[:, 2]), atol=1e-4)
    assert len(pos) == len(yaw) == len(sca)
    assert (sca > 0).all()


def test_grass_grid_density_scales_count():
    hf = HeightField(np.zeros((16, 16)), 1000.0, 10.0)
    sparse, _, _ = world_grid_scatter(0, 0, 50.0, 0.2, hf)
    dense, _, _ = world_grid_scatter(0, 0, 50.0, 0.8, hf)
    assert len(dense) > 2 * len(sparse)      # ~4x density -> more tufts


def test_grass_mask_thins_and_excludes():
    hf = HeightField(np.zeros((16, 16)), 1000.0, 10.0)
    full, _, _ = world_grid_scatter(0, 0, 40.0, 1.0, hf)
    # mask=0 everywhere removes all instances; mask=1 keeps the full set unchanged.
    none, _, _ = world_grid_scatter(0, 0, 40.0, 1.0, hf, mask=lambda x, z: np.zeros_like(x))
    allkept, _, _ = world_grid_scatter(0, 0, 40.0, 1.0, hf, mask=lambda x, z: np.ones_like(x))
    assert len(none) == 0
    assert len(allkept) == len(full)
    # a half-plane mask (grass only where x<0) keeps instances on that side only.
    half, _, _ = world_grid_scatter(0, 0, 40.0, 1.0, hf,
                                    mask=lambda x, z: (x < 0).astype(float))
    assert len(half) > 0
    assert (half[:, 0] < 0).all()


def test_grass_mask_is_world_anchored():
    """A cell's keep/drop under a mask must not change as the disc recentres."""
    hf = HeightField(np.zeros((16, 16)), 1000.0, 10.0)
    m = lambda x, z: np.full_like(x, 0.5)      # 50% keep, decided per-cell by hash
    p1, _, _ = world_grid_scatter(0.0, 0.0, 40.0, 1.0, hf, mask=m)
    p2, _, _ = world_grid_scatter(6.0, 4.0, 40.0, 1.0, hf, mask=m)
    s1 = {(round(x, 3), round(z, 3)) for x, z in p1[:, [0, 2]]}
    s2 = {(round(x, 3), round(z, 3)) for x, z in p2[:, [0, 2]]}
    shared = s1 & s2
    assert len(shared) > 0.8 * min(len(s1), len(s2))


# --- poisson_thin --------------------------------------------------------------

def _min_gap_ok(xz, rad, keep):
    """No two kept points closer than the sum of their radii."""
    k = np.where(keep)[0]
    for a in range(len(k)):
        for b in range(a + 1, len(k)):
            d = math.hypot(xz[k[a], 0] - xz[k[b], 0], xz[k[a], 1] - xz[k[b], 1])
            if d < rad[k[a]] + rad[k[b]] - 1e-9:
                return False
    return True


def test_poisson_thin_enforces_spacing():
    rng = np.random.default_rng(0)
    xz = rng.uniform(0, 50, (400, 2))
    pos = np.stack([xz[:, 0], np.zeros(400), xz[:, 1]], 1)
    rad = np.full(400, 1.5)
    keep = poisson_thin(pos, rad)
    assert 0 < keep.sum() < 400                 # some dropped, some kept
    assert _min_gap_ok(xz, rad, keep)           # survivors respect the spacing


def test_poisson_thin_keeps_highest_priority_in_a_clump():
    # three points within each other's keep-out; only the highest-priority survives
    pos = np.array([[0, 0, 0], [0.5, 0, 0], [1.0, 0, 0]], float)
    rad = np.full(3, 1.0)
    keep = poisson_thin(pos, rad, priority=np.array([1.0, 5.0, 2.0]))
    assert keep.tolist() == [False, True, False]


def test_poisson_thin_variable_radius_uses_pair_sum():
    # gap of 3.0; radii 2.0 + 2.0 = 4.0 > 3.0 -> conflict, one dropped
    pos = np.array([[0, 0, 0], [3.0, 0, 0]], float)
    keep = poisson_thin(pos, np.array([2.0, 2.0]))
    assert keep.sum() == 1
    # same gap but radii 1.0 + 1.0 = 2.0 < 3.0 -> both kept
    keep2 = poisson_thin(pos, np.array([1.0, 1.0]))
    assert keep2.sum() == 2


def test_poisson_thin_empty():
    assert poisson_thin(np.zeros((0, 3)), np.zeros(0)).shape == (0,)


# --- clump ribbon decimation ---------------------------------------------------

def _ribbon(n_rings, x0=0.0, height=1.0):
    """A single blade ribbon: ``n_rings`` cross-rings of 3 verts (left/centre/right),
    rising in +y with UV.v running 0 (root) -> 1 (tip), 4 triangles per gap."""
    P = []; UV = []
    for r in range(n_rings):
        v = r / (n_rings - 1)
        for u, ux in ((0.0, -0.05), (0.5, 0.0), (1.0, 0.05)):
            P.append((x0 + ux, v * height, 0.0)); UV.append((u, v))
    idx = []
    for r in range(n_rings - 1):
        a = r * 3; b = (r + 1) * 3
        for k in range(2):
            idx += [a + k, a + k + 1, b + k, a + k + 1, b + k + 1, b + k]
    P = np.array(P, np.float32); UV = np.array(UV, np.float32)
    N = np.tile(np.array([0, 0, 1], np.float32), (len(P), 1))
    return P, N, UV, np.array(idx, np.uint32)


def _components(P, idx):
    tris = idx.reshape(-1, 3); parent = list(range(len(P)))
    def find(a):
        while parent[a] != a: parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for t in tris:
        for x in t[1:]: parent[find(int(x))] = find(int(t[0]))
    return len({find(v) for v in range(len(P))})


def test_decimate_reduces_tris_and_keeps_a_valid_ribbon():
    P, N, UV, idx = _ribbon(9, height=2.0)
    n0 = len(idx) // 3
    P2, N2, UV2, idx2 = _decimate_ribbons(P, N, UV, idx, length_samples=4)
    tris = idx2.reshape(-1, 3)
    assert len(idx2) // 3 < n0                                   # fewer triangles
    degenerate = (tris[:, 0] == tris[:, 1]) | (tris[:, 1] == tris[:, 2]) | (tris[:, 0] == tris[:, 2])
    assert not degenerate.any()                                 # no collapsed triangles left
    assert idx2.max() < len(P2)                                  # indices reference kept verts
    # root and tip survive, so the blade keeps its full length and UV span
    assert P2[:, 1].min() == pytest.approx(0.0)
    assert P2[:, 1].max() == pytest.approx(2.0)
    assert UV2[:, 1].min() == pytest.approx(0.0) and UV2[:, 1].max() == pytest.approx(1.0)


def test_decimate_preserves_separate_blades():
    # two disjoint ribbons must stay two disjoint blades after decimation
    P0, N0, UV0, i0 = _ribbon(9, x0=0.0)
    P1, N1, UV1, i1 = _ribbon(9, x0=10.0)
    P = np.concatenate([P0, P1]); N = np.concatenate([N0, N1])
    UV = np.concatenate([UV0, UV1]); idx = np.concatenate([i0, i1 + len(P0)])
    assert _components(P, idx) == 2
    P2, N2, UV2, idx2 = _decimate_ribbons(P, N, UV, idx, length_samples=3)
    assert _components(P2, idx2) == 2


def test_decimate_noop_when_rings_below_target():
    P, N, UV, idx = _ribbon(3)
    _P, _N, _UV, idx2 = _decimate_ribbons(P, N, UV, idx, length_samples=5)
    assert len(idx2) // 3 == len(idx) // 3        # already <= target: nothing dropped


# --- TerrainWalkMixin ----------------------------------------------------------

class _FakePlatform:
    def __init__(self, p, yaw=0.0):
        self._p = np.array(p, 'd')
        self.quaternion = quaternion.fromXYZR(0, 1, 0, yaw)
    @property
    def position(self): return self._p
    def setPosition(self, p): self._p = np.array(p, 'd')
    def setYaw(self, yaw): self.quaternion = quaternion.fromXYZR(0, 1, 0, yaw)


class _Walker(TerrainWalkMixin):
    def __init__(self, platform): self.platform = platform; self.redraws = 0
    def triggerRedraw(self, force=0): self.redraws += 1


def test_idle_redraws_only_when_the_view_changes():
    w = _Walker(_FakePlatform((0.0, 0.0, 0.0))); w.init_walk(ramp_field())
    w.OnIdle(); assert w.redraws == 1                 # first frame draws
    w.OnIdle(); assert w.redraws == 1                 # parked: no new draw
    w.platform.setPosition((5.0, 0.0, 0.0)); w.OnIdle()
    assert w.redraws == 2                             # moved -> draw
    w.platform.setYaw(0.5); w.OnIdle()
    assert w.redraws == 3                             # turned in place -> draw
    w.OnIdle(); assert w.redraws == 3                 # parked again: no new draw


def test_stream_fires_on_move_or_turn():
    w = _Walker(_FakePlatform((0.0, 0.0, 0.0))); w.init_walk(ramp_field())
    moves = []; both = []
    w.add_stream(2.0, lambda x, z: moves.append((x, z)))
    w.add_stream(2.0, lambda x, z: both.append((x, z)), turn=math.radians(10))
    w.OnIdle(); assert len(moves) == 1 and len(both) == 1        # both fire first frame
    w.platform.setYaw(math.radians(25)); w.OnIdle()
    assert len(moves) == 1 and len(both) == 2                    # turn: only the turn-aware one
    w.platform.setPosition((0.5, 0.0, 0.5)); w.OnIdle()
    assert len(moves) == 1 and len(both) == 2                    # sub-threshold move: neither
    w.platform.setPosition((5.0, 0.0, 0.0)); w.OnIdle()
    assert len(moves) == 2 and len(both) == 3                    # big move: both


def test_clamp_snaps_to_ground():
    hf = ramp_field(R=17, E=200.0, relief=30.0)
    w = _Walker(_FakePlatform((10.0, -999.0, -3.0)))
    w.init_walk(hf)
    w.collide_and_clamp()
    expect = hf.height_at(10.0, -3.0) + w.eye_height
    assert w.platform.position[1] == pytest.approx(expect, abs=1e-4)


def test_collision_pushes_out_to_trunk_radius():
    hf = HeightField(np.zeros((16, 16)), 200.0, 10.0)
    trunk = np.array([[10.0, 0.0, 20.0]], np.float32)
    rad = np.array([0.3], np.float32)
    w = _Walker(_FakePlatform((10.1, 0.0, 20.0)))       # deep inside the trunk
    w.init_walk(hf, trunk, rad)
    w.collide_and_clamp()
    d = math.hypot(w.platform.position[0] - 10.0, w.platform.position[2] - 20.0)
    assert d == pytest.approx(rad[0] + w.player_radius, abs=1e-3)


def test_no_push_when_clear_of_trunks():
    hf = HeightField(np.zeros((16, 16)), 200.0, 10.0)
    trunk = np.array([[10.0, 0.0, 20.0]], np.float32)
    rad = np.array([0.3], np.float32)
    w = _Walker(_FakePlatform((15.0, 0.0, 20.0)))
    w.init_walk(hf, trunk, rad)
    w.collide_and_clamp()
    assert w.platform.position[0] == pytest.approx(15.0)
    assert w.platform.position[2] == pytest.approx(20.0)


def _walk(hf, trunk, rad, prev, cur):
    w = _Walker(_FakePlatform(prev)); w.init_walk(hf, trunk, rad)
    w.collide_and_clamp()                      # establish previous position
    w.platform.setPosition(cur); w.collide_and_clamp()
    return float(w.platform.position[0]), float(w.platform.position[2])


def test_swept_collision_blocks_fast_step_through_trunk():
    hf = HeightField(np.zeros((16, 16)), 200.0, 10.0)
    trunk = np.array([[0.0, 0.0, 0.0]], np.float32); rad = np.array([0.4], np.float32)
    R = rad[0] + TerrainWalkMixin.player_radius
    # a 3m step straight across the ~1.3m trunk in one frame must not tunnel through
    x, z = _walk(hf, trunk, rad, (-1.5, 0, 0.03), (1.5, 0, 0.03))
    assert x < 1.5 - 1e-3
    assert math.hypot(x, z) >= R - 1e-3


def test_swept_collision_dead_centre_ejects():
    hf = HeightField(np.zeros((16, 16)), 200.0, 10.0)
    trunk = np.array([[0.0, 0.0, 0.0]], np.float32); rad = np.array([0.4], np.float32)
    # a step passing exactly through the axis (degenerate push direction) still ejects
    x, z = _walk(hf, trunk, rad, (-1.5, 0, 0.0), (1.5, 0, 0.0))
    assert x < 1.5 - 1e-3


def test_collision_resolves_deepest_of_many():
    hf = HeightField(np.zeros((16, 16)), 200.0, 10.0)
    # trunk 0 far in -x (deep penetration), trunk 1 far in +x (barely clear); the
    # resolver must pick the deepest (trunk 0) and push out to its radius.
    trunks = np.array([[0.0, 0.0, 0.0], [8.0, 0.0, 0.0]], np.float32)
    rad = np.array([0.5, 0.5], np.float32)
    r0 = rad[0] + TerrainWalkMixin.player_radius
    w = _Walker(_FakePlatform((0.2, 0.0, 0.0)))    # deep inside trunk 0
    w.init_walk(hf, trunks, rad)
    w.collide_and_clamp()
    # trunk 0 sits at x=0 and the camera is on its +x side, so it is pushed further +x
    assert w.platform.position[0] > 0.2
    d0 = math.hypot(w.platform.position[0] - 0.0, w.platform.position[2] - 0.0)
    assert d0 == pytest.approx(r0, abs=1e-3)


# --- packaging -----------------------------------------------------------------

def test_engine_shaders_present():
    for name in ("terrain_splat.vert", "terrain_splat.frag",
                 "veg_billboard.vert", "veg_billboard.frag",
                 "veg_mesh.vert", "veg_mesh.frag"):
        assert os.path.exists(os.path.join(SHADER_DIR, name)), name


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
