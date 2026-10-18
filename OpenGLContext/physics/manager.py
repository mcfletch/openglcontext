"""``PhysicsManager`` — couples a :class:`PhysicsWorld` to scenegraph bodies.

The manager registers :class:`~OpenGLContext.scenegraph.physicsbody.PhysicsBody`
nodes into a world, advances the simulation with the fixed-timestep accumulator,
writes interpolated poses back to their Transforms, and then delivers the
frame's collisions to the callbacks subscribed through :attr:`PhysicsManager.events`
(:mod:`OpenGLContext.physics.events`).  The application calls :meth:`advance`
once a frame, usually from its ``OnIdle``.
"""
from collections import OrderedDict
from collections.abc import Hashable
from contextlib import AbstractContextManager, nullcontext
from typing import Any, Optional
import typing

from omi_physics.contactevents import BodyRef
from omi_physics.world import PhysicsWorld
if typing.TYPE_CHECKING:
    from OpenGLContext.scenegraph.physicsbody import PhysicsBody

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
        from vrml import field, protofunctions
        declared = protofunctions.getField(transform, 'rotation')
        if not isinstance(declared, field.Field):
            raise TypeError('%s.rotation is an event, which holds no pose' % (tt.__name__,))
        rot = _ROT_FIELD_CACHE[tt] = declared
    rot.fset(transform, aa_row, False)              # array coerce, no dispatch


