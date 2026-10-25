"""Replica: the render thread's own copy of the bodies, for queries and characters.

A world stepped on a thread is the thread's to touch. A ray cast, a sweep or a
character's step on the render thread reads this copy instead: a second
:class:`~omi_physics.world.PhysicsWorld` that is never stepped. Bodies are added
and removed as the commands that make them are sent, and the poses and
velocities of the bodies that move are copied in from each snapshot, so the copy
is as current as the last published tick, and a body that was added a moment ago
is already in it.

The replica shares each :class:`~omi_physics.model.Shape` with the real world by
reference, so a triangle mesh is held once.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from omi_physics import mathutil, model
from omi_physics.collisionquery import WorldQuery
from omi_physics.world import PhysicsWorld

from OpenGLContext.physics.records import BodyBatch, BodySpec, Command, Snapshot

__all__ = ['KINEMATIC_MASS', 'Replica']

#: The mass a character or another body moved by code is given here, so a push
#: against it is a push against something that does not give.
KINEMATIC_MASS = 1.0e6


class Replica:
    """A world that is stepped by nobody, kept like the real one."""

    def __init__(self) -> None:
        self.world = PhysicsWorld(gravity=model.Gravity(gravity=0.0), sleep_enabled=False)
        self.world.log_events = False
        self._index: dict[int, int] = {}
        self._shapes: dict[int, int] = {}
        self._rows: dict[int, int] | None = None
        self._query = WorldQuery(self.world)
        self._rows_index: np.ndarray = np.zeros(0, dtype='i8')
        self._rows_take: np.ndarray = np.zeros(0, dtype='i8')
        #: The replica slot of each snapshot row; -1 for a row of a body not here.
        self._slot_of_row: np.ndarray = np.zeros(0, dtype='i8')
        #: The version of the last snapshot synced from, under the row table ``_rows``.
        self._synced: int | None = None

    @property
    def query(self) -> WorldQuery:
        """The replica as a :class:`~omi_physics.collisionquery.CollisionQuery`."""
        return self._query

    def __contains__(self, uid: int) -> bool:
        return uid in self._index

    def index_of(self, uid: int) -> int:
        """The replica's slot for body ``uid``; KeyError if it is not here."""
        return self._index[uid]

    def uid_at(self, index: int) -> int | None:
        """The id of the body in slot ``index``, or None for an empty slot."""
        handle = self.world.handle_of(self.world.ref(index))
        return None if handle is None else int(handle)

    def apply(self, command: Command) -> None:
        """Mirror a command that changes which bodies there are or where they stand."""
        if command.op == 'add':
            self.add(command.args[0])
        elif command.op == 'add_many':
            self.add_many(command.args[0])
        elif command.op == 'remove_many':
            for number in range(command.args[0], command.args[0] + command.args[1]):
                self.remove(number)
        elif command.op == 'remove':
            self.remove(command.uid)
        elif command.op == 'velocity' and command.uid in self._index:
            self.world.linear_velocity[self._index[command.uid]] = command.args[0]
        elif command.op == 'place' and command.uid in self._index:
            translation, axis_angle = command.args
            orientation = None
            if axis_angle is not None:
                x, y, z, angle = (float(v) for v in axis_angle)
                orientation = mathutil.quat_from_axis_angle((x, y, z), angle)
            self.world.place_body(self._index[command.uid], translation, orientation)

    def add(self, spec: BodySpec) -> None:
        """Make the body ``spec`` describes."""
        world = self.world
        shape = self._shapes.get(spec.proxy.uid)
        if shape is None:
            shape = self._shapes[spec.proxy.uid] = world.add_shape(spec.proxy.shape)
        moves = spec.kind in ('dynamic', 'kinematic')
        motion = model.Motion(type=model.DYNAMIC if moves else model.STATIC,
                              mass=spec.motion.mass if spec.kind == 'dynamic' else KINEMATIC_MASS)
        trigger = model.Trigger(shape=shape) if spec.kind == 'trigger' else None
        collider = None if trigger else model.Collider(shape=shape)
        self._index[spec.uid] = world.add_body(
            motion, collider, trigger, position=spec.position, orientation=spec.orientation,
            handle=spec.uid)
        self._rows = None

    def add_many(self, batch: BodyBatch) -> None:
        """Make the static bodies of ``batch``."""
        world = self.world
        shape = self._shapes.get(batch.proxy.uid)
        if shape is None:
            shape = self._shapes[batch.proxy.uid] = world.add_shape(batch.proxy.shape)
        indices = world.add_bodies(shape, batch.positions, collider=model.Collider(shape=shape))
        for offset, index in enumerate(indices.tolist()):
            self._index[batch.first + offset] = int(index)

    def remove(self, uid: int) -> None:
        """Take body ``uid`` out."""
        index = self._index.pop(uid, None)
        if index is not None:
            self.world.remove_body(index)
            self._rows = None

    def sync(self, snapshot: Snapshot) -> None:
        """Copy the poses and velocities of the bodies that move from ``snapshot``.

        After a sync from the snapshot ``snapshot.base``, only the rows it lists
        as changed are copied and only their boxes refitted.
        """
        if snapshot.rows is not self._rows:
            ours = [(self._index[uid], row) for uid, row in snapshot.rows.items()
                    if uid in self._index]
            self._rows_index = np.array([index for index, _ in ours], dtype='i8')
            self._rows_take = np.array([row for _, row in ours], dtype='i8')
            self._slot_of_row = np.full(len(snapshot.rows), -1, dtype='i8')
            self._slot_of_row[self._rows_take] = self._rows_index
            self._rows = snapshot.rows
            self._synced = None
        changed = snapshot.changed_since(self._synced)
        self._synced = snapshot.version
        if changed is None:
            into, take = self._rows_index, self._rows_take
        else:
            slots = self._slot_of_row[changed]
            mine = slots >= 0
            into, take = slots[mine], changed[mine]
        if len(into) == 0:
            return
        world = self.world
        world.position[into] = snapshot.position[take]
        world.prev_position[into] = snapshot.position[take]
        world.orientation[into] = snapshot.orientation[take]
        world.prev_orientation[into] = snapshot.orientation[take]
        world.linear_velocity[into] = snapshot.linear_velocity[take]
        if changed is None:
            world.refit_aabbs()
        else:
            world.refit_aabbs(rows=into)


def build(specs: dict[int, Any], snapshot: Any = None) -> Replica:
    """A replica holding the bodies of ``specs``, placed from ``snapshot`` where it has them."""
    replica = Replica()
    for uid in sorted(specs):
        spec = specs[uid]
        if isinstance(spec, BodyBatch):
            replica.add_many(spec)
        else:
            replica.add(spec)
    if snapshot is not None:
        replica.sync(snapshot)
    return replica
