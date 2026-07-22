"""``PhysicsManager`` — couples a :class:`PhysicsWorld` to scenegraph bodies.

The manager registers :class:`~OpenGLContext.scenegraph.physicsbody.PhysicsBody`
nodes into a world, advances the simulation with the fixed-timestep accumulator,
and writes interpolated poses back to their Transforms.  A context's frame clock
drives :meth:`advance` (see ``events``/``DoEventCascade`` wiring).
"""
from typing import Any, List, Optional
from omi_physics.world import PhysicsWorld

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

    def add(self, body: Any) -> Any:
        """Register a scenegraph ``PhysicsBody`` handle into the world and track it; returns the body."""
        body.register(self.world)
        self.bodies.append(body)
        return body

    def advance(self, real_dt: float) -> float:
        """Step the world by ``real_dt`` seconds and sync poses; returns the interpolation alpha."""
        alpha = self.world.advance(real_dt)
        self.sync(alpha)
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
