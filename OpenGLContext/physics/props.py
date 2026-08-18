"""Standing a world's props up in a physics world, and taking them down again.

A world's boulders are hundreds of bodies and a car touches one of them at a
time; the collision broadphase pays for every one it is holding. So the rule is
the one the ground follows: what is within reach is in the world, and what is
not is taken out again.

A prop's body comes from the prop's own measurements rather than from the mesh
in a tile. Tile geometry is level-of-detail geometry that arrives and leaves as
a camera moves, and a collider that came and went with it would be a rock a car
drives through at the moment the tile behind it swaps. The
:class:`~OpenGLContext.scenegraph.props.Prop` records travel in the tileset's
``extras``, which is the same reason the road does.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

import numpy as np
from omi_physics import model

if TYPE_CHECKING:
    from omi_physics.world import PhysicsWorld

    from OpenGLContext.scenegraph.props import Prop

__all__ = ['PropColliders', 'REACH_METRES', 'SETTLED_METRES']

#: How far from the point props are kept, in metres. Past this nothing is going
#: to reach one before the next update does.
REACH_METRES = 220.0

#: How far the point moves before the set is chosen again, in metres. A stale
#: set is not a wrong one -- reach is generous -- so re-choosing every frame is
#: work for nothing.
SETTLED_METRES = 20.0


class PropColliders:
    """Static bodies for the props near a point, added and removed as it moves.

    :param world: the physics world the props are added to and removed from.
    :param props: every :class:`~OpenGLContext.scenegraph.props.Prop` in the
        world. Held as given; nothing here writes to it.
    :param reach: how far from the point props are kept, in metres.
    :param settled: how far the point may move before the set is re-chosen.

    Call :meth:`update` with where the thing that might hit one is.
    """

    def __init__(self, world: "PhysicsWorld", props: "Sequence[Prop]",
                 reach: float = REACH_METRES,
                 settled: float = SETTLED_METRES) -> None:
        self.world = world
        self.props = list(props)
        self.reach = float(reach)
        self.settled = float(settled)
        #: The props with a body in the world right now.
        self.standing: list = []
        self._bodies: dict[int, int] = {}
        self._at: Any = None
        self._plan = np.asarray(
            [[p.position[0], p.position[2]] for p in self.props],
            dtype='d').reshape(-1, 2)

    def update(self, position: Any) -> None:
        """Hold the props within reach of here, and let go of the rest."""
        at = np.asarray(position, dtype='d').reshape(-1)[:3]
        if self._at is not None and float(np.hypot(
                at[0] - self._at[0], at[2] - self._at[2])) <= self.settled:
            return
        self._at = at.copy()
        if not len(self._plan):
            return
        near = np.nonzero(
            np.hypot(self._plan[:, 0] - at[0], self._plan[:, 1] - at[2])
            <= self.reach)[0]
        wanted = {int(index) for index in near}
        for index in list(self._bodies):
            if index not in wanted:
                self.world.remove_body(self._bodies.pop(index))
        for index in sorted(wanted):
            if index not in self._bodies:
                self._bodies[index] = self._stand(self.props[index])
        self.standing = [self.props[index] for index in sorted(self._bodies)]

    def release(self) -> None:
        """Take every prop out of the physics world."""
        for index in list(self._bodies):
            self.world.remove_body(self._bodies.pop(index))
        self.standing = []
        self._at = None

    def _stand(self, prop: "Prop") -> int:
        """One prop as a static body: an upright box the size it takes up.

        A box rather than the mesh it is drawn as. What a car needs from a
        boulder is that it stops there, and a triangle soup per rock costs the
        broadphase and the narrow phase both for a difference nobody driving
        past at forty metres a second can see.
        """
        shape = self.world.add_shape(model.Shape.box(
            (prop.radius * 2.0, prop.height, prop.radius * 2.0)))
        half = np.array([0.0, prop.height / 2.0, 0.0])
        return int(self.world.add_body(
            model.Motion(type=model.STATIC),
            collider=model.Collider(shape=shape),
            position=tuple(np.asarray(prop.position, dtype='d') + half),
            orientation=_yaw(prop.yaw)))


def _yaw(angle: float) -> tuple:
    """A rotation about the vertical, as the quaternion the world wants."""
    half = float(angle) / 2.0
    return (0.0, float(np.sin(half)), 0.0, float(np.cos(half)))
