"""Build a physics collision world from a loaded glTF/scenegraph.

Walks a scenegraph, pulls the world-space triangles out of every mesh, and adds
them as a static ``trimesh`` collider so a character can walk on and bump into the
model.  If the document carries OMI physics bodies those are honoured directly
(via :mod:`omi_physics.omi_gltf`); otherwise the whole model becomes one
static collision mesh.  Used by the ``oglc-gltf`` viewer's walk-around mode.
"""
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from omi_physics import model
from omi_physics.world import PhysicsWorld


def _local_matrix(node: Any) -> np.ndarray:
    """The node's local 4x4 transform (identity if it has no pose or one cannot be built)."""
    from OpenGLContext.loaders.gltf.transforms import _local_matrix_rv
    if hasattr(node, 'translation') or hasattr(node, 'rotation') or \
            getattr(node, '_forward', None) is not None:
        try:
            return np.asarray(_local_matrix_rv(node), dtype='d')
        except Exception:
            return np.eye(4)
    return np.eye(4)


def _mesh_positions_indices(geom: Any) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Return ``(positions, triangle_indices)`` for a scenegraph geometry, or None if it has none.

    ``geom`` is a scenegraph geometry node; positions come from its ``positions``
    or ``coord.point`` and faces from ``indices`` or a fan-triangulated
    ``coordIndex``. Triangle indices are an ``(M, 3)`` array.
    """
    pos = getattr(geom, 'positions', None)
    if pos is None:
        pos = getattr(geom, 'coord', None)
        pos = getattr(pos, 'point', None)
    if pos is None or not len(pos):
        return None
    pos = np.asarray(pos, dtype='d')
    idx = getattr(geom, 'indices', None)
    if idx is None:
        # try IndexedFaceSet coordIndex (with -1 face separators)
        ci = getattr(geom, 'coordIndex', None)
        if ci is not None and len(ci):
            idx = _fan_triangulate(np.asarray(ci))
        else:
            idx = np.arange(len(pos), dtype='i')
    idx = np.asarray(idx).ravel()
    tri = idx[:len(idx) - (len(idx) % 3)].reshape(-1, 3)
    return pos, tri


def _fan_triangulate(coord_index: np.ndarray) -> np.ndarray:
    """Fan-triangulate a VRML ``coordIndex`` (``-1``-separated faces) to a flat triangle index array."""
    tris = []
    face: List[int] = []
    for v in coord_index:
        if v < 0:
            for k in range(1, len(face) - 1):
                tris.append((face[0], face[k], face[k + 1]))
            face = []
        else:
            face.append(int(v))
    if len(face) >= 3:
        for k in range(1, len(face) - 1):
            tris.append((face[0], face[k], face[k + 1]))
    return np.array(tris, dtype='i').ravel() if tris else np.zeros(0, dtype='i')


# unit-cube box triangles (indices into 8 AABB corners ordered by (ix,iy,iz) bits:
# corner index = ix*4 + iy*2 + iz). Two triangles per face, outward-ish winding.
_BOX_TRIS = np.array([
    (0, 1, 3), (0, 3, 2),   # -X
    (4, 6, 7), (4, 7, 5),   # +X
    (0, 4, 5), (0, 5, 1),   # -Y
    (2, 3, 7), (2, 7, 6),   # +Y
    (0, 2, 6), (0, 6, 4),   # -Z
    (1, 5, 7), (1, 7, 3),   # +Z
], dtype='i')


def _aabb_box(lo: np.ndarray, hi: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """The 8 corner points (and 12 triangles) of the AABB [lo, hi]."""
    corners = np.array([[hi[0] if ix else lo[0],
                         hi[1] if iy else lo[1],
                         hi[2] if iz else lo[2]]
                        for ix in (0, 1) for iy in (0, 1) for iz in (0, 1)],
                       dtype='d')
    return corners, _BOX_TRIS


def _placed_worlds(node: Any, world: np.ndarray) -> List[np.ndarray]:
    """The world matrices a node's mesh is drawn at: one, or one per placement.

    An empty placement set draws nothing, so it collides with nothing.
    """
    placements = getattr(node, 'instancePlacements', None)
    if placements is None:
        return [world]
    found = placements()
    if found is None:
        return []
    return [placement @ world for placement in found]


def _append_mesh(world_points: np.ndarray, tri: Any, points: List[np.ndarray],
                 tris: List[np.ndarray], state: Dict[str, int],
                 min_hull_size: float) -> None:
    """Add one placed mesh's world verts/tris, re-basing its indices."""
    wp = world_points[:, :3]
    # A small static sub-component contributes its AABB box (12 tris) rather
    # than its full triangle mesh: cheaper to extract and to test against, and
    # imperceptible to a walking character. Off by default (min_hull_size == 0
    # keeps exact geometry).
    if min_hull_size > 0 and len(wp):
        lo, hi = wp.min(axis=0), wp.max(axis=0)
        if float(np.linalg.norm(hi - lo)) <= min_hull_size:
            wp, tri = _aabb_box(lo, hi)
    # Running vertex offset (state['n']); summing len() over every prior array
    # per mesh made extraction O(meshes^2) -- seconds on big CAD assemblies with
    # thousands of sub-meshes.
    base = state['n']
    points.append(wp)
    state['n'] += len(wp)
    if len(tri):
        tris.append(np.asarray(tri) + base)


