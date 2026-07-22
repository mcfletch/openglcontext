"""Debug rendering of collision geometry and motion.

Physics bugs are visual, so this builds a wireframe overlay from the world state
each frame: collision proxies, broad-phase AABBs, contact points + normals, and —
as requested — per-body **velocity**, **acceleration**, and **angular-velocity**
vectors (the last drawn at the body's corners so opposite corners point opposite
ways, making spin visible).  Sleep state is colour-coded.

The overlay is an ``IndexedLineSet`` (per-vertex colour), so it renders through
the same path in both the legacy and shader profiles.  Enable features with the
``PhysicsDebug`` bit flags.
"""
from typing import Any, List, Optional, Tuple, TYPE_CHECKING
import numpy as np

from OpenGLContext.scenegraph import basenodes as _basenodes
from omi_physics import mathutil
from omi_physics.body import (make_proxy, SphereProxy, BoxProxy, CapsuleProxy, ConvexProxy,
                   TriangleMeshProxy, Proxy)
from omi_physics import hull

if TYPE_CHECKING:
    from omi_physics.world import PhysicsWorld

# basenodes registers its node classes at runtime, so it carries no static
# attributes; access it through an ``Any`` alias.
basenodes: Any = _basenodes

_Edge = Tuple[np.ndarray, np.ndarray]

# Feature flags (debugPhysics bitmask)
PROXIES = 1
AABBS = 2
CONTACTS = 4
VELOCITY = 8
ACCELERATION = 16
ANGULAR = 32
SLEEP = 64
JOINTS = 128
ALL = PROXIES | AABBS | CONTACTS | VELOCITY | ACCELERATION | ANGULAR | SLEEP | JOINTS

# colours
C_PROXY = (0.2, 1.0, 0.4)
C_ASLEEP = (0.4, 0.4, 0.7)
C_AABB = (0.3, 0.3, 0.3)
C_CONTACT = (1.0, 0.2, 0.2)
C_VELOCITY = (0.2, 0.8, 1.0)
C_ACCEL = (1.0, 0.6, 0.1)
C_ANGULAR = (1.0, 0.2, 1.0)
C_JOINT = (1.0, 1.0, 0.3)


