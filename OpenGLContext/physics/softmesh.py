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

The mesh is placed by its :attr:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh.origin`,
the soft body's centre of mass, so its positions stay small numbers wherever
the cloth is. Put the mesh's ``Shape`` in the scene under no transform: its
vertices are world positions.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import numpy as np

from OpenGLContext.physics.ragdolls import quat_rotate
from OpenGLContext.physics.softbodies import SoftBody, SoftBodySpec

if TYPE_CHECKING:
    from OpenGLContext.physics.service import Physics

__all__ = ['SoftMesh', 'weld']


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
    particle of each drawn vertex.
    """

    def __init__(self, physics: Physics, mesh: Any, soft: SoftBody, index: np.ndarray) -> None:
        self.physics = physics
        self.mesh = mesh
        self.soft = soft
        self.index = index
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

        ``pins`` is (vertices, points) with the mesh's own vertex indices;
        ``values`` are :class:`~OpenGLContext.physics.softbodies.SoftBodySpec`
        fields (``mass``, ``compliance``, ``pressure``...).
        """
        positions = getattr(mesh, 'positions', None)
        if positions is None or not len(positions):
            raise ValueError('a soft mesh needs a mesh with vertex positions')
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
        made = cls(physics, mesh, soft, index)
        # The rest pose, in place: the mesh's buffers are made dynamic before it is first drawn.
        place = np.asarray(position, dtype='d').reshape(3)
        turn = np.asarray(rotation, dtype='d').reshape(4)
        turn = turn / np.linalg.norm(turn)
        normals = getattr(mesh, 'normals', None)
        mesh.set_vertices(quat_rotate(turn, positions), None if normals is None
                          else quat_rotate(turn, normals), origin=place)
        return made

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
        self.mesh.set_vertices(frame.positions[self.index], frame.normals[self.index],
                               origin=frame.origin)
        self.version = frame.version
        self.writes += 1
        self.physics.note_render_cost('soft bodies', time.perf_counter() - started)
        return True

    def remove(self) -> None:
        """Take the soft body out of the world; the mesh keeps its last vertices."""
        self.physics._forget_soft_mesh(self)
        self.soft.remove()
