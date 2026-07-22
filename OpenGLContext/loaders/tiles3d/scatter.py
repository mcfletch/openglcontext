"""Deterministic vegetation scatter over a tile's surface mesh.

Places instances (trees, brush, grass) on a mesh with density proportional to
surface area, sampling uniformly within each triangle. Placement is seeded (by the
tile) so the same tile always scatters identically — reproducible for regression
capture and stable as the tile pages in and out.

The result feeds instanced rendering (per-instance transform), the vegetation
backbone in [passes/instancing.py]; grass uses the same placements at higher density.
"""
import numpy as np


class Scatter:
    """Instance placements: `positions` (N,3), `yaws` (N,), `scales` (N,)."""

    def __init__(self, positions, yaws, scales):
        self.positions = positions
        self.yaws = yaws
        self.scales = scales

    def __len__(self):
        return len(self.positions)


def scatter_on_mesh(points, tris, density, seed, scale_range=(1.0, 1.0),
                    keep=None):
    """Scatter instances over the triangle mesh (`points`, `tris`).

    `density` is instances per unit surface area. Returns a `Scatter`. Uniform
    sampling within a triangle uses the standard sqrt barycentric transform; triangles
    are chosen with probability proportional to their area. `keep`, if given, is a
    callable taking the (M,3) candidate positions and returning a boolean mask of which
    to keep — used to restrict vegetation to e.g. grass elevations (not water or peaks).
    """
    points = np.asarray(points, dtype="d")
    tris = np.asarray(tris)
    if len(tris) == 0 or len(points) == 0:
        return Scatter(np.zeros((0, 3), "f4"), np.zeros(0), np.zeros(0))

    a = points[tris[:, 0]]
    b = points[tris[:, 1]]
    c = points[tris[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    total_area = float(areas.sum())
    count = int(round(total_area * density))
    if count <= 0:
        return Scatter(np.zeros((0, 3), "f4"), np.zeros(0), np.zeros(0))

    rng = np.random.default_rng(seed)
    probs = areas / total_area
    choice = rng.choice(len(tris), size=count, p=probs)
    u = rng.random(count)
    v = rng.random(count)
    su = np.sqrt(u)
    bary0 = (1.0 - su)[:, None]
    bary1 = (su * (1.0 - v))[:, None]
    bary2 = (su * v)[:, None]
    positions = (bary0 * a[choice] + bary1 * b[choice] + bary2 * c[choice])

    yaws = rng.random(count) * (2.0 * np.pi)
    scales = rng.uniform(scale_range[0], scale_range[1], size=count)
    if keep is not None:
        mask = np.asarray(keep(positions), dtype=bool)
        positions, yaws, scales = positions[mask], yaws[mask], scales[mask]
    return Scatter(positions.astype("f4"), yaws, scales)
