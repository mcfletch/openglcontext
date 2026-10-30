"""Scenery as static bodies.

A shape in the scene that no body claims is a static trimesh body, so what is
drawn is what a ball rolls on and a walker stands on. :class:`SceneryTracker`
finds the shapes when the scene's set of paths changes, makes a
:class:`~OpenGLContext.physics.body.Body` for each new one at once, and has its
triangles cooked on a worker thread; the body joins the world when the cooking
is done. A shape that leaves the scene loses its body.

A shape is left out when it is marked ``collide = False``, when it sits in a
disabled X3D ``Collision`` group, when it draws no triangles, and when a body
other than scenery claims it or a node above it. A shape's body is placed where
the shape stood when it was first seen; scenery that moves is a kinematic body.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
from omi_physics import model

from OpenGLContext.physics.body import Body
from OpenGLContext.physics.gltf_world import MeshSite, _mesh_positions_indices, iter_meshes, site_mesh
from OpenGLContext.physics.omi_adapter import proxy_from_shape
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.records import BodySpec

if TYPE_CHECKING:
    from OpenGLContext.physics.service import Physics

__all__ = ['SceneryTracker']

log = logging.getLogger(__name__)
_STATIC = model.Motion(type=model.STATIC)


class SceneryTracker:
    """Keeps a static body for each shape of a scene."""

    def __init__(self, physics: Physics) -> None:
        self.physics = physics
        self._generation: Any = None
        #: The body made for each shape, by the shape.
        self.derived: dict[Any, Body] = {}

    def update(self, root: Any, generation: Any) -> int:
        """Look at ``root`` if its ``generation`` is not the one last looked at.

        Returns how many shapes were new. The walk is the cost of a change to
        the scene; a frame in which the scene did not change costs a comparison.
        """
        if generation == self._generation:
            return 0
        self._generation = generation
        physics = self.physics
        if physics.definition.colliders != 'scene' or physics.closed:
            return 0
        present = set()
        fresh = 0
        for site in iter_meshes(root, skip=self._claimed, tagged=True):
            node = site.node
            if getattr(node, 'collide', True) is False:
                continue
            present.add(node)
            if node in self.derived:
                continue
            fresh += self._start_authored(site) if site.tag is not None else self._start(site)
        for node in [node for node in self.derived if node not in present]:
            physics.remove(self.derived.pop(node))
        return fresh

    def _claimed(self, node: Any) -> bool:
        """Whether a body other than scenery stands for ``node`` and what is under it."""
        body = self.physics._by_node.get(node)
        return body is not None and not body.derived

    def _start(self, site: MeshSite) -> int:
        mesh = _mesh_positions_indices(site.geometry)
        if mesh is None or len(mesh[1]) == 0:
            return 0
        body = self.physics._derive(site.node)
        self.derived[site.node] = body
        self.physics._cook_later(body, lambda: self._spec(body, site, mesh))
        return 1

    def _start_authored(self, site: MeshSite) -> int:
        """Make the body a glTF node's ``OMI_physics_body`` describes."""
        document, body = site.tag
        physics = self.physics
        node = site.node
        proxies = document.__dict__.setdefault('_proxies', {})
        shape_index = body.collider.shape if body.collider else body.trigger.shape
        if not 0 <= shape_index < len(document.shapes):
            log.warning('node %r names shape %d, which the document does not have',
                        node, shape_index)
            return 0
        proxy = proxies.get(shape_index)
        if proxy is None:
            proxy = proxies[shape_index] = proxy_from_shape(document.shapes[shape_index])
        motion = body.motion or model.Motion(type=model.STATIC)
        material = None
        if body.collider is not None and 0 <= body.collider.physicsMaterial < len(document.materials):
            material = document.materials[body.collider.physicsMaterial]
        kind = 'trigger' if body.trigger is not None and body.collider is None else {
            model.DYNAMIC: 'dynamic', model.KINEMATIC: 'kinematic'}.get(motion.type, 'static')
        pose = None
        if kind in ('static', 'trigger'):
            pose = (tuple(float(v) for v in site.world[3, :3]), _quaternion_of(site.world))
        made = physics._add(kind, node, proxy, {'material': material}, motion=motion,
                            pose=pose, derived=True)
        self.derived[node] = made
        return 1

    @staticmethod
    def _spec(body: Body, site: MeshSite, mesh: tuple[np.ndarray, np.ndarray]) -> BodySpec | None:
        """The body spec for ``site``, with its triangles in world space (on the cooking thread)."""
        found = site_mesh(site, mesh=mesh)
        if found is None or len(found[1]) == 0:
            return None
        points, triangles = found
        return BodySpec(body.uid, 'static', Proxy.trimesh(points, triangles), _STATIC)

    def release(self, node: Any) -> None:
        """Forget the body made for ``node``, which has become the application's."""
        self.derived.pop(node, None)


def _quaternion_of(world: np.ndarray) -> tuple[float, ...]:
    """The turn of a row-vector world matrix as a quaternion ``(x, y, z, w)``, scale removed."""
    rotation = np.array(world[:3, :3], dtype='d')
    lengths = np.linalg.norm(rotation, axis=1)
    m = (rotation / np.where(lengths > 0.0, lengths, 1.0)[:, None]).T
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0.0:
        w = float(np.sqrt(1.0 + trace)) / 2.0
        x, y, z = (m[2, 1] - m[1, 2]) / (4 * w), (m[0, 2] - m[2, 0]) / (4 * w), (m[1, 0] - m[0, 1]) / (4 * w)
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        r = float(np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])) * 2.0
        w, x, y, z = (m[2, 1] - m[1, 2]) / r, r / 4.0, (m[0, 1] + m[1, 0]) / r, (m[0, 2] + m[2, 0]) / r
    elif m[1, 1] > m[2, 2]:
        r = float(np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])) * 2.0
        w, x, y, z = (m[0, 2] - m[2, 0]) / r, (m[0, 1] + m[1, 0]) / r, r / 4.0, (m[1, 2] + m[2, 1]) / r
    else:
        r = float(np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])) * 2.0
        w, x, y, z = (m[1, 0] - m[0, 1]) / r, (m[0, 2] + m[2, 0]) / r, (m[1, 2] + m[2, 1]) / r, r / 4.0
    return (float(x), float(y), float(z), float(w))
