"""Rock cut into a surface: a mesh refined where it is cut and scraped flat in discs. No GL.

A tunnel, a cliff or a quarry face begins as a smooth surface and is made to look hewn from rock
the way :func:`~OpenGLContext.scenegraph.natural.stone` makes a boulder: flat discs are pressed
into it, each cutting down to a plane (a little tilted) within its reach and leaving what lies
outside, so the surface steps in facets with a clean edge at every rim. A pit is a small, deep
disc. :func:`scrape` does this to any triangle mesh whose front faces look into the open and
whose rock lies behind them, and refines the mesh about every rim first, so a step is an edge of
the mesh and not a slope across a coarse triangle.

:func:`split_edges` is the refinement: it cuts the chosen edges of a mesh at their middles and
re-divides the triangles that touch them, so the result has no cracks whatever edges were
chosen. :func:`scrape` repeats the cut-and-scrape over the passes it is given, from large facets
to small pits, as each pass refines the mesh the one before it left.

Vertices a caller needs to keep where they are -- where the mesh meets other meshes -- are
``pinned``: they do not move, and the surface is cut in gradually over ``ramp`` metres from them.
"""
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

__all__ = ['Pass', 'scrape', 'split_edges', 'interpolated', 'face_normals']

#: Rounds of splitting about the rims of a pass's discs, at most.
MAX_SPLITS = 2
#: Edges longer than this share of a disc's radius are split about its rim.
EDGE_SHARE = 0.4
#: How far, in metres, a disc's cut reaches either side of its plane along its axis.
WINDOW = 0.6


@dataclass(frozen=True)
class Pass:
    """One round of scraping: discs of a size, each cutting a depth, as many as fill the surface.

    ``radius`` and ``depth`` are the ranges, in metres, a disc's reach and its cut are drawn
    from; ``per_area`` is how many discs there are for each square metre of surface; ``tilt`` is
    the steepest slope, as a ratio, of a cut face.
    """

    radius: tuple[float, float]
    depth: tuple[float, float]
    per_area: float
    tilt: float = 0.25


