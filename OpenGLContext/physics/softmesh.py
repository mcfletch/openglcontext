"""A mesh node simulated as a soft body: cloth, a rope of triangles, a pressure ball.

:meth:`Physics.add_soft_mesh <OpenGLContext.physics.service.Physics.add_soft_mesh>`
takes a :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh` (what glTF meshes
and the engine's generated meshes are drawn as) and makes a soft body of it.
A glTF mesh splits a vertex where its texture coordinates or normals do (a
seam), so the vertices are first welded by position (:func:`weld`): the soft
body has one particle a place, and each drawn vertex keeps the index of its
particle. Every frame the service calls :meth:`SoftMesh.sync`; where the
body's ``version`` has moved, the particles and their normals are gathered
through that index into the mesh's arrays in place, and the mesh's vertex
buffers are written rather than made again. A cloth at rest costs nothing.
A mesh with tangents has each turned with its vertex's normal
(:func:`transport_tangents`), so a normal map follows the folds.

A soft body is made from the mesh's authored vertices (:func:`rest_pose`),
recorded before the first soft body writes them, so the same mesh simulated
again (a scene shown again, or drawn in a second context) starts from where
it was authored.

The mesh is placed by its :attr:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh.origin`,
the soft body's centre of mass, so its positions stay small numbers wherever
the cloth is. Put the mesh's ``Shape`` in the scene under no transform: its
vertices are world positions.
"""
from __future__ import annotations

import time
import weakref
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from OpenGLContext.physics.ragdolls import quat_rotate
from OpenGLContext.physics.softbodies import SoftBody, SoftBodySpec

if TYPE_CHECKING:
    from OpenGLContext.physics.service import Physics

__all__ = ['SoftMesh', 'rest_pose', 'transport_tangents', 'weld']

#: Each mesh's positions array, then its authored positions, normals and tangents, by mesh.
_REST: weakref.WeakKeyDictionary[Any, tuple[Any, np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]] = (
    weakref.WeakKeyDictionary())


def rest_pose(mesh: Any) -> tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """A mesh's authored positions (V, 3), normals (V, 3) and tangents (V, 4), each None where absent.

    Copies are recorded the first time a mesh is asked for, and answered
    while the mesh holds the same positions array: a soft body writes into
    that array in place, and a mesh given new positions is recorded again.
    """
    positions = mesh.positions
    found = _REST.get(mesh)
    if found is None or found[0] is not positions:
        normals, tangents = getattr(mesh, 'normals', None), getattr(mesh, 'tangents', None)
        found = (positions, np.array(positions, dtype='d').reshape(-1, 3),
                 None if normals is None else np.array(normals, dtype='d').reshape(-1, 3),
                 None if tangents is None else np.array(tangents, dtype='d').reshape(-1, 4))
        _REST[mesh] = found
    return found[1], found[2], found[3]


def _units(vectors: np.ndarray) -> np.ndarray:
    """Each row of ``vectors`` (N, 3) scaled to length 1; a row of length 0 is left 0."""
    lengths = np.linalg.norm(vectors, axis=1, keepdims=True)
    return np.divide(vectors, lengths, out=np.zeros_like(vectors), where=lengths > 1e-12)