class PhysicsDebugDraw:
    """Builds/updates an ``IndexedLineSet`` overlay from a :class:`PhysicsWorld`."""

    def __init__(self, world: "PhysicsWorld", flags: int = PROXIES | CONTACTS,
                 vector_scale: float = 0.25) -> None:
        self.world = world
        self.flags = flags
        self.vector_scale = vector_scale
        # Dynamic overlay (contacts, vectors, AABBs) -- a single rebuilt ILS.
        self.coord = basenodes.Coordinate(point=[])
        self.color = basenodes.Color(color=[])
        self.lines = basenodes.IndexedLineSet(
            coord=self.coord, color=self.color, colorPerVertex=1)
        self.shape = basenodes.Shape(geometry=self.lines)
        # Collision proxies -- per-body Transform > Shape(shared unit wireframe),
        # so every box proxy (and every sphere proxy) batches into one instanced
        # line draw and only the transforms update each frame.
        self._proxy_group = basenodes.Group(children=[])
        self._wire_cache: dict = {}          # shape type -> shared wireframe node
        self._proxy_nodes: dict = {}         # body index -> (Transform, shape id)
        self.root = basenodes.Group(children=[self.shape, self._proxy_group])

    def _seg(self, pts: list, cols: list, a: Any, b: Any,
             color: Tuple[float, float, float]) -> Tuple[int, int, int]:
        """Append a coloured line segment ``a``-``b`` and return its index triple."""
        i = len(pts)
        pts.append(a)
        pts.append(b)
        cols.append(color)
        cols.append(color)
        return (i, i + 1, -1)

    #: flat-ILS overlays that walk every body (proxies use the instanced path)
    _FLAT_PER_BODY = AABBS | VELOCITY | ACCELERATION | ANGULAR

    def update(self) -> None:
        """Refresh both overlays from the current world state.

        Collision proxies move through the instanced-line path (transforms only,
        no geometry rebuild); the remaining overlays (AABBs, vectors, contacts,
        joints) rebuild the single dynamic ILS. With nothing enabled both are
        cheap no-ops, so a simulation that just wants its solid meshes pays nothing.
        """
        w = self.world
        if self.flags & PROXIES:
            self._update_proxy_instances()
        elif self._proxy_nodes:
            self._proxy_group.children = []
            self._proxy_nodes = {}

        if not (self.flags & (self._FLAT_PER_BODY | CONTACTS | JOINTS)):
            if len(self.coord.point) != 1:              # collapse to an empty overlay once
                self.coord.point = [(0, 0, 0)]
                self.color.color = [(0, 0, 0)]
                self.lines.coordIndex = []
            return
        pts: list = []
        cols: list = []
        idx: list = []
        g = w.resolve_gravity() if (self.flags & ACCELERATION) else None
        if self.flags & self._FLAT_PER_BODY:
            for i in range(w.body_count):
                self._body_lines(i, pts, cols, idx, g)
        if self.flags & CONTACTS:
            for c in w.contacts:
                n = c.normal * self.vector_scale
                idx.append(self._seg(pts, cols, list(c.point),
                                     list(c.point + n), C_CONTACT))
        if self.flags & JOINTS:
            for jc in w.joint_constraints:
                self._joint_lines(jc, pts, cols, idx)
        self.coord.point = pts if pts else [(0, 0, 0)]
        self.color.color = cols if cols else [(0, 0, 0)]
        self.lines.coordIndex = [v for seg in idx for v in seg]

    def _update_proxy_instances(self) -> None:
        """Create/refresh a per-body Transform for each box/sphere collision proxy.

        Every box proxy shares one unit box-wireframe node and every sphere proxy
        one unit sphere-wireframe, so the instancing pass batches each into a
        single line draw; per frame only the (cheap) Transform poses are written.
        """
        from omi_physics import mathutil
        from .manager import write_pose
        w = self.world
        n = w.body_count
        if n == 0:
            return
        pos = w.position[:n]
        aa = mathutil.quat_to_axis_angle(w.orientation[:n])   # batched, once
        awake = w.awake[:n]
        dynamic = w.motion_type[:n] == 2
        children = self._proxy_group.children
        added = False
        for i in range(n):
            si = w.collider_shape[i] if w.collider_shape[i] >= 0 else w.trigger_shape[i]
            if si < 0:
                continue
            entry = self._proxy_nodes.get(i)
            if entry is None or entry[1] != id(w.shapes[si]):
                wire = self._wire_for(w.shapes[si])
                if wire is None:
                    continue                            # capsule/convex/... : skip
                tr = basenodes.Transform(scale=self._wire_scale(w.shapes[si]),
                                         children=[basenodes.Shape(geometry=wire)])
                self._proxy_nodes[i] = (tr, id(w.shapes[si]))
                children = children + [tr]
                added = True
                write_pose(tr, pos[i], aa[i])
                continue
            if dynamic[i] and not awake[i]:
                continue                                # sleeping: pose unchanged
            write_pose(entry[0], pos[i], aa[i])
        if added:
            self._proxy_group.children = children

    def _wire_for(self, shape: Any):
        """Shared unit wireframe geometry for a shape type, or None if unsupported."""
        wire = self._wire_cache.get(shape.type)
        if wire is None:
            if shape.type == 'box':
                wire = _unit_box_wire()
            elif shape.type == 'sphere':
                wire = _unit_sphere_wire()
            else:
                return None
            self._wire_cache[shape.type] = wire
        return wire

    @staticmethod
    def _wire_scale(shape: Any):
        """Transform scale that fits the unit wireframe to ``shape``."""
        if shape.type == 'box':
            return tuple(float(s) for s in shape.size)
        r = float(shape.radius)
        return (r, r, r)

    def _body_lines(self, i: int, pts: list, cols: list, idx: list,
                    g: Optional[np.ndarray]) -> None:
        """Add AABB, velocity, acceleration, and spin lines for body ``i``."""
        w = self.world
        shape_idx = w.collider_shape[i] if w.collider_shape[i] >= 0 else w.trigger_shape[i]
        pos = w.position[i]
        if shape_idx >= 0 and (self.flags & ANGULAR):
            proxy = make_proxy(w.shapes[shape_idx], pos, w.orientation[i])
            self._spin_vectors(proxy, w.angular_velocity[i], pts, cols, idx)
        if shape_idx >= 0 and (self.flags & AABBS):
            lo, hi = w.aabb_min[i], w.aabb_max[i]
            for a, b in box_edges_aabb(lo, hi):
                idx.append(self._seg(pts, cols, list(a), list(b), C_AABB))
        if self.flags & VELOCITY:
            idx.append(self._seg(pts, cols, list(pos),
                                 list(pos + w.linear_velocity[i] * self.vector_scale),
                                 C_VELOCITY))
        if self.flags & ACCELERATION and g is not None and w.motion_type[i] == 2:
            a = g[i] * w.gravity_factor[i]
            idx.append(self._seg(pts, cols, list(pos),
                                 list(pos + a * self.vector_scale * self.vector_scale),
                                 C_ACCEL))

    def _joint_lines(self, jc: Any, pts: list, cols: list, idx: list) -> None:
        """Draw a line between the two anchors of joint constraint ``jc``."""
        w = self.world
        a = getattr(jc, 'a', None)
        b = getattr(jc, 'b', None)
        if a is None or b is None:
            return
        pa = np.asarray(getattr(jc, 'anchor', getattr(jc, 'anchor_a', (0, 0, 0)))) \
            if a < 0 else w.position[a]
        pb = w.position[b] if b >= 0 else np.asarray(
            getattr(jc, 'anchor_b', (0, 0, 0)))
        idx.append(self._seg(pts, cols, list(np.asarray(pa, dtype='d')),
                             list(np.asarray(pb, dtype='d')), C_JOINT))

    def _spin_vectors(self, proxy: Proxy, omega: np.ndarray, pts: list,
                      cols: list, idx: list) -> None:
        """Draw the surface velocity from spin ``omega`` at each proxy corner."""
        if np.dot(omega, omega) < 1e-9:
            return
        for corner in proxy_corners(proxy):
            r = corner - proxy.center_hint()
            v = np.cross(omega, r) * self.vector_scale
            idx.append(self._seg(pts, cols, list(corner), list(corner + v), C_ANGULAR))


