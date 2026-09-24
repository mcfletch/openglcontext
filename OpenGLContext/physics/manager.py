"""``PhysicsManager`` — couples a :class:`PhysicsWorld` to scenegraph bodies.

The manager registers :class:`~OpenGLContext.scenegraph.physicsbody.PhysicsBody`
nodes into a world, advances the simulation with the fixed-timestep accumulator,
writes interpolated poses back to their Transforms, and then delivers the
frame's collisions to the callbacks subscribed through :attr:`PhysicsManager.events`
(:mod:`OpenGLContext.physics.events`).  The application calls :meth:`advance`
once a frame, usually from its ``OnIdle``.
"""
from collections import OrderedDict
from typing import Any, List, Optional

from omi_physics.contactevents import BodyRef
from omi_physics.world import PhysicsWorld

from .events import CollisionEvents

_ROT_FIELD_CACHE: dict = {}


def write_pose(transform: Any, pos_row: Any, aa_row: Any) -> None:
    """Write an (interpolated) pose onto a scene ``Transform`` as cheaply as possible.

    Pass numpy rows (not tuples) so the field coercion takes its fast array path,
    and set the rotation without a change notification: a single dispatch on
    ``translation`` already invalidates the node's cached local matrix (the cache
    holder depends on every TRS field), so a second one on ``rotation`` is wasted.
    Together this roughly halves the per-body sync cost.
    """
    transform.translation = pos_row                 # array coerce + 1 dispatch
    tt = type(transform)
    rot = _ROT_FIELD_CACHE.get(tt)
    if rot is None:
        from vrml import protofunctions
        rot = protofunctions.getField(transform, 'rotation')
        _ROT_FIELD_CACHE[tt] = rot
    rot.fset(transform, aa_row, False)              # array coerce, no dispatch


class PhysicsManager:
    """Couples a :class:`PhysicsWorld` to scenegraph bodies: register, advance, write poses back."""

    def __init__(self, world: Optional[PhysicsWorld] = None, gravity: Any = None,
                 default_linear_damping: float = 0.3,
                 default_angular_damping: float = 1.5,
                 **world_kw: Any) -> None:
        """Wrap ``world``, building a default one from the given damping/gravity if none is passed."""
        if world is None:
            world = PhysicsWorld(gravity=gravity,
                                 default_linear_damping=default_linear_damping,
                                 default_angular_damping=default_angular_damping,
                                 **world_kw)
        self.world = world
        self.bodies: List[Any] = []
        #: Collision subscriptions: :meth:`CollisionEvents.subscribe
        #: <OpenGLContext.physics.events.CollisionEvents.subscribe>`.
        self.events = CollisionEvents(self)
        self._handles: dict = {}
        #: Bodies removed recently, so events about their last contacts still
        #: name them. Bounded: only the events of the next frame or two need it.
        self._retired: "OrderedDict[BodyRef, Any]" = OrderedDict()

    #: Whether :meth:`advance` steps the world on the calling thread.
    steps_on_this_thread = True
    #: How many removed bodies :meth:`handle` still answers for.
    RETIRED_KEPT = 4096

    def add(self, body: Any) -> Any:
        """Register a scenegraph ``PhysicsBody`` handle into the world and track it; returns the body."""
        body.register(self.world)
        self.bodies.append(body)
        self._handles[self.world.ref(body.index)] = body
        return body

    def remove(self, body: Any) -> None:
        """Take ``body`` out of the world and stop writing its pose.

        The pairs it was touching end with ``reason='removed'``, and the
        subscriptions on it hear those ends at the next :meth:`advance` and
        then finish. ``body.index`` is None afterwards.
        """
        if body.index is None:
            return
        ref = self.world.ref(body.index)
        self._remove_body(body.index)
        self._handles.pop(ref, None)
        self._retired[ref] = body
        while len(self._retired) > self.RETIRED_KEPT:
            self._retired.popitem(last=False)
        if body in self.bodies:
            self.bodies.remove(body)
        body.index = None

    def _remove_body(self, index: int) -> None:
        """Remove body ``index`` from the world."""
        self.world.remove_body(index)

    def handle(self, ref: BodyRef) -> Any:
        """The ``PhysicsBody`` ``ref`` names, or ``ref`` itself for a body added without one."""
        found = self._handles.get(ref)
        if found is None:
            found = self._retired.get(ref)
        if found is None:
            found = self.world.handle_of(ref)
        return ref if found is None else found

    def body_for(self, transform: Any) -> Any:
        """The registered ``PhysicsBody`` driving ``transform``, or None."""
        for body in self.bodies:
            if body.transform is transform:
                return body
        return None

    def advance(self, real_dt: float) -> float:
        """Step the world by ``real_dt`` seconds, sync poses and deliver collisions.

        Returns the interpolation alpha. Collision callbacks run last, so they
        see the scene in the pose this frame draws.
        """
        alpha = self.world.advance(real_dt)
        self.sync(alpha)
        if self.events.draining:
            self.events.dispatch(self.world.contact_log.drain())
        return alpha

    def sync(self, alpha: float = 1.0) -> None:
        """Write each body's interpolated pose (``alpha`` in ``[0, 1]``) to its scene Transform.

        The interpolation and quaternion→axis-angle conversion run once for all
        bodies with numpy; the per-body loop then only assigns the two Transform
        fields, which cannot be batched across separate scene nodes. Sleeping
        dynamic bodies are skipped -- their pose has not changed.
        """
        from omi_physics import mathutil
        w = self.world
        n = w.body_count
        if n == 0:
            return
        pos = w.prev_position[:n] * (1 - alpha) + w.position[:n] * alpha
        quat = mathutil.quat_normalize(
            w.prev_orientation[:n] * (1 - alpha) + w.orientation[:n] * alpha)
        aa = mathutil.quat_to_axis_angle(quat)
        awake = w.awake[:n]
        dynamic = w.motion_type[:n] == 2
        for body in self.bodies:
            i = body.index
            if i is None or (dynamic[i] and not awake[i]):
                continue
            write_pose(body.transform, pos[i], aa[i])