class PhysicsManager:
    """Couples a :class:`PhysicsWorld` to scenegraph bodies: register, advance, write poses back."""

    #: Whether :meth:`advance` steps the world on the calling thread.
    steps_on_this_thread = True
    #: How many removed bodies :meth:`handle` still answers for.
    RETIRED_KEPT = 4096

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
        #: World material indices for the presets :meth:`attach` has been given by name.
        self._presets: dict[str, int] = {}
        # The world's event log is the manager's to drain, and it is wanted
        # only once something subscribes (CollisionEvents switches it on);
        # until then listeners are called and nothing is kept.
        world.log_events = False
        #: The registered bodies in the order they were added, as dictionary
        #: keys so that removing one does not search for it.
        self._bodies: dict[Any, None] = {}
        #: Each registered body by the Transform it drives.
        self._by_transform: dict[Any, Any] = {}
        #: Collision subscriptions: :meth:`CollisionEvents.subscribe
        #: <OpenGLContext.physics.events.CollisionEvents.subscribe>`.
        self.events = CollisionEvents(self)
        #: Bodies removed recently, so events about their last contacts still
        #: name them. Bounded: only the events of the next frame or two need it.
        self._retired: "OrderedDict[BodyRef, Any]" = OrderedDict()

    @property
    def bodies(self) -> list['PhysicsBody']:
        """The registered ``PhysicsBody`` handles, in the order they were added."""
        return list(self._bodies)

    def with_world(self) -> AbstractContextManager[Any]:
        """Exclusive access to the world while it is changed.

        This manager steps the world on the caller's thread, so there is
        nothing to wait for; a threaded manager answers its simulation's lock.
        Code that changes the world outside :meth:`advance` takes it, so the
        same code runs under either.
        """
        return nullcontext()

    def add(self, body: 'PhysicsBody') -> 'PhysicsBody':
        """Register a scenegraph ``PhysicsBody`` handle into the world and track it; returns the body."""
        body.register(self.world)
        self._bodies[body] = None
        self._by_transform[body.transform] = body
        return body

    def attach(self, node: Any, motion: Any = None, *, material: Any = None,
               strategy: str = 'auto', trigger: bool = False,
               collision_filter: int = -1) -> 'PhysicsBody':
        """Make a scenegraph node a physics body; returns its ``PhysicsBody``.

        The collision shape is cooked from the geometry the node draws
        (:func:`~OpenGLContext.physics.gltf_world.node_mesh`), so what is drawn
        and what is collided with cannot disagree, and the body is bound to the
        node: the world moves the node while the body is dynamic.  ``node`` is
        a ``Transform`` holding the geometry, placed where the body starts.

        ``motion`` is an ``omi_physics.model.Motion``; left out the body is
        static, which is what scenery is.  ``material`` is a preset name from
        ``model.MATERIAL_PRESETS``, a ``model.Material``, or the index of one
        already in the world.  ``strategy`` is one of
        :func:`omi_physics.cookery.cook_shape`'s: ``primitive`` fits a box or
        a sphere, ``convex`` the hull, ``trimesh`` the triangles of a static
        body, and ``auto`` is the triangles for a static body and the hull
        for a dynamic one.  ``decompose`` makes several shapes and a body has
        one.  ``trigger=True`` makes the shape a
        trigger volume that reports what enters it and stops nothing.

        Raises ``ValueError`` for a node that draws no triangles, and for a
        strategy that makes several shapes.
        """
        from omi_physics import model
        from omi_physics.cookery import cook_shape

        from OpenGLContext.scenegraph.physicsbody import PhysicsBody

        from .gltf_world import node_mesh

        found = node_mesh(node)
        if found is None:
            raise ValueError('%r draws no triangles to make a collision shape from' % (node,))
        points, indices = found
        motion = motion if motion is not None else model.Motion(type=model.STATIC)
        dynamic = motion.type == model.DYNAMIC
        if strategy == 'auto' and dynamic:
            strategy = 'convex'
        shape = cook_shape(points, indices, strategy, dynamic)
        if isinstance(shape, list):
            raise ValueError('strategy %r makes several shapes and a body has one' % strategy)
        with self.with_world():
            shape_index = self.world.add_shape(shape)
            if trigger:
                body = PhysicsBody(node, motion, trigger=model.Trigger(
                    shape=shape_index, collisionFilter=collision_filter))
            else:
                body = PhysicsBody(node, motion, model.Collider(
                    shape=shape_index, physicsMaterial=self._material_index(material),
                    collisionFilter=collision_filter))
            return self.add(body)

    def _material_index(self, material: Any) -> int:
        """The world's index for a preset name, a ``Material`` or an index; -1 for none."""
        from omi_physics import model
        if material is None:
            return -1
        if isinstance(material, int):
            return material
        if isinstance(material, str):
            if material not in self._presets:
                self._presets[material] = self.world.add_material(
                    model.MATERIAL_PRESETS[material])
            return self._presets[material]
        return int(self.world.add_material(material))

    def remove(self, body: 'PhysicsBody') -> None:
        """Take ``body`` out of the world and stop writing its pose.

        The pairs it was touching end with ``reason='removed'``, and the
        subscriptions on it hear those ends at the next :meth:`advance` and
        then finish. ``body.index`` is None afterwards. On a threaded manager
        this takes :meth:`with_world` itself.
        """
        if body.index is None:
            return
        ref = self.world.ref(body.index)
        self._remove_body(body.index)
        self._retired[ref] = body
        while len(self._retired) > self.RETIRED_KEPT:
            self._retired.popitem(last=False)
        self._forget(body)
        body.index = None

    def _forget(self, body: 'PhysicsBody') -> None:
        """Stop tracking ``body``."""
        self._bodies.pop(body, None)
        transform = body.transform
        if self._by_transform.get(transform) is body:
            del self._by_transform[transform]

    def _remove_body(self, index: int) -> None:
        """Remove body ``index`` from the world."""
        self.world.remove_body(index)

    def handle(self, ref: BodyRef) -> Any:
        """The ``PhysicsBody`` ``ref`` names, or ``ref`` itself for a body added without one."""
        found = self.world.handle_of(ref)
        if found is None:
            found = self._retired.get(ref)
        return ref if found is None else found

    def body_for(self, transform: Any) -> Any:
        """The registered ``PhysicsBody`` driving ``transform``, or None.

        None for anything that cannot be a transform's key, such as a list of
        bodies handed to :meth:`CollisionEvents.resolve
        <OpenGLContext.physics.events.CollisionEvents.resolve>`.
        """
        if not isinstance(transform, Hashable):
            return None
        return self._by_transform.get(transform)

    def advance(self, real_dt: float) -> float:
        """Step the world by ``real_dt`` seconds, sync poses and deliver collisions.

        Returns the interpolation alpha. Collision callbacks run last, so they
        see the scene in the pose this frame draws.

        The world's :attr:`~omi_physics.world.PhysicsWorld.contact_log` is
        drained every frame, whether or not anything has subscribed, so a
        subscription made later hears only what happens after it.
        """
        alpha = self.world.advance(real_dt)
        self.sync(alpha)
        events = self.world.contact_log.drain()
        if self.events.draining:
            self.events.dispatch(events)
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
        for body in self._bodies:
            i = body.index
            if i is None or (dynamic[i] and not awake[i]):
                continue
            write_pose(body.transform, pos[i], aa[i])