def transport_tangents(rest_normals: Any, normals: Any, tangents: Any) -> np.ndarray:
    """Tangents (N, 4) turned by the least rotation taking each rest normal to its normal (N, 3).

    Each result is square to its normal and of length 1, its ``w`` (the
    bitangent's sign) kept. Where the normal has turned right over, or the
    turned tangent lies along it, the tangent is made square to the normal
    from whatever direction is left.
    """
    before = _units(np.asarray(rest_normals, dtype='d').reshape(-1, 3))
    after = _units(np.asarray(normals, dtype='d').reshape(-1, 3))
    given = np.asarray(tangents, dtype='d').reshape(-1, 4)
    tangent = given[:, :3]
    # Rodrigues' rotation about before x after, by the angle between them.
    axis = np.cross(before, after)
    cosine = np.sum(before * after, axis=1)
    over = 1.0 + cosine
    scale = np.divide(np.sum(axis * tangent, axis=1), over, out=np.zeros_like(over), where=over > 1e-6)
    turned = tangent * cosine[:, None] + np.cross(axis, tangent) + axis * scale[:, None]
    turned = np.where((over > 1e-6)[:, None], turned, tangent)
    turned -= after * np.sum(after * turned, axis=1, keepdims=True)
    lengths = np.linalg.norm(turned, axis=1)
    lost = lengths < 1e-6
    if lost.any():
        # Any direction square to the normal: across x, or across y for a normal along x.
        across = np.where((np.abs(after[lost, 0]) < 0.9)[:, None], (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        turned[lost] = np.cross(after[lost], across)
        lengths[lost] = np.linalg.norm(turned[lost], axis=1)
    found = np.empty_like(given)
    found[:, :3] = turned / np.maximum(lengths, 1e-12)[:, None]
    found[:, 3] = given[:, 3]
    return found


def weld(positions: Any, tolerance: float = 1e-5) -> tuple[np.ndarray, np.ndarray]:
    """The distinct points of ``positions`` (P, 3) and the point of each vertex (V,).

    Points closer than ``tolerance`` (in the positions' units) on every axis
    are one; the first vertex at a place gives the point its position.
    """
    points = np.asarray(positions, dtype='d').reshape(-1, 3)
    if not len(points):
        return points.copy(), np.zeros(0, dtype=np.intp)
    keys = np.round(points / max(float(tolerance), 1e-12)).astype(np.int64)
    _unique, first, index = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    # Number the points in the order their first vertex comes, so a mesh already welded keeps its order.
    order = np.argsort(first, kind='stable')
    renumber = np.empty_like(order)
    renumber[order] = np.arange(len(order))
    return points[first[order]], renumber[index.reshape(-1)]


class SoftMesh:
    """A mesh whose vertices a soft body moves: the body, the weld, and the per-frame write.

    ``soft`` is the :class:`~OpenGLContext.physics.softbodies.SoftBody`
    (pins, wind, removal); ``mesh`` the mesh it writes; ``index`` the
    particle of each drawn vertex; ``rest_normals`` (V, 3) and
    ``rest_tangents`` (V, 4) the placed rest pose's, which each write turns
    the tangents from, None for a mesh without them.
    """

    def __init__(self, physics: Physics, mesh: Any, soft: SoftBody, index: np.ndarray,
                 rest_normals: Optional[np.ndarray] = None,
                 rest_tangents: Optional[np.ndarray] = None) -> None:
        self.physics = physics
        self.mesh = mesh
        self.soft = soft
        self.index = index
        self.rest_normals = rest_normals
        self.rest_tangents = rest_tangents
        #: The body version last written into the mesh, -1 for none.
        self.version = -1
        #: How many times the mesh has been written.
        self.writes = 0

    @classmethod
    def build(cls, physics: Physics, mesh: Any, position: Any = (0.0, 0.0, 0.0),
              rotation: Any = (0.0, 0.0, 0.0, 1.0), pins: Any = None, pin_bodies: Any = None,
              tolerance: float = 1e-5, collision_filter: Any = None,
              **values: Any) -> SoftMesh:
        """Weld ``mesh``, make its soft body placed by ``position`` and ``rotation``, and bind them.

        The soft body is made from the mesh's authored vertices
        (:func:`rest_pose`). ``pins`` is (vertices, points) with the mesh's
        own vertex indices; ``values`` are
        :class:`~OpenGLContext.physics.softbodies.SoftBodySpec` fields
        (``mass``, ``compliance``, ``pressure``...).
        """
        if getattr(mesh, 'positions', None) is None or not len(mesh.positions):
            raise ValueError('a soft mesh needs a mesh with vertex positions')
        positions, normals, tangents = rest_pose(mesh)
        if getattr(mesh, 'indices', None) is None and len(positions) % 3:
            raise ValueError('a soft mesh is triangles: indexed, or three vertices a face')
        particles, index = weld(positions, tolerance)
        drawn = (np.asarray(mesh.indices, dtype=np.int64).reshape(-1, 3)
                 if mesh.indices is not None
                 else np.arange(len(positions), dtype=np.int64).reshape(-1, 3))
        faces = index[drawn]
        # A face whose corners weld together has no area to hold.
        faces = faces[(faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2])
                      & (faces[:, 0] != faces[:, 2])]
        spec = SoftBodySpec.from_mesh(particles, faces, **values)
        if pins is not None:
            vertices, points = pins
            pins = (index[np.asarray(vertices, dtype=np.intp).reshape(-1)], points)
        soft = physics.add_soft_body(spec, position, rotation, pins=pins, pin_bodies=pin_bodies,
                                     collision_filter=collision_filter)
        # The rest pose, in place: the mesh's buffers are made dynamic before it is first drawn.
        place = np.asarray(position, dtype='d').reshape(3)
        turn = np.asarray(rotation, dtype='d').reshape(4)
        turn = turn / np.linalg.norm(turn)
        turned_normals = None if normals is None else quat_rotate(turn, normals)
        turned_tangents = None
        if tangents is not None:
            turned_tangents = tangents.copy()
            turned_tangents[:, :3] = quat_rotate(turn, tangents[:, :3])
        mesh.set_vertices(quat_rotate(turn, positions), turned_normals, origin=place,
                          tangents=turned_tangents)
        if turned_normals is None:
            turned_tangents = None
        return cls(physics, mesh, soft, index, turned_normals, turned_tangents)

    def pin(self, vertices: Any, points: Any, bodies: Any = None) -> None:
        """Pin mesh vertices (the mesh's own indices) to points; see :meth:`SoftBody.pin`."""
        indices = self.index[np.asarray(vertices, dtype=np.intp).reshape(-1)]
        self.soft.pin(indices.tolist(), points, bodies)

    def sync(self) -> bool:
        """Write the newest vertices into the mesh where they moved; whether it wrote."""
        frame = self.soft.frame()
        if frame is None or frame.version == self.version:
            return False
        started = time.perf_counter()
        normals = frame.normals[self.index]
        tangents = None
        if self.rest_tangents is not None and self.rest_normals is not None:
            tangents = transport_tangents(self.rest_normals, normals, self.rest_tangents)
        self.mesh.set_vertices(frame.positions[self.index], normals, origin=frame.origin,
                               tangents=tangents)
        self.version = frame.version
        self.writes += 1
        self.physics.note_render_cost('soft bodies', time.perf_counter() - started)
        return True

    def remove(self) -> None:
        """Take the soft body out of the world; the mesh keeps its last vertices."""
        self.physics._forget_soft_mesh(self)
        self.soft.remove()