# ── wireframe generators ────────────────────────────────────────────────
def _wire_node(edges: List[_Edge]) -> Any:
    """A green ``IndexedLineSet`` from local-space edges (for instanced proxies)."""
    pts: list = []
    idx: list = []
    for a, b in edges:
        j = len(pts)
        pts.append(tuple(float(v) for v in a))
        pts.append(tuple(float(v) for v in b))
        idx += [j, j + 1, -1]
    return basenodes.IndexedLineSet(
        coord=basenodes.Coordinate(point=pts),
        color=basenodes.Color(color=[C_PROXY] * len(pts)),
        colorPerVertex=1, coordIndex=idx)


def _unit_box_wire() -> Any:
    """The 12 edges of a unit box (``±0.5``); a Transform scales it to the collider."""
    c = [(sx * 0.5, sy * 0.5, sz * 0.5)
         for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    e = [(0, 1), (0, 2), (0, 4), (3, 1), (3, 2), (3, 7),
         (5, 1), (5, 4), (5, 7), (6, 2), (6, 4), (6, 7)]
    return _wire_node([(np.array(c[a]), np.array(c[b])) for a, b in e])


def _unit_sphere_wire() -> Any:
    """Three unit-radius rings; a Transform scales it to the collider radius."""
    return _wire_node(_sphere_edges(np.zeros(3), 1.0))


def box_edges_aabb(lo: np.ndarray, hi: np.ndarray) -> List[_Edge]:
    """The 12 edges of the axis-aligned box spanning ``[lo, hi]``."""
    c = [(lo[0], lo[1], lo[2]), (hi[0], lo[1], lo[2]), (hi[0], hi[1], lo[2]),
         (lo[0], hi[1], lo[2]), (lo[0], lo[1], hi[2]), (hi[0], lo[1], hi[2]),
         (hi[0], hi[1], hi[2]), (lo[0], hi[1], hi[2])]
    e = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
         (0, 4), (1, 5), (2, 6), (3, 7)]
    return [(np.array(c[a]), np.array(c[b])) for a, b in e]


