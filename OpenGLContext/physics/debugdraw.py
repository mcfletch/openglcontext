"""A wireframe overlay of the bodies a physics service holds.

:class:`ProxyOverlay` draws the box and sphere bodies of a physics service from
the service's own shapes and poses; ``Physics.show_proxies`` mounts it. The
wireframes are ``IndexedLineSet`` nodes with per-vertex colour, so they render
through the same path in the legacy and shader profiles.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from OpenGLContext.scenegraph import basenodes as _basenodes

if TYPE_CHECKING:
    from OpenGLContext.physics.service import Physics

__all__ = ['ProxyOverlay']

# basenodes registers its node classes at runtime, so it carries no static
# attributes; access it through an ``Any`` alias.
basenodes: Any = _basenodes

_Edge = tuple[np.ndarray, np.ndarray]

#: The colour of a proxy's wireframe.
C_PROXY = (0.2, 1.0, 0.4)


class ProxyOverlay:
    """The box and sphere bodies of a physics service as wireframes, placed where the bodies are.

    Every box shares one unit box wireframe and every sphere one unit sphere,
    each scaled by its body's ``Transform``, so the instancing pass draws each
    kind in one line draw. :meth:`update` places the bodies the service holds
    and drops the ones it no longer does. Other shapes are left out.
    """

    def __init__(self, physics: Physics) -> None:
        self.physics = physics
        #: The ``Transform`` drawn for each body, by uid.
        self.placed: dict[int, Any] = {}
        self._wires: dict[str, Any] = {}
        self._group = basenodes.Group(children=[])
        self.root = basenodes.Group(children=[self._group])

    def _wire(self, kind: str) -> Any:
        wire = self._wires.get(kind)
        if wire is None:
            wire = self._wires[kind] = _unit_box_wire() if kind == 'box' else _unit_sphere_wire()
        return wire

    def update(self) -> None:
        """Place each box and sphere body where the frame draws it."""
        from OpenGLContext.physics.poses import quat_to_vrml_rotation, write_pose  # noqa: PLC0415 poses import the scenegraph

        physics = self.physics
        specs = physics._specs
        shown = [uid for uid, spec in specs.items() if spec.proxy.kind in ('box', 'sphere')]
        gone = [uid for uid in self.placed if uid not in specs]
        changed = bool(gone)
        for uid in gone:
            del self.placed[uid]
        if shown:
            poses = physics.poses(shown)
            for row, uid in enumerate(shown):
                transform = self.placed.get(uid)
                if transform is None:
                    proxy = specs[uid].proxy
                    size = (proxy.params['size'] if proxy.kind == 'box'
                            else (proxy.params['radius'],) * 3)
                    transform = self.placed[uid] = basenodes.Transform(
                        scale=tuple(float(v) for v in size),
                        children=[basenodes.Shape(geometry=self._wire(proxy.kind))])
                    changed = True
                write_pose(transform, poses.position[row],
                           np.asarray(quat_to_vrml_rotation(poses.orientation[row]), dtype='d'))
        if changed:
            self._group.children = list(self.placed.values())


def _wire_node(edges: list[_Edge]) -> Any:
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


def _ring(center: np.ndarray, radius: float, axis_u: np.ndarray,
          axis_v: np.ndarray, n: int = 16) -> list[_Edge]:
    """Edges of a circle of ``n`` segments in the ``axis_u``/``axis_v`` plane."""
    out: list[_Edge] = []
    prev: Optional[np.ndarray] = None
    for k in range(n + 1):
        t = 2 * np.pi * k / n
        p = center + radius * (np.cos(t) * axis_u + np.sin(t) * axis_v)
        if prev is not None:
            out.append((prev, p))
        prev = p
    return out


def _sphere_edges(center: np.ndarray, radius: float) -> list[_Edge]:
    """Three orthogonal rings approximating a sphere's silhouette."""
    x, y, z = np.eye(3)
    return (_ring(center, radius, x, y) + _ring(center, radius, y, z)
            + _ring(center, radius, x, z))