def face_normals(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """The unit normal of each triangle, from the order its corners are wound in."""
    corners = points[triangles]
    faces = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    length = np.linalg.norm(faces, axis=1, keepdims=True)
    return np.asarray(faces / np.maximum(length, 1e-12))


def interpolated(values: np.ndarray, parents: np.ndarray) -> np.ndarray:
    """``values`` with a row added for each new vertex :func:`split_edges` made, the mean of the
    rows of the two vertices its edge ran between."""
    if not len(parents):
        return values
    return np.concatenate([values, (values[parents[:, 0]] + values[parents[:, 1]]) / 2.0])


def split_edges(points: np.ndarray, triangles: np.ndarray,
                wanted: Callable[[np.ndarray, np.ndarray], np.ndarray], *,
                fixed: np.ndarray | None = None, protected: np.ndarray | None = None
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``points`` and ``triangles`` with the edges ``wanted`` says to split cut at their middles.

    ``wanted(a, b)`` is given the ends of every edge, ``(E, 3)`` each, and answers which to split.
    A triangle with one split edge becomes two, with two becomes three and with three becomes
    four, so a split edge is split in both the triangles that share it and the mesh stays whole.
    Windings are kept. Returns the points (the new ones at the end), the triangles, and the two
    vertices each new point is the middle of, ``(N, 2)``, for :func:`interpolated`.

    An edge between two ``fixed`` vertices (a boolean per vertex) is not split, nor is one of the
    ``protected`` pairs, ``(P, 2)`` vertex indices: they are where the mesh meets other meshes, and
    a vertex made there would be a crack.
    """
    tri = np.asarray(triangles, dtype=np.int64)
    count = len(tri)
    edges = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
    # One integer for each edge, so the edges are told apart by a sort of numbers and not of rows.
    count_points = len(points)
    coded, inverse = np.unique(edges[:, 0] * count_points + edges[:, 1], return_inverse=True)
    keys = np.stack([coded // count_points, coded % count_points], axis=1)
    chosen = np.asarray(wanted(points[keys[:, 0]], points[keys[:, 1]]), dtype=bool)
    if fixed is not None:
        chosen &= ~(np.asarray(fixed, dtype=bool)[keys[:, 0]] & np.asarray(fixed, dtype=bool)[keys[:, 1]])
    if protected is not None and len(protected) and chosen.any():
        pairs = np.sort(np.asarray(protected, dtype=np.int64), axis=1)
        width = int(max(keys.max(), pairs.max())) + 1
        chosen &= ~np.isin(keys[:, 0] * width + keys[:, 1], pairs[:, 0] * width + pairs[:, 1])
    if not chosen.any():
        return points, tri, np.zeros((0, 2), dtype=np.int64)
    middle = np.full(len(keys), -1, dtype=np.int64)
    parents = keys[chosen]
    middle[chosen] = len(points) + np.arange(len(parents))
    points = np.concatenate([points, (points[parents[:, 0]] + points[parents[:, 1]]) / 2.0])
    cut = middle[inverse.reshape(3, count).T]
    pattern = (cut[:, 0] >= 0) * 1 + (cut[:, 1] >= 0) * 2 + (cut[:, 2] >= 0) * 4
    out = [tri[pattern == 0]]
    for code, turn in ((1, 0), (2, 1), (4, 2)):
        here = pattern == code
        v = np.roll(tri[here], -turn, axis=1)
        m = cut[here][:, turn]
        out.append(np.stack([v[:, 0], m, v[:, 2]], axis=1))
        out.append(np.stack([m, v[:, 1], v[:, 2]], axis=1))
    for code, turn in ((3, 0), (6, 1), (5, 2)):
        here = pattern == code
        v = np.roll(tri[here], -turn, axis=1)
        m0, m1 = np.roll(cut[here], -turn, axis=1)[:, :2].T
        out.append(np.stack([m0, v[:, 1], m1], axis=1))
        long_one = (np.linalg.norm(points[v[:, 0]] - points[m1], axis=1)
                    <= np.linalg.norm(points[m0] - points[v[:, 2]], axis=1))
        out.append(np.where(long_one[:, None], np.stack([v[:, 0], m0, m1], axis=1),
                            np.stack([v[:, 0], m0, v[:, 2]], axis=1)))
        out.append(np.where(long_one[:, None], np.stack([v[:, 0], m1, v[:, 2]], axis=1),
                            np.stack([m0, m1, v[:, 2]], axis=1)))
    here = pattern == 7
    a, b, c = tri[here].T
    ab, bc, ca = cut[here].T
    out += [np.stack(t, axis=1) for t in ((a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca))]
    return points, np.concatenate(out), parents


def _cells_of_segments(a: np.ndarray, b: np.ndarray, reach: float, size: float,
                       origin: np.ndarray, shape: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Every grid cell that reaches within ``reach`` of segment ``a``-``b``'s box, as a cell code,
    and the segment each belongs to."""
    low = np.floor((np.minimum(a, b) - reach - origin) / size).astype(np.int64)
    span = np.floor((np.maximum(a, b) + reach - origin) / size).astype(np.int64) - low + 1
    per = span[:, 0] * span[:, 1] * span[:, 2]
    owner = np.repeat(np.arange(len(a)), per)
    local = np.arange(int(per.sum())) - np.repeat(np.cumsum(per) - per, per)
    here = span[owner]
    cell = low[owner] + np.stack([local // (here[:, 1] * here[:, 2]),
                                  local // here[:, 2] % here[:, 1],
                                  local % here[:, 2]], axis=1)
    return (cell[:, 0] * shape[1] + cell[:, 1]) * shape[2] + cell[:, 2], owner


def _distance_from(pinned: np.ndarray, points: np.ndarray, triangles: np.ndarray,
                   reach: float) -> np.ndarray:
    """How far each vertex is from the pinned ones and the edges between them, up to ``reach``."""
    far = np.full(len(points), reach)
    far[pinned] = 0.0
    edges = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    ends = np.unique(edges[pinned[edges[:, 0]] & pinned[edges[:, 1]]], axis=0)
    alone = np.flatnonzero(pinned)
    first = np.concatenate([ends[:, 0], alone])
    second = np.concatenate([ends[:, 1], alone])
    if not len(first):
        return far
    a, b = points[first], points[second]
    # The segments are filed by the cells of a grid their reach covers, so a vertex compares
    # itself only with the segments filed under its own cell.
    size = 2.0 * reach
    origin = np.minimum(points.min(axis=0), np.minimum(a, b).min(axis=0)) - reach - size
    top = np.maximum(points.max(axis=0), np.maximum(a, b).max(axis=0)) + reach + size
    shape = np.floor((top - origin) / size).astype(np.int64) + 2
    filed, which = _cells_of_segments(a, b, reach, size, origin, shape)
    order = np.argsort(filed, kind='stable')
    filed, which = filed[order], which[order]
    cells = np.floor((points - origin) / size).astype(np.int64)
    code = (cells[:, 0] * shape[1] + cells[:, 1]) * shape[2] + cells[:, 2]
    low = np.searchsorted(filed, code, side='left')
    counts = np.searchsorted(filed, code, side='right') - low
    for owner in np.array_split(np.flatnonzero(counts), max(1, int(counts.sum() // 2_000_000) + 1)):
        n = counts[owner]
        if not len(owner):
            continue
        starts = np.cumsum(n) - n
        who = np.repeat(owner, n)
        offset = np.arange(int(n.sum())) - np.repeat(starts, n)
        segment = which[low[who] + offset]
        base, span = a[segment], b[segment] - a[segment]
        length = np.maximum(np.einsum('ij,ij->i', span, span), 1e-18)
        t = np.clip(np.einsum('ij,ij->i', points[who] - base, span) / length, 0.0, 1.0)
        gap = points[who] - (base + t[:, None] * span)
        far[owner] = np.minimum(far[owner], np.sqrt(np.minimum.reduceat(
            np.einsum('ij,ij->i', gap, gap), starts)))
    return far


def _smooth(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0.0, 1.0)
    return np.asarray(t * t * (3.0 - 2.0 * t))


def _vertex_normals(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    corners = points[triangles]
    faces = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    normals = np.zeros_like(points)
    for corner in range(3):
        np.add.at(normals, triangles[:, corner], faces)
    return np.asarray(normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12))


class _Discs:
    """The discs of a pass: each has a centre on the surface, a direction into the rock, a radius,
    a depth and a slope for its face."""

    def __init__(self, points: np.ndarray, triangles: np.ndarray, rng: np.random.Generator,
                 shape: Pass, keep_clear: np.ndarray | None) -> None:
        normals = face_normals(points, triangles)
        corners = points[triangles]
        area = 0.5 * np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0],
                                             corners[:, 2] - corners[:, 0]), axis=1)
        count = int(round(float(area.sum()) * shape.per_area))
        if count == 0 or not area.sum() > 0.0:
            self.count = 0
            return
        pick = rng.choice(len(triangles), size=count, p=area / area.sum())
        mix = rng.dirichlet((1.0, 1.0, 1.0), size=count)
        centre = np.einsum('ij,ijk->ik', mix, corners[pick])
        radius = rng.uniform(*shape.radius, count)
        depth = rng.uniform(*shape.depth, count)
        tilt = rng.normal(size=(count, 3)) * shape.tilt
        axis = -normals[pick]
        tilt -= axis * np.sum(tilt * axis, axis=1, keepdims=True)
        if keep_clear is not None and len(keep_clear):
            near = np.linalg.norm(centre[:, None, :] - keep_clear[None, :, :], axis=2).min(axis=1)
            allowed = near > radius + 0.5
            centre, radius, depth, tilt, axis = (v[allowed] for v in (centre, radius, depth, tilt, axis))
        self.centre, self.radius, self.depth, self.tilt, self.axis = centre, radius, depth, tilt, axis
        self.count = len(centre)


def _long_axis(points: np.ndarray) -> int:
    """The axis a mesh is longest along, which is the one its places are looked up by."""
    return int(np.argmax(np.ptp(points, axis=0)))


def _rim_edges(discs: _Discs, along: int) -> Callable[[np.ndarray, np.ndarray], np.ndarray]:
    """Which edges lie across the rim of a disc and are long beside its radius."""
    def wanted(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        mid, span = (a + b) / 2.0, np.linalg.norm(a - b, axis=1)
        order = np.argsort(mid[:, along])
        line = mid[order, along]
        chosen = np.zeros(len(a), dtype=bool)
        for i in range(discs.count):
            reach = discs.radius[i] + float(span.max()) + WINDOW
            low = np.searchsorted(line, discs.centre[i, along] - reach)
            high = np.searchsorted(line, discs.centre[i, along] + reach)
            if high <= low:
                continue
            index = order[low:high]
            offset = mid[index] - discs.centre[i]
            height = offset @ discs.axis[i]
            across = np.linalg.norm(offset - height[:, None] * discs.axis[i], axis=1)
            rim = ((np.abs(across - discs.radius[i]) < 0.6 * span[index] + 0.05)
                   & (np.abs(height) < discs.depth[i] + WINDOW + 1.0)
                   & (span[index] > EDGE_SHARE * discs.radius[i]))
            chosen[index[rim]] = True
        return chosen

    return wanted


def _cut(points: np.ndarray, discs: _Discs, weight: np.ndarray, along: int) -> np.ndarray:
    """``points`` with every disc's cut applied in turn, eased by ``weight`` per vertex."""
    points = points.copy()
    order = np.argsort(points[:, along])
    line = points[order, along]
    # A vertex moves at most this far along any axis, over every disc that reaches it.
    drift = 3.0 * (float(discs.depth.max()) + WINDOW) + float(discs.radius.max()) * float(
        np.linalg.norm(discs.tilt, axis=1).max())
    for i in range(discs.count):
        reach = discs.radius[i] + drift
        low = np.searchsorted(line, discs.centre[i, along] - reach)
        high = np.searchsorted(line, discs.centre[i, along] + reach)
        index = order[low:high]
        if not len(index):
            continue
        offset = points[index] - discs.centre[i]
        height = offset @ discs.axis[i]
        flat = offset - height[:, None] * discs.axis[i]
        inside = ((np.linalg.norm(flat, axis=1) < discs.radius[i])
                  & (np.abs(height) < discs.depth[i] + WINDOW))
        if not inside.any():
            continue
        plane = discs.depth[i] + flat @ discs.tilt[i]
        move = np.maximum(plane - height, 0.0) * inside * weight[index]
        points[index] += move[:, None] * discs.axis[i]
    return points


def scrape(points: np.ndarray, triangles: np.ndarray, rng: np.random.Generator,
           passes: Sequence[Pass], *, pinned: np.ndarray | None = None, ramp: float = 0.8,
           keep_clear: np.ndarray | None = None
           ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``points`` and ``triangles`` with each of ``passes`` scraped into the surface.

    The triangles are wound so that their front faces look into the open; the rock is behind
    them, and every cut goes into it, so the open space only grows. ``pinned`` is a boolean per
    vertex for those that must not move; the cuts come in over ``ramp`` metres from them.
    ``keep_clear`` is ``(K, 3)`` places nothing is cut within reach of -- where something is
    fixed to the surface. ``rng`` is the numpy generator the discs are drawn from, so the same
    one cuts the same rock.

    Returns the points, the triangles and the pinned flags, each for the refined mesh.
    """
    pts = np.asarray(points, dtype=np.float64)
    tri = np.asarray(triangles, dtype=np.int64)
    pin = np.zeros(len(pts), dtype=bool) if pinned is None else np.asarray(pinned, dtype=bool)
    for shape in passes:
        discs = _Discs(pts, tri, rng, shape, keep_clear)
        if not discs.count:
            continue
        along = _long_axis(pts)
        wanted = _rim_edges(discs, along)
        for _ in range(MAX_SPLITS):
            pts, tri, parents = split_edges(pts, tri, wanted, fixed=pin)
            if not len(parents):
                break
            pin = np.concatenate([pin, pin[parents[:, 0]] & pin[parents[:, 1]]])
        weight = _smooth(_distance_from(pin, pts, tri, ramp) / ramp) if pin.any() else np.ones(len(pts))
        pts = _cut(pts, discs, weight, along)
    return pts, tri, pin


def grain(points: np.ndarray, triangles: np.ndarray, rng: np.random.Generator,
          amount: float, waves: Callable[[np.random.Generator, np.ndarray], np.ndarray],
          pinned: np.ndarray | None = None, ramp: float = 0.8) -> np.ndarray:
    """``points`` pushed into the rock by ``amount`` metres at most, by ``waves`` -- smooth noise
    from 0 to 1 at each point -- so the surface is rough and never nearer the open than it was."""
    normals = _vertex_normals(points, triangles)
    weight = np.ones(len(points))
    if pinned is not None and np.any(pinned):
        weight = _smooth(_distance_from(np.asarray(pinned, dtype=bool), points, triangles, ramp) / ramp)
    push = amount * np.clip(waves(rng, points), 0.0, 1.0) * weight
    return np.asarray(points - normals * push[:, None])