def _box_corners(proxy: BoxProxy) -> List[np.ndarray]:
    """The 8 world-space corners of an oriented box proxy."""
    signs = [(sx, sy, sz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    return [proxy.center + proxy.R @ (np.array(s) * proxy.half) for s in signs]


def proxy_corners(proxy: Proxy) -> List[np.ndarray]:
    """Representative world-space corner points for ``proxy`` (its AABB corners for round shapes)."""
    if isinstance(proxy, BoxProxy):
        return _box_corners(proxy)
    if isinstance(proxy, ConvexProxy):
        return list(proxy.world)
    lo, hi = proxy.aabb()
    return [np.array(c) for c, _ in [(x, 0) for x in
            [(lo[0], lo[1], lo[2]), (hi[0], lo[1], lo[2]),
             (hi[0], hi[1], lo[2]), (lo[0], hi[1], lo[2]),
             (lo[0], lo[1], hi[2]), (hi[0], lo[1], hi[2]),
             (hi[0], hi[1], hi[2]), (lo[0], hi[1], hi[2])]]]


def proxy_edges(proxy: Proxy) -> List[_Edge]:
    """Wireframe edges tessellating ``proxy`` for the debug overlay."""
    if isinstance(proxy, BoxProxy):
        c = _box_corners(proxy)
        e = [(0, 1), (0, 2), (0, 4), (3, 1), (3, 2), (3, 7), (5, 1), (5, 4),
             (5, 7), (6, 2), (6, 4), (6, 7)]
        return [(c[a], c[b]) for a, b in e]
    if isinstance(proxy, SphereProxy):
        return _sphere_edges(proxy.center, proxy.radius)
    if isinstance(proxy, CapsuleProxy):
        return _capsule_edges(proxy)
    if isinstance(proxy, ConvexProxy):
        return _hull_edges(proxy.world)
    if isinstance(proxy, TriangleMeshProxy):
        return _mesh_edges(proxy)
    return []


def _ring(center: np.ndarray, radius: float, axis_u: np.ndarray,
          axis_v: np.ndarray, n: int = 16) -> List[_Edge]:
    """Edges of a circle of ``n`` segments in the ``axis_u``/``axis_v`` plane."""
    out: List[_Edge] = []
    prev: Optional[np.ndarray] = None
    for k in range(n + 1):
        t = 2 * np.pi * k / n
        p = center + radius * (np.cos(t) * axis_u + np.sin(t) * axis_v)
        if prev is not None:
            out.append((prev, p))
        prev = p
    return out


def _sphere_edges(center: np.ndarray, radius: float) -> List[_Edge]:
    """Three orthogonal rings approximating a sphere's silhouette."""
    x, y, z = np.eye(3)
    return (_ring(center, radius, x, y) + _ring(center, radius, y, z)
            + _ring(center, radius, x, z))


def _capsule_edges(proxy: CapsuleProxy) -> List[_Edge]:
    """End-cap rings, connecting side lines, and a mid ring for a capsule."""
    r = proxy.radius
    axis = proxy.R @ np.array([0, 1.0, 0])
    u = proxy.R @ np.array([1.0, 0, 0])
    v = proxy.R @ np.array([0, 0, 1.0])
    edges = _ring(proxy.p0, r, u, v) + _ring(proxy.p1, r, u, v)
    for d in (u, -u, v, -v):
        edges.append((proxy.p0 + d * r, proxy.p1 + d * r))
    edges += _ring(0.5 * (proxy.p0 + proxy.p1), r, u, axis)
    return edges


def _hull_edges(points: np.ndarray) -> List[_Edge]:
    """Unique edges of the convex hull of ``points``."""
    verts, faces = hull.convex_hull(points)
    seen: set = set()
    edges: List[_Edge] = []
    for f in faces:
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            key = (min(a, b), max(a, b))
            if key not in seen:
                seen.add(key)
                edges.append((verts[a], verts[b]))
    return edges


def _mesh_edges(proxy: TriangleMeshProxy, limit: int = 2000) -> List[_Edge]:
    """Triangle edges of a mesh proxy, capped at ``limit`` triangles."""
    edges: List[_Edge] = []
    for tri in proxy.indices[:limit]:
        a, b, c = (proxy.world_pts[tri[0]], proxy.world_pts[tri[1]],
                   proxy.world_pts[tri[2]])
        edges += [(a, b), (b, c), (c, a)]
    return edges