def _collect(node: Any, world_matrix: np.ndarray, points: List[np.ndarray],
             tris: List[np.ndarray], ancestry: Tuple[int, ...],
             state: Dict[str, int], min_hull_size: float) -> None:
    """Walk ``node`` and append each mesh's world-space verts/tris to ``points``/``tris``.

    ``node`` is a scenegraph node. Mutates ``points``, ``tris`` and ``state``
    (the running vertex offset ``state['n']``). ``ancestry`` is the id path from
    the root, so instanced geometry reached by several transforms is collected once
    per instance without infinite recursion.
    """
    # Cycle-detect on the current path, NOT a global seen-set: instanced geometry
    # shares one mesh node reachable via many parent transforms, and each instance
    # must be collected with its own transform (a global seen-set would keep only
    # the first, so e.g. the parthenon's instanced columns would have no collider).
    if id(node) in ancestry:
        return
    ancestry = ancestry + (id(node),)
    world = _local_matrix(node) @ world_matrix
    geom = getattr(node, 'geometry', None)
    if geom is not None:
        mi = _mesh_positions_indices(geom)
        if mi is not None:
            pos, tri = mi
            homog = np.column_stack([pos, np.ones(len(pos))])
            # A node holding a set of placements is that mesh once per placement,
            # so collision has to be too -- a car must not drive through a tree
            # it can see.
            for placed in _placed_worlds(node, world):
                _append_mesh(homog @ placed, tri, points, tris, state,
                             min_hull_size)
    for child in getattr(node, 'children', None) or ():
        _collect(child, world, points, tris, ancestry, state, min_hull_size)


def extract_trimesh(group: Any,
                    min_hull_size: float = 0.0) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Return ``(points, indices)`` of the whole scene's world-space triangles.

    ``group`` is the root scenegraph node. Returns None if it has no extractable
    triangles.

    ``min_hull_size`` (world units): any leaf mesh whose world-space AABB diagonal
    is at or below this is replaced by that AABB's box (8 verts, 12 triangles),
    trading exact collision shape for a much smaller trimesh. ``0`` (default) keeps
    every triangle.
    """
    points: List[np.ndarray] = []
    tris: List[np.ndarray] = []
    _collect(group, np.eye(4), points, tris, (), {'n': 0}, min_hull_size)
    if not points:
        return None
    all_points = np.vstack(points)
    all_tris = np.vstack(tris) if tris else np.zeros((0, 3), dtype='i')
    return all_points, all_tris


def collision_world_from_scene(
        group: Any, gravity: float = 9.81, ground_pad: float = 0.0,
        min_hull_size: float = 0.0
) -> Tuple[PhysicsWorld, Optional[Tuple[np.ndarray, np.ndarray]]]:
    """Build a :class:`PhysicsWorld` whose static geometry is the model's mesh.

    ``group`` is the root scenegraph node.

    Returns ``(world, bounds)`` where bounds is ``(lo, hi)`` of the collision
    geometry (``None`` if the model had no extractable triangles). ``min_hull_size``
    box-ifies sub-components at or below that world-space size (see
    :func:`extract_trimesh`) to speed up loading of large multi-part scenes.
    """
    world = PhysicsWorld(gravity=model.Gravity(gravity=gravity, direction=(0, -1, 0)),
                         default_linear_damping=0.2, default_angular_damping=1.0)
    result = extract_trimesh(group, min_hull_size=min_hull_size)
    if result is None or not len(result[1]):
        return world, None
    points, indices = result
    shape = world.add_shape(model.Shape.trimesh(points, indices))
    world.add_body(model.Motion(type=model.STATIC),
                   collider=model.Collider(shape=shape), position=(0, 0, 0))
    lo = points.min(axis=0) - ground_pad
    hi = points.max(axis=0) + ground_pad
    return world, (lo, hi)
