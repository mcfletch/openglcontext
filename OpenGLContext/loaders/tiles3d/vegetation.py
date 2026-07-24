"""Turn scatter placements into instanced vegetation.

Wraps one shared prototype (a `Shape`/geometry) in a per-instance `Transform`
(position from the tile surface, random yaw, random uniform scale). Because every
instance reuses the same geometry object, the existing instancing engine
([passes/instancing.py]) collapses the whole group into a single draw call, so a tile
can carry thousands of plants cheaply. Octahedral impostor far-LODs are a later add.
"""
import math
from collections.abc import Callable, Sequence
from typing import Any, Optional

import numpy as np

from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.transform import Transform

from OpenGLContext.loaders.tiles3d.scatter import scatter_on_mesh, Scatter


def poisson_thin(
    positions: np.ndarray,
    radii: np.ndarray,
    priority: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Blue-noise thinning: drop overcrowded points so no two kept points overlap.

    A uniform (Poisson) scatter clumps — many points land far closer than the mean
    spacing — which for sized objects (trees) reads as intersecting, soupy overlap.
    This greedily keeps points in ``priority`` order (default: largest ``radii``
    first) and drops any later point that lies within ``radii[i] + radii[j]`` of an
    already-kept point, so each kept point owns a keep-out disc of its own radius.
    Give a bigger radius to bigger instances and mature neighbours hold more space.

    :param positions: (N, 2) or (N, 3) world positions (XZ used if 3-wide).
    :param radii: (N,) per-point keep-out radius; points i, j conflict when their
        centres are closer than ``radii[i] + radii[j]``.
    :param priority: (N,) keep-preference, higher wins in a crowd; defaults to radii.
    :returns: boolean keep-mask over ``positions``.
    """
    pos = np.asarray(positions, float)
    rad = np.asarray(radii, float)
    n = len(pos)
    if n == 0:
        return np.zeros(0, bool)
    xz = pos[:, [0, 2]] if pos.shape[1] >= 3 else pos[:, :2]
    priority = rad if priority is None else np.asarray(priority, float)
    order = np.argsort(-priority)          # process highest priority first
    keep = np.ones(n, bool)
    maxr = float(rad.max())
    if maxr <= 0:
        return keep

    try:
        from scipy.spatial import cKDTree
    except ImportError:
        cKDTree = None

    if cKDTree is not None:
        # find every candidate pair within the largest possible conflict distance,
        # filter to true conflicts, then greedily drop the lower-priority side.
        pairs = cKDTree(xz).query_pairs(2.0 * maxr, output_type='ndarray')
        if len(pairs):
            a, b = pairs[:, 0], pairs[:, 1]
            d = np.hypot(xz[a, 0] - xz[b, 0], xz[a, 1] - xz[b, 1])
            hit = d < (rad[a] + rad[b])
            a, b = a[hit], b[hit]
            adj: list[list[int]] = [[] for _ in range(n)]
            for i, j in zip(a.tolist(), b.tolist(), strict=True):
                adj[i].append(j)
                adj[j].append(i)
            for i in order:
                if not keep[i]:
                    continue
                for j in adj[i]:
                    keep[j] = False if keep[j] and j != i else keep[j]
        return keep

    # scipy-free fallback: a spatial hash on a cell = max conflict diameter, so all
    # conflicts for a point fall in its own + 8 neighbouring cells.
    cell = 2.0 * maxr
    grid: dict[tuple[int, int], list[int]] = {}
    for i in order:
        i = int(i)
        x, z = xz[i]
        ri = rad[i]
        cx = int(math.floor(x / cell))
        cz = int(math.floor(z / cell))
        ok = True
        for gx in (cx - 1, cx, cx + 1):
            for gz in (cz - 1, cz, cz + 1):
                for j in grid.get((gx, gz), ()):
                    dx = x - xz[j, 0]
                    dz = z - xz[j, 1]
                    if dx * dx + dz * dz < (ri + rad[j]) ** 2:
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                break
        if ok:
            grid.setdefault((cx, cz), []).append(i)
        else:
            keep[i] = False
    return keep


def scatter_disc(
    center: Sequence[float],
    radius: float,
    density: float,
    seed: int,
    height_fn: Callable[[np.ndarray, np.ndarray], np.ndarray],
    keep: Optional[Callable[[np.ndarray], np.ndarray]] = None,
    scale_range: tuple[float, float] = (1.0, 1.0),
    water_level: float = 0.0,
) -> Scatter:
    """Scatter instances in a disc around `center`, seated on the terrain surface.

    Points are drawn uniformly in the disc and lifted to `height_fn(x, z)` (clamped to
    `water_level`), so vegetation sits on the ground. Used for camera-following
    vegetation fields; `density` is instances per m². `keep(positions)->mask` filters
    (e.g. grass elevations only)."""
    cx, cy, cz = center
    count = int(np.pi * radius * radius * density)
    if count <= 0:
        return Scatter(np.zeros((0, 3), "f4"), np.zeros(0), np.zeros(0))
    rng = np.random.default_rng(seed)
    rr = radius * np.sqrt(rng.random(count))
    th = rng.random(count) * (2.0 * np.pi)
    x = cx + rr * np.cos(th)
    z = cz + rr * np.sin(th)
    y = np.maximum(np.asarray(height_fn(x, z), "d"), water_level)
    pos = np.stack([x, y, z], axis=1).astype("f4")
    yaws = rng.random(count) * (2.0 * np.pi)
    scales = rng.uniform(scale_range[0], scale_range[1], size=count)
    if keep is not None:
        m = np.asarray(keep(pos), dtype=bool)
        pos, yaws, scales = pos[m], yaws[m], scales[m]
    return Scatter(pos, yaws, scales)


def grass_tuft(
    height: float = 0.55, color: tuple[float, float, float] = (0.26, 0.45, 0.14)
) -> Group:
    """A knee-high grass/weed tuft: crossed thin blades sharing one material."""
    from OpenGLContext.scenegraph.basenodes import (  # type: ignore[attr-defined]  # basenodes builds node classes dynamically from entry points
        Shape, Box, Appearance, Material,
    )
    mat = Appearance(material=Material(diffuseColor=list(color)))
    blades = []
    for ang in (0.0, 1.05, 2.1):
        blades.append(Transform(
            translation=[0.0, height * 0.5, 0.0], rotation=[0.0, 1.0, 0.0, ang],
            children=[Shape(geometry=Box(size=(height * 0.85, height, 0.04)),
                            appearance=mat)]))
    return Group(children=blades)


def bush(
    size: float = 1.3, color: tuple[float, float, float] = (0.13, 0.31, 0.10)
) -> Group:
    """A low shrub: a couple of overlapping foliage blobs."""
    from OpenGLContext.scenegraph.basenodes import (  # type: ignore[attr-defined]  # basenodes builds node classes dynamically from entry points
        Shape, Sphere, Appearance, Material,
    )
    mat = Appearance(material=Material(diffuseColor=list(color)))
    blobs = [(0, size * 0.5, 0, size * 0.5),
             (size * 0.32, size * 0.42, size * 0.15, size * 0.36),
             (-size * 0.28, size * 0.44, -size * 0.12, size * 0.34)]
    return Group(children=[
        Transform(translation=[bx, by, bz],
                  children=[Shape(geometry=Sphere(radius=br), appearance=mat)])
        for bx, by, bz, br in blobs])


def build_forest_patch(
    center: Sequence[float],
    height_fn: Callable[[np.ndarray, np.ndarray], np.ndarray],
    tree: Any = None,
    tree_far: Any = None,
    seed: int = 0,
    water_level: float = 0.0,
    grass_radius: float = 42.0,
    grass_density: float = 0.22,
    bush_radius: float = 75.0,
    bush_density: float = 0.014,
    tree_radius: float = 190.0,
    tree_density: float = 0.012,
    tree_lod_distance: float = 120.0,
) -> Group:
    """A dense, ground-hugging forest around `center`: grass, shrubs and trees.

    Grass fills a tight disc (you walk through it), shrubs a wider one, and trees the
    widest with a near-mesh / far-billboard LOD. All layers share one prototype each,
    so the instancing engine draws each in a handful of calls. Rebuild this around the
    camera as it moves to keep a bounded, always-dense field."""
    from OpenGLContext.scenegraph.basenodes import Shape, Box, Appearance, Material  # type: ignore[attr-defined]  # basenodes builds node classes dynamically from entry points

    def keep(p: np.ndarray) -> np.ndarray:
        return (p[:, 1] > water_level + 2.0) & (p[:, 1] < 135.0)

    tree = tree or conifer(height=10.0)
    tree_far = tree_far or Shape(
        geometry=Box(size=(5.0, 11.0, 1.0)),
        appearance=Appearance(material=Material(diffuseColor=(0.10, 0.32, 0.12))))

    grass = group_from_scatter(scatter_disc(
        center, grass_radius, grass_density, seed + 1, height_fn, keep=keep,
        scale_range=(0.6, 1.5), water_level=water_level), grass_tuft())
    shrubs = group_from_scatter(scatter_disc(
        center, bush_radius, bush_density, seed + 2, height_fn, keep=keep,
        scale_range=(0.7, 1.6), water_level=water_level), bush())
    trees_s = scatter_disc(center, tree_radius, tree_density, seed + 3, height_fn,
                           keep=keep, scale_range=(0.7, 1.7), water_level=water_level)
    near, far = partition_by_distance(trees_s, center, tree_lod_distance)
    trees = Group(children=[group_from_scatter(near, tree),
                            group_from_scatter(far, tree_far)])
    return Group(children=[grass, shrubs, trees])


def conifer(
    height: float = 9.0,
    trunk_color: tuple[float, float, float] = (0.30, 0.20, 0.11),
    foliage_color: tuple[float, float, float] = (0.11, 0.34, 0.12),
) -> Group:
    """A layered pine-tree prototype: a trunk plus three stacked foliage skirts.

    Returned as a `Group` of `Shape`s reused across instances, so the instancing
    engine collapses each sub-part across all trees. Much more tree-like than a single
    cone, still cheap enough for instancing."""
    from OpenGLContext.scenegraph.basenodes import (  # type: ignore[attr-defined]  # basenodes builds node classes dynamically from entry points
        Shape, Cylinder, Cone, Appearance, Material,
    )
    trunk_h = height * 0.32
    trunk_mat = Appearance(material=Material(diffuseColor=list(trunk_color)))
    foliage_mat = Appearance(material=Material(diffuseColor=list(foliage_color)))
    parts = [Transform(translation=[0.0, trunk_h * 0.5, 0.0],
                       children=[Shape(geometry=Cylinder(
                           radius=height * 0.04, height=trunk_h),
                           appearance=trunk_mat)])]
    for i in range(3):
        y = trunk_h + i * (height * 0.21)
        r = height * 0.24 * (1.0 - 0.22 * i)
        h = height * 0.34
        parts.append(Transform(translation=[0.0, y + h * 0.5, 0.0],
                               children=[Shape(geometry=Cone(bottomRadius=r, height=h),
                                               appearance=foliage_mat)]))
    return Group(children=parts)


def group_from_scatter(placements: Scatter, prototype: Any) -> Group:
    """A `Group` of per-instance `Transform`s over one shared `prototype`."""
    children = []
    for position, yaw, scale in zip(placements.positions, placements.yaws,
                                    placements.scales, strict=True):
        children.append(Transform(
            translation=[float(position[0]), float(position[1]), float(position[2])],
            rotation=[0.0, 1.0, 0.0, float(yaw)],
            scale=[float(scale), float(scale), float(scale)],
            children=[prototype],
        ))
    return Group(children=children)


def partition_by_distance(
    placements: Scatter, camera: Sequence[float], near_distance: float
) -> tuple[Scatter, Scatter]:
    """Split placements into (near, far) about a distance from `camera`.

    Near instances render as full meshes; far ones as cheap billboard impostors.
    """
    if len(placements) == 0:
        empty = Scatter(np.zeros((0, 3), "f4"), np.zeros(0), np.zeros(0))
        return empty, empty
    cam = np.asarray(camera, dtype="f4")
    d = np.linalg.norm(placements.positions - cam, axis=1)
    near_mask = d <= near_distance
    far_mask = ~near_mask

    def sub(mask: np.ndarray) -> Scatter:
        return Scatter(placements.positions[mask], placements.yaws[mask],
                       placements.scales[mask])
    return sub(near_mask), sub(far_mask)


def build_vegetation_group(
    points: np.ndarray,
    tris: np.ndarray,
    prototype: Any,
    density: float,
    seed: int,
    scale_range: tuple[float, float] = (1.0, 1.0),
    keep: Optional[Callable[[np.ndarray], np.ndarray]] = None,
) -> Group:
    """A `Group` of per-instance `Transform`s placing `prototype` over the mesh.

    `prototype` is a single node reused by every instance (so instancing collapses
    them). Placement is the deterministic surface scatter for `seed`. `keep` (a
    positions->mask callable) restricts placements, e.g. to grass elevations.
    """
    placements = scatter_on_mesh(points, tris, density, seed,
                                 scale_range=scale_range, keep=keep)
    return group_from_scatter(placements, prototype)


def build_grass_patch(
    points: np.ndarray,
    tris: np.ndarray,
    blade: Any,
    camera: Sequence[float],
    radius: float,
    density: float,
    seed: int,
    elevation: Optional[tuple[float, float]] = None,
    scale_range: tuple[float, float] = (0.7, 1.4),
) -> Group:
    """Dense instanced grass blades within `radius` of the camera.

    Grass is only worth drawing near the viewer, so placements are limited to a disc
    around `camera` (and optionally an `elevation` height band), keeping the blade
    count bounded as the camera moves. One shared `blade` -> a single instanced draw.
    """
    cam = np.asarray(camera, dtype="f4")

    def keep(pos: np.ndarray) -> np.ndarray:
        d = np.linalg.norm(pos[:, [0, 2]] - cam[[0, 2]], axis=1)
        mask = d <= radius
        if elevation is not None:
            lo, hi = elevation
            mask &= (pos[:, 1] >= lo) & (pos[:, 1] <= hi)
        return mask

    placements = scatter_on_mesh(points, tris, density, seed,
                                 scale_range=scale_range, keep=keep)
    return group_from_scatter(placements, blade)


def build_vegetation_lod(
    points: np.ndarray,
    tris: np.ndarray,
    near_prototype: Any,
    far_prototype: Any,
    density: float,
    seed: int,
    camera: Sequence[float],
    near_distance: float,
    scale_range: tuple[float, float] = (1.0, 1.0),
    keep: Optional[Callable[[np.ndarray], np.ndarray]] = None,
) -> Group:
    """A `Group` with near instances as `near_prototype` and far as `far_prototype`.

    `far_prototype` is typically a camera-facing billboard (a cheap impostor) so
    distant vegetation costs a fraction of the full mesh.
    """
    placements = scatter_on_mesh(points, tris, density, seed,
                                 scale_range=scale_range, keep=keep)
    near, far = partition_by_distance(placements, camera, near_distance)
    return Group(children=[group_from_scatter(near, near_prototype),
                           group_from_scatter(far, far_prototype)])
