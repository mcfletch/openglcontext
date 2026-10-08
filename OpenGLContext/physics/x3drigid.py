"""X3D's RigidBodyPhysics on omi_physics -- no GL

A `RigidBodyCollection` is a :class:`RigidSystem`: one
:class:`~omi_physics.world.PhysicsWorld` holding a body for each enabled
`RigidBody` of the collection, and a static body for each collidable that is
in no body but that the collection's `collider`, or a `Contact` sent to its
`set_contacts`, names. :meth:`RigidSystem.advance` steps it by a frame's
time, in fixed steps of :data:`STEP` seconds (:data:`ACCURATE_STEP` where the
collection prefers accuracy), and sends what moved: each body's `position`,
`orientation`, `linearVelocity` and `angularVelocity`, the `translation` and
`rotation` of the collidables a body carries, and each joint's outputs its
`forceOutput` names.

What collides is what the X3D model says collides:

- the collidables of the collection's `collider`, with that
  `CollisionCollection`'s parameters, at every step;
- the pairs the `Contact` nodes last sent to `set_contacts` name, with each
  contact's parameters, for the frame that follows. The contact points are
  found again at each step from where the bodies are. A contact one of whose
  sides names neither a body nor a collidable is against the world: a fixed
  surface through its `position`, across its `contactNormal`, which points
  from `body1` toward `body2`.

Two collidables of one body never collide, nor do two bodies a joint holds.
A `CollisionSensor` finds the touches among its collider's collidables where
they stand (:func:`detect`), without stepping anything.

A collidable carried by a body is drawn and collided where the body is: its
`translation` and `rotation` are the body's. A `CollidableOffset` places the
collidable it holds by that collidable's own `translation` and `rotation`, in
the body's frame. A collidable in no body is where its own fields put it.

Geometry becomes a collision shape by its kind (:func:`geometry_shape`): a
`Box`, `Sphere`, `Cylinder` or `Cone` as itself, any other geometry that has
triangles as its mesh, which for a body that moves is the mesh's convex hull.
A collidable reached through a `CollisionSpace` whose `useGeometry` is false
collides as the box that bounds it.
"""
from __future__ import annotations

import math
import weakref
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Optional

import numpy as np
from omi_physics import joints as omi_joints
from omi_physics import mathutil, model
from omi_physics.body import make_proxy, world_aabb
from omi_physics.collide import collide
from omi_physics.hull import convex_hull
from omi_physics.world import PhysicsWorld
from vrml import cache, protofunctions
from vrml import node as vrml_node
from vrml.x3d import interpolation

__all__ = ['ACCURATE_STEP', 'MAX_FRAME', 'NOMINAL_STEP', 'STEP', 'RigidSystem', 'Touch',
           'collidable_parts', 'contact_parameters', 'detect', 'geometry_shape', 'members']

#: The fixed step a collection is simulated in, in seconds.
STEP = 1.0 / 120.0
#: The step of a collection whose `preferAccuracy` is true.
ACCURATE_STEP = 1.0 / 240.0
#: The most time one frame advances a collection by, in seconds.
MAX_FRAME = 0.25
#: The step X3D's per-step quantities are read against: the damping factors
#: and a suspension's force mixing and error correction.
NOMINAL_STEP = 1.0 / 60.0

_LEVEL = np.array([0.0, 0.0, 0.0, 1.0])
_IDENTITY_INERTIA = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
_SHAPE_KEY = 'x3drigid-shape'
#: Half the size of the box standing for the world in a contact with one body.
_SURFACE = 500.0
#: Where such a box waits while no contact needs it.
_PARKED = np.array([0.0, -1.0e7, 0.0])


def _turn_onto(start: Any, end: Any) -> np.ndarray:
    """The shortest turn, a quaternion, taking the unit vector `start` onto `end`"""
    start = np.asarray(start, dtype='d')
    end = np.asarray(end, dtype='d')
    axis = np.cross(start, end)
    cosine = float(np.dot(start, end))
    if cosine < -0.999999:
        other = np.array([1.0, 0.0, 0.0]) if abs(start[0]) < 0.9 else np.array([0.0, 0.0, 1.0])
        axis = np.cross(start, other)
        return np.append(axis / np.linalg.norm(axis), 0.0)
    turn = np.append(axis, 1.0 + cosine)
    return turn / np.linalg.norm(turn)


def quaternion(rotation: Any) -> np.ndarray:
    """An X3D rotation (axis, angle) as a unit quaternion (x, y, z, w)"""
    found: np.ndarray = interpolation.quaternion_of(np.asarray(rotation, dtype='d'))
    return np.asarray(found, dtype='d')


def rotation(turn: np.ndarray) -> np.ndarray:
    """A unit quaternion (x, y, z, w) as an X3D rotation"""
    found: np.ndarray = interpolation.rotation_of(turn)
    return np.asarray(found, dtype='d')


def _kind(node: Any) -> str:
    """The X3D name of a node's type"""
    return str(getattr(type(node), 'PROTO', type(node).__name__))


# -- shapes ---------------------------------------------------------------
def geometry_shape(geometry: Any, moving: bool) -> Optional[model.Shape]:
    """The collision shape of an X3D geometry node, in its own frame; None for none

    `moving` asks for the shape of a body that moves, which for a mesh is its
    convex hull rather than its triangles. The shape is kept on the geometry
    node until one of the node's fields, or of the nodes it holds, changes.
    """
    if not geometry:
        return None
    key = (_SHAPE_KEY, bool(moving))
    holder = cache.CACHE.getHolder(geometry, key=key)
    if holder is not None and holder.data is not None:
        found: model.Shape = holder.data[0]
        return found
    shape = _build_shape(geometry, moving)
    holder = cache.CACHE.holder(geometry, (shape,), key=key)
    _depend_on_fields(holder, geometry)
    return shape


def _depend_on_fields(holder: Any, node: Any) -> None:
    """Make `holder` depend on every field of `node` and of the nodes its fields hold"""
    for found in protofunctions.getFields(node):
        holder.depend(node, found)
        if isinstance(found, vrml_node.SFNode):
            child = getattr(node, found.name, None)
            if child:
                _depend_on_fields(holder, child)


def _build_shape(geometry: Any, moving: bool) -> Optional[model.Shape]:
    """:func:`geometry_shape`'s answer, worked out"""
    kind = _kind(geometry)
    if kind == 'Box':
        return model.Shape.box(tuple(float(value) for value in geometry.size))
    if kind == 'Sphere':
        return model.Shape.sphere(float(geometry.radius))
    if kind == 'Cylinder':
        return model.Shape.cylinder(height=float(geometry.height), radius=float(geometry.radius))
    if kind == 'Cone':
        return model.Shape(type='cylinder', height=float(geometry.height),
                           radiusBottom=float(geometry.bottomRadius), radiusTop=0.0)
    from OpenGLContext.scenegraph import meshdata  # noqa: PLC0415 the scenegraph's, read only for meshes
    arrays = meshdata.geometry_arrays(geometry)
    if arrays is None:
        return None
    points = np.asarray(arrays.attributes['POSITION'], dtype='d').reshape(-1, 3)
    if arrays.indices is None:
        corners = np.arange((len(points) // 3) * 3)
    else:
        corners = np.asarray(arrays.indices, dtype=np.int64).ravel()
    if not len(corners):
        return None
    if moving:
        hull, _faces = convex_hull(points[corners])
        return model.Shape.convex(hull)
    return model.Shape.trimesh(points, corners.reshape(-1, 3))


def collidable_parts(collidable: Any, moving: bool,
                     bounds_only: bool = False) -> list[model.ShapePart]:
    """The shapes of a collidable, in its own frame; empty for a disabled one

    A `CollidableOffset`'s are those of the collidable it holds, placed by
    that collidable's `translation` and `rotation`. `bounds_only` gives each
    shape as the box that bounds it.
    """
    if not collidable or not getattr(collidable, 'enabled', True):
        return []
    kind = _kind(collidable)
    if kind == 'CollidableOffset':
        inner = collidable.collidable
        if not inner:
            return []
        place = np.asarray(inner.translation, dtype='d')
        turn = quaternion(inner.rotation)
        placed = []
        for part in collidable_parts(inner, moving, bounds_only):
            placed.append(model.ShapePart(
                part.shape,
                tuple(place + mathutil.quat_to_matrix(turn) @ np.asarray(part.position)),
                tuple(mathutil.quat_mul(turn, np.asarray(part.orientation, dtype='d')))))
        return placed
    if kind != 'CollidableShape' or not collidable.shape:
        return []
    shape = geometry_shape(getattr(collidable.shape, 'geometry', None), moving)
    if shape is None:
        return []
    if bounds_only:
        low, high = world_aabb(shape, (0.0, 0.0, 0.0), _LEVEL)
        return [model.ShapePart(model.Shape.box(tuple(high - low)),
                                tuple(0.5 * (low + high)))]
    return [model.ShapePart(shape)]


def _inner_collidables(collidable: Any) -> list[Any]:
    """A collidable and those an offset holds within it"""
    found = [collidable]
    if _kind(collidable) == 'CollidableOffset' and collidable.collidable:
        found.extend(_inner_collidables(collidable.collidable))
    return found


def members(collection: Any) -> list[tuple[Any, bool]]:
    """The collidables of a `CollisionCollection`, each with whether it collides by its bounds

    Spaces are walked into; a disabled collection or space has none.
    """
    if not collection or not getattr(collection, 'enabled', True):
        return []
    found: list[tuple[Any, bool]] = []
    seen: set[Any] = set()

    def walk(nodes: Iterable[Any], bounds: bool) -> None:
        for node in nodes:
            if not node:
                continue
            if _kind(node) == 'CollisionSpace':
                if node.enabled:
                    walk(node.collidables, bounds or not node.useGeometry)
            elif node not in seen:
                seen.add(node)
                found.append((node, bounds))

    walk(collection.collidables, False)
    return found


def contact_parameters(source: Any) -> model.ContactParameters:
    """How a `CollisionCollection` or a `Contact` says its pairs meet

    Each parameter applies where `appliedParameters` names it: BOUNCE the
    bounce and its least speed, FRICTION_COEFFICIENT-2 the second friction
    coefficient (else the first acts both ways), USER_FRICTION a contact's
    friction direction, SPEED-1 and SPEED-2 the surface speeds, SLIP-1 and
    SLIP-2 the slips, ERROR_REDUCTION and CONSTANT_FORCE the softness's error
    correction and force mixing; what is not named is the collection's own.
    """
    applied = {str(value) for value in source.appliedParameters}
    first, second = (float(value) for value in source.frictionCoefficients)
    surface = tuple(float(value) for value in source.surfaceSpeed)
    slips = getattr(source, 'slipFactors', None)
    if slips is None:
        slips = source.slipCoefficients
    slip = tuple(float(value) for value in slips)
    direction = None
    if 'USER_FRICTION' in applied and hasattr(source, 'frictionDirection'):
        direction = tuple(float(value) for value in source.frictionDirection)
    bounce = 'BOUNCE' in applied
    return model.ContactParameters(
        restitution=float(source.bounce) if bounce else 0.0,
        bounce_speed=float(source.minBounceSpeed) if bounce else None,
        friction=(first, second) if 'FRICTION_COEFFICIENT-2' in applied else first,
        friction_direction=direction,
        surface_speed=(surface[0] if 'SPEED-1' in applied else 0.0,
                       surface[1] if 'SPEED-2' in applied else 0.0),
        slip=(slip[0] if 'SLIP-1' in applied else 0.0, slip[1] if 'SLIP-2' in applied else 0.0),
        softness=(float(source.softnessConstantForceMix) if 'CONSTANT_FORCE' in applied
                  else None),
        error_correction=(float(source.softnessErrorCorrection)
                          if 'ERROR_REDUCTION' in applied else None))


# -- where a collidable is -----------------------------------------------
#: Each collidable a running collection's body carries: the body, and where in
#: the body's frame the collidable is.
_CARRIED: 'weakref.WeakKeyDictionary[Any, tuple[Any, np.ndarray, np.ndarray]]' = (
    weakref.WeakKeyDictionary())


def _carry(body: Any, collidable: Any, place: np.ndarray, turn: np.ndarray) -> None:
    """Record that `body` carries `collidable`, and the offsets within it"""
    _CARRIED[collidable] = (body, place, turn)
    if _kind(collidable) == 'CollidableOffset' and collidable.collidable:
        inner = collidable.collidable
        inner_turn = quaternion(inner.rotation)
        _carry(body, inner,
               place + mathutil.quat_to_matrix(turn) @ np.asarray(inner.translation, dtype='d'),
               mathutil.quat_mul(turn, inner_turn))


def carrier(collidable: Any) -> Any:
    """The body carrying a collidable, or None"""
    found = _CARRIED.get(collidable)
    return None if found is None else found[0]


def pose_of(collidable: Any) -> tuple[np.ndarray, np.ndarray]:
    """Where a collidable's own frame is: its position and orientation (a quaternion)

    The carrying body's pose for a collidable a body carries; its own fields
    otherwise.
    """
    found = _CARRIED.get(collidable)
    if found is None:
        return np.asarray(collidable.translation, dtype='d'), quaternion(collidable.rotation)
    body, place, turn = found
    body_turn = quaternion(body.orientation)
    position = (np.asarray(body.position, dtype='d')
                + mathutil.quat_to_matrix(body_turn) @ place)
    return position, mathutil.quat_mul(body_turn, turn)


def _moving(collidable: Any) -> bool:
    """Whether a collidable is carried by a body that moves"""
    body = carrier(collidable)
    return body is not None and not body.fixed


# -- a CollisionSensor's touches -----------------------------------------
@dataclass
class Touch:
    """One point where two collidables meet

    The normal points from `first` toward `second`; `depth` is how far they
    overlap, in metres.
    """
    first: Any
    second: Any
    point: np.ndarray
    normal: np.ndarray
    depth: float


@dataclass
class _Placed:
    """A collidable's proxy, kept for as long as its shape and pose are the same"""
    shape: model.Shape
    pose: tuple[float, ...]
    proxy: Any


def detect(collection: Any, kept: Optional[dict[Any, _Placed]] = None) -> list[Touch]:
    """Where the collidables of a `CollisionCollection` touch, as they stand

    Two collidables of one body are not tested. `kept` holds each
    collidable's proxy between calls, rebuilt when its shape or its pose
    changes.
    """
    if kept is None:
        kept = {}
    placed: list[tuple[Any, Any]] = []
    for collidable, bounds in members(collection):
        parts = collidable_parts(collidable, _moving(collidable), bounds)
        if not parts:
            continue
        position, turn = pose_of(collidable)
        shape = parts[0].shape if len(parts) == 1 and not np.any(parts[0].position) \
            and np.allclose(parts[0].orientation, _LEVEL) else model.Shape.compound(parts)
        pose = tuple(float(value) for value in (*position, *turn))
        entry = kept.get(collidable)
        if entry is None or entry.shape is not shape or entry.pose != pose:
            entry = _Placed(shape, pose, make_proxy(shape, position, turn))
            kept[collidable] = entry
        placed.append((collidable, entry.proxy))
    for gone in [node for node in kept if node not in {found for found, _ in placed}]:
        del kept[gone]
    if len(placed) < 2:
        return []
    boxes = [proxy.aabb() for _, proxy in placed]
    low = np.array([box[0] for box in boxes])
    high = np.array([box[1] for box in boxes])
    touches: list[Touch] = []
    for i in range(len(placed)):
        near = np.nonzero(np.all(low[i + 1:] <= high[i], axis=1)
                          & np.all(high[i + 1:] >= low[i], axis=1))[0] + i + 1
        first, first_proxy = placed[i]
        for j in near.tolist():
            second, second_proxy = placed[j]
            body = carrier(first)
            if body is not None and body is carrier(second):
                continue
            for contact in collide(0, 1, first_proxy, second_proxy):
                if contact.depth > 0.0:
                    touches.append(Touch(first, second, np.asarray(contact.point),
                                         np.asarray(contact.normal), float(contact.depth)))
    return touches


# -- a RigidBodyCollection's world ---------------------------------------
@dataclass
class _Body:
    """One X3D body in the world"""
    node: Any
    index: int
    #: The centre of mass, in the body's frame.
    com: np.ndarray
    #: Every collidable the body carries, offsets' contents included.
    collidables: set[Any] = field(default_factory=set)
    #: The top-level collidables, drawn where the body is.
    carried: list[Any] = field(default_factory=list)
    #: The values last sent on the body's fields, by name.
    sent: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Joint:
    """One X3D joint in the world"""
    node: Any
    joint: Any
    kind: str
    #: The values last sent on the joint's outputs, by name.
    sent: dict[str, Any] = field(default_factory=dict)


#: Each joint's outputs, by X3D type.
JOINT_OUTPUTS = {
    'BallJoint': ('body1AnchorPoint', 'body2AnchorPoint'),
    'SingleAxisHingeJoint': ('angle', 'angleRate', 'body1AnchorPoint', 'body2AnchorPoint'),
    'DoubleAxisHingeJoint': ('body1AnchorPoint', 'body1Axis', 'body2AnchorPoint', 'body2Axis',
                             'hinge1Angle', 'hinge1AngleRate', 'hinge2Angle',
                             'hinge2AngleRate'),
    'SliderJoint': ('separation', 'separationRate'),
    'UniversalJoint': ('body1AnchorPoint', 'body1Axis', 'body2AnchorPoint', 'body2Axis'),
    'MotorJoint': ('motor1Angle', 'motor1AngleRate', 'motor2Angle', 'motor2AngleRate',
                   'motor3Angle', 'motor3AngleRate'),
}


def _floats(values: Any) -> tuple[float, ...]:
    """A field's value as a tuple of floats"""
    return tuple(float(value) for value in np.asarray(values, dtype='d').ravel())


def _suspension(force_mix: float, error_correction: float) -> tuple[float, float]:
    """The stiffness (N/m) and damping (N s/m) of a suspension X3D gives as ERP and CFM

    Read against :data:`NOMINAL_STEP`, as ODE reads them against its step.
    """
    if force_mix <= 0.0:
        return 0.0, 0.0
    erp = min(max(error_correction, 0.0), 1.0)
    return erp / (NOMINAL_STEP * force_mix), (1.0 - erp) / force_mix


def _damping(factor: float) -> float:
    """The damping rate (per second) that takes `factor` of a velocity each nominal step"""
    factor = min(max(float(factor), 0.0), 0.999)
    return -math.log1p(-factor) / NOMINAL_STEP


class RigidSystem:
    """A `RigidBodyCollection` simulated on omi_physics

    Built from the collection's nodes at the first :meth:`advance`, and again
    whenever what it is built from changes: the bodies, their geometry, mass
    and enabled state, the joints, the collider. Field values that change from
    frame to frame -- positions and velocities sent in, forces, torques,
    gravity, motor speeds -- are read every frame.
    """

    def __init__(self, collection: Any) -> None:
        self.collection = collection
        self.world: Optional[PhysicsWorld] = None
        self.bodies: list[_Body] = []
        self.joints: list[_Joint] = []
        #: World index -> the collidables there.
        self.held: dict[int, set[Any]] = {}
        #: Collidable -> the world index of its static body.
        self.free: dict[Any, int] = {}
        self._signature: Any = None
        self._waiting = 0.0
        self._collider: set[Any] = set()
        self._collider_parameters: Optional[model.ContactParameters] = None
        self._routed: dict[tuple[int, int], model.ContactParameters] = {}
        #: The `Contact` nodes sent to `set_contacts` since the last frame.
        self.contacts: list[Any] = []
        #: Static bodies standing for the world in contacts that name one body.
        self._surfaces: list[int] = []
        self._surfaces_used = 0

    # -- what the world is built from ------------------------------------
    def _bodies(self) -> list[Any]:
        """The collection's enabled bodies, each once"""
        found: list[Any] = []
        for node in self.collection.bodies:
            if node and _kind(node) == 'RigidBody' and node.enabled \
                    and not any(node is other for other in found):
                found.append(node)
        return found

    def _collidable_signature(self, collidable: Any, moving: bool) -> tuple[Any, ...]:
        """What a collidable's shapes are made from"""
        kind = _kind(collidable)
        if kind == 'CollidableOffset':
            inner = collidable.collidable
            return (collidable, collidable.enabled, inner,
                    None if not inner else _floats(inner.translation),
                    None if not inner else _floats(inner.rotation),
                    None if not inner else self._collidable_signature(inner, moving))
        shape = getattr(collidable, 'shape', None)
        geometry = getattr(shape, 'geometry', None)
        return (collidable, getattr(collidable, 'enabled', True), shape, geometry,
                geometry_shape(geometry, moving))

    def signature(self) -> tuple[Any, ...]:
        """Everything the world is built from"""
        bodies = []
        for body in self._bodies():
            density = body.massDensityModel
            moving = not body.fixed
            bodies.append((body, body.fixed, float(body.mass), _floats(body.centerOfMass),
                           _floats(body.inertia), density,
                           None if not density else geometry_shape(density, True),
                           tuple(self._collidable_signature(collidable, moving)
                                 for collidable in body.geometry if collidable)))
        joints = []
        for joint in self.collection.joints:
            if not joint:
                continue
            joints.append((joint, joint.body1, joint.body2,
                           *(_floats(getattr(joint, name)) for name in
                             ('anchorPoint', 'axis', 'axis1', 'axis2', 'motor1Axis',
                              'motor2Axis', 'motor3Axis') if hasattr(joint, name)),
                           getattr(joint, 'enabledAxes', None)))
        collider = self.collection.collider
        return (tuple(bodies), tuple(joints), collider,
                tuple((node, bounds, self._collidable_signature(node, False))
                      for node, bounds in members(collider)))

    # -- building ---------------------------------------------------------
    def build(self) -> None:
        """Make the world from the collection's nodes, as they stand"""
        for entry in self.bodies:
            for collidable in entry.collidables:
                if carrier(collidable) is entry.node:
                    del _CARRIED[collidable]
        self.world = world = PhysicsWorld(sleep_enabled=True)
        self.bodies, self.joints, self.held, self.free = [], [], {}, {}
        self._surfaces, self._surfaces_used = [], 0
        for node in self._bodies():
            self._add_body(world, node)
        for collidable, bounds in members(self.collection.collider):
            self._held_index(collidable, bounds)
        by_node = {entry.node: entry.index for entry in self.bodies}
        for node in self.collection.joints:
            if node:
                self._add_joint(world, node, by_node)
        world.set_pair_rule(self._rule)

    def _add_body(self, world: PhysicsWorld, node: Any) -> None:
        """Put one X3D body into the world"""
        moving = not node.fixed
        com = np.asarray(node.centerOfMass, dtype='d')
        parts: list[model.ShapePart] = []
        entry = _Body(node, -1, com)
        for collidable in node.geometry:
            if not collidable:
                continue
            entry.carried.append(collidable)
            for held in _inner_collidables(collidable):
                entry.collidables.add(held)
            _carry(node, collidable, np.zeros(3), _LEVEL.copy())
            for part in collidable_parts(collidable, moving):
                parts.append(model.ShapePart(part.shape,
                                             tuple(np.asarray(part.position) - com),
                                             part.orientation))
        shape = model.Shape.compound(parts) if parts else None
        motion = model.Motion(type=model.DYNAMIC if moving else model.STATIC,
                              mass=max(float(node.mass), 1e-9),
                              inertiaDiagonal=self._inertia(node, shape))
        collider = None
        if shape is not None:
            collider = model.Collider(shape=world.add_shape(shape))
        turn = quaternion(node.orientation)
        origin = np.asarray(node.position, dtype='d')
        entry.index = world.add_body(motion, collider=collider,
                                     position=origin + mathutil.quat_to_matrix(turn) @ com,
                                     orientation=turn, handle=node)
        self._set_velocity(entry, np.asarray(node.linearVelocity, dtype='d'),
                           np.asarray(node.angularVelocity, dtype='d'))
        entry.sent = {'position': _floats(node.position),
                      'orientation': _floats(node.orientation),
                      'linearVelocity': _floats(node.linearVelocity),
                      'angularVelocity': _floats(node.angularVelocity)}
        self.held[entry.index] = set(entry.collidables)
        self.bodies.append(entry)

    @staticmethod
    def _inertia(node: Any, shape: Optional[model.Shape]) -> tuple[float, float, float]:
        """The diagonal of a body's inertia: the field's, or worked out from its shapes

        X3D's default, the identity, asks for the inertia of the
        `massDensityModel`'s geometry where there is one, and of the body's
        own shapes otherwise. The products of inertia off the diagonal are
        not used.
        """
        given = _floats(node.inertia)
        mass = max(float(node.mass), 1e-9)
        if given == _IDENTITY_INERTIA or len(given) != 9:
            from omi_physics.massprops import inertia_diagonal  # noqa: PLC0415 beside its use
            density = node.massDensityModel
            source = (geometry_shape(density, True) if density else shape)
            if source is not None:
                diagonal = inertia_diagonal(source, mass)
                if diagonal.any():
                    return float(diagonal[0]), float(diagonal[1]), float(diagonal[2])
        return given[0], given[4], given[8]

    def _held_index(self, collidable: Any, bounds: bool = False) -> Optional[int]:
        """The world index of what holds a collidable, adding a static body for a free one"""
        for entry in self.bodies:
            if collidable in entry.collidables:
                return entry.index
        found = self.free.get(collidable)
        if found is not None:
            return found
        assert self.world is not None
        parts = collidable_parts(collidable, False, bounds)
        if not parts:
            return None
        world = self.world
        position, turn = pose_of(collidable)
        index = world.add_body(model.Motion(type=model.STATIC), collider=model.Collider(
            shape=world.add_shape(model.Shape.compound(parts))),
            position=position, orientation=turn, handle=collidable)
        self.free[collidable] = index
        self.held[index] = set(_inner_collidables(collidable))
        return index

    def _add_joint(self, world: PhysicsWorld, node: Any, by_node: dict[Any, int]) -> None:
        """Put one X3D joint into the world, where both its bodies are in it"""
        ends = []
        for body in (node.body1, node.body2):
            if not body:
                ends.append(-1)
            elif body in by_node:
                ends.append(by_node[body])
            else:
                return
        if ends == [-1, -1]:
            return
        a, b = ends
        kind = _kind(node)
        joint: Any
        if kind == 'BallJoint':
            joint = omi_joints.BallJoint(a, b, anchor=_floats(node.anchorPoint))
        elif kind == 'SingleAxisHingeJoint':
            joint = omi_joints.HingeJoint(a, b, anchor=_floats(node.anchorPoint),
                                          axis=_floats(node.axis))
        elif kind == 'DoubleAxisHingeJoint':
            joint = omi_joints.TwoAxisHingeJoint(a, b, anchor=_floats(node.anchorPoint),
                                                 axis1=_floats(node.axis1),
                                                 axis2=_floats(node.axis2))
        elif kind == 'SliderJoint':
            joint = omi_joints.SliderJoint(a, b, axis=_floats(node.axis))
        elif kind == 'UniversalJoint':
            joint = omi_joints.UniversalJoint(a, b, anchor=_floats(node.anchorPoint),
                                              axis1=_floats(node.axis1),
                                              axis2=_floats(node.axis2))
        elif kind == 'MotorJoint':
            count = min(max(int(node.enabledAxes), 0), 3)
            axes = [_floats(getattr(node, 'motor%dAxis' % (number + 1)))
                    for number in range(count)]
            joint = omi_joints.MotorJoint(a, b, axes=axes, torques=[0.0] * count)
        else:
            return
        entry = _Joint(node, joint, kind)
        self._joint_settings(entry)
        world.add_joint_constraint(joint)
        self.joints.append(entry)

    # -- each frame -------------------------------------------------------
    def _joint_settings(self, entry: _Joint) -> None:
        """Give an omi joint its X3D joint's stops, motors and forces as they are now"""
        node, joint, kind = entry.node, entry.joint, entry.kind
        joint.erp = float(self.collection.errorCorrection)
        joint.cfm = float(self.collection.constantForceMix)
        if kind == 'SingleAxisHingeJoint':
            low, high = float(node.minAngle), float(node.maxAngle)
            if low <= -math.pi and high >= math.pi:
                low, high = -math.inf, math.inf
            joint.stops = omi_joints.Stops(low, high, float(node.stopBounce),
                                            float(node.stopErrorCorrection))
        elif kind == 'DoubleAxisHingeJoint':
            low, high = float(node.minAngle1), float(node.maxAngle1)
            if low <= -math.pi and high >= math.pi:
                low, high = -math.inf, math.inf
            joint.stops1 = omi_joints.Stops(low, high, float(node.stop1Bounce),
                                             float(node.stop1ErrorCorrection),
                                             float(node.stop1ConstantForceMix))
            joint.motor1_speed = float(node.desiredAngularVelocity1)
            joint.motor1_torque = float(node.maxTorque1)
            joint.motor2_speed = float(node.desiredAngularVelocity2)
            joint.motor2_torque = float(node.maxTorque2)
            joint.suspension_stiffness, joint.suspension_damping = _suspension(
                float(node.suspensionForce), float(node.suspensionErrorCorrection))
        elif kind == 'SliderJoint':
            joint.stops = omi_joints.Stops(float(node.minSeparation),
                                            float(node.maxSeparation), float(node.stopBounce),
                                            float(node.stopErrorCorrection))
            joint.force = float(node.sliderForce)
        elif kind == 'MotorJoint':
            joint.torques = [float(getattr(node, 'axis%dTorque' % (number + 1)))
                             for number in range(len(joint.axes_world))]

    def _set_velocity(self, entry: _Body, linear: np.ndarray, angular: np.ndarray) -> None:
        """Set a body moving: `linear` is the velocity of its centre of mass"""
        assert self.world is not None
        world, index = self.world, entry.index
        if entry.node.fixed:
            return
        world.linear_velocity[index] = linear
        world.angular_velocity[index] = angular
        world.wake(index)

    def _read_inputs(self) -> None:
        """Apply what was sent to the bodies, and the settings read every frame"""
        world = self.world
        assert world is not None
        collection = self.collection
        gravity = np.asarray(collection.gravity, dtype='d')
        strength = float(np.linalg.norm(gravity))
        world.gravity = model.Gravity(gravity=strength, direction=tuple(
            gravity / strength if strength > 0.0 else (0.0, -1.0, 0.0)))
        for entry in self.bodies:
            node, index = entry.node, entry.index
            position, turn = _floats(node.position), _floats(node.orientation)
            if position != entry.sent['position'] or turn != entry.sent['orientation']:
                quat = quaternion(turn)
                world.place_body(index, np.asarray(position)
                                 + mathutil.quat_to_matrix(quat) @ entry.com, quat)
                entry.sent['position'], entry.sent['orientation'] = position, turn
                world.wake(index)
            linear, angular = _floats(node.linearVelocity), _floats(node.angularVelocity)
            if linear != entry.sent['linearVelocity'] or angular != entry.sent['angularVelocity']:
                self._set_velocity(entry, np.asarray(linear), np.asarray(angular))
                entry.sent['linearVelocity'], entry.sent['angularVelocity'] = linear, angular
            self._body_settings(entry)
        for collidable, index in self.free.items():
            placed, facing = pose_of(collidable)
            if np.any(world.position[index] != placed) or \
                    np.any(world.orientation[index] != facing):
                world.place_body(index, placed, facing)
        for joint in self.joints:
            self._joint_settings(joint)

    def _body_settings(self, entry: _Body) -> None:
        """A body's forces, damping, gravity, rotation and sleep, as its fields are now"""
        world, node, index = self.world, entry.node, entry.index
        assert world is not None
        if node.fixed:
            return
        force = np.asarray(node.forces, dtype='d').reshape(-1, 3).sum(axis=0)
        torque = np.asarray(node.torques, dtype='d').reshape(-1, 3).sum(axis=0)
        # Set only when changed: setting one wakes the body.
        if np.any(world.force[index] != force):
            world.set_force(index, force)
        if np.any(world.torque[index] != torque):
            world.set_torque(index, torque)
        world.gravity_factor[index] = 1.0 if node.useGlobalGravity else 0.0
        damped = bool(node.autoDamp)
        world.linear_damping[index] = _damping(node.linearDampingFactor) if damped else 0.0
        world.angular_damping[index] = _damping(node.angularDampingFactor) if damped else 0.0
        world.set_exact_rotation(index, bool(node.useFiniteRotation))
        source = node if node.autoDisable else self.collection
        if source.autoDisable:
            world.set_sleep(index, float(source.disableLinearSpeed),
                            float(source.disableAngularSpeed), float(source.disableTime))
        else:
            world.set_sleep(index, after=math.inf)

    def _solver_settings(self, step: float) -> None:
        """The collection's iterations, corrections and force mixing, as they are now"""
        world, collection = self.world, self.collection
        assert world is not None
        solver = world.contact_solver
        iterations = max(int(collection.iterations), 1)
        solver.velocity_iterations = iterations
        world.joint_iterations = iterations
        solver.correction = float(collection.errorCorrection)
        solver.softness = max(float(collection.constantForceMix), 0.0)
        solver.slop = max(float(collection.contactSurfaceThickness), 0.0)
        speed = float(collection.maxCorrectionSpeed)
        solver.max_correction = speed * step if speed > 0.0 else math.inf

    def _read_contacts(self) -> None:
        """The pairs the `Contact` nodes sent since the last frame name, and how they meet"""
        world = self.world
        assert world is not None
        collider = self.collection.collider
        self._collider = set()
        self._collider_parameters = None
        if collider and collider.enabled:
            self._collider = {node for node, _ in members(collider)}
            self._collider_parameters = contact_parameters(collider)
        routed: dict[tuple[int, int], model.ContactParameters] = {}
        by_body = {entry.node: entry.index for entry in self.bodies}
        for contact in self.contacts:
            if not contact:
                continue
            ends = []
            for body, geometry in ((contact.body1, contact.geometry1),
                                   (contact.body2, contact.geometry2)):
                found = by_body.get(body) if body else None
                if found is None and geometry:
                    found = self._held_index(geometry)
                ends.append(found)
            if ends[0] is None and ends[1] is None:
                continue
            if ends[0] is None or ends[1] is None:
                # A side that names nothing is the world: a surface through
                # the contact, solid on the far side of it from the body.
                normal = np.asarray(contact.contactNormal, dtype='d')
                surface = self._surface(np.asarray(contact.position, dtype='d'),
                                        normal if ends[1] is None else -normal)
                ends = [surface if end is None else end for end in ends]
            one, other = (int(end) for end in ends if end is not None)
            if one != other:
                routed[(one, other)] = contact_parameters(contact)
        self.contacts = []
        self._routed = routed
        for index in self._surfaces[self._surfaces_used:]:
            world.place_body(index, _PARKED)
        self._surfaces_used = 0

    def _surface(self, point: np.ndarray, into: np.ndarray) -> int:
        """A static body whose face passes through `point`, solid along `into`, for this frame"""
        world = self.world
        assert world is not None
        length = float(np.linalg.norm(into))
        into = into / length if length > 1e-12 else np.array([0.0, -1.0, 0.0])
        if self._surfaces_used < len(self._surfaces):
            index = self._surfaces[self._surfaces_used]
        else:
            index = world.add_body(model.Motion(type=model.STATIC), collider=model.Collider(
                shape=world.add_shape(model.Shape.box((2 * _SURFACE,) * 3))),
                position=_PARKED)
            self._surfaces.append(index)
            self.held[index] = set()
        self._surfaces_used += 1
        # The box's +y face is turned to face away from the solid.
        world.place_body(index, point + into * _SURFACE, _turn_onto((0.0, 1.0, 0.0), -into))
        return index

    def _rule(self, a: int, b: int) -> Any:
        """Whether, and how, the bodies at `a` and `b` meet this step"""
        found = self._routed.get((a, b))
        if found is not None:
            return found
        found = self._routed.get((b, a))
        if found is not None:
            return replace(found, surface_speed=(-found.surface_speed[0],
                                                 -found.surface_speed[1]))
        if self._collider_parameters is not None and \
                self.held.get(a, set()) & self._collider and \
                self.held.get(b, set()) & self._collider:
            return self._collider_parameters
        return False

    def advance(self, seconds: float) -> bool:
        """Step the collection by `seconds` and send what moved; whether anything is awake"""
        if not self.collection.enabled:
            return False
        signature = self.signature()
        if self.world is None or signature != self._signature:
            self.build()
            self._signature = signature
        world = self.world
        assert world is not None
        self._read_inputs()
        self._read_contacts()
        step = ACCURATE_STEP if self.collection.preferAccuracy else STEP
        self._solver_settings(step)
        self._waiting = min(self._waiting + max(float(seconds), 0.0), MAX_FRAME)
        while self._waiting >= step:
            world.step(step)
            self._waiting -= step
        self._send()
        return self.awake()

    def awake(self) -> bool:
        """Whether any body of the collection is moving"""
        world = self.world
        if world is None:
            return False
        return any(bool(world.awake[entry.index]) and not entry.node.fixed
                   for entry in self.bodies)

    # -- what is sent -----------------------------------------------------
    def _send(self) -> None:
        """Set each body's and joint's outputs where they changed"""
        world = self.world
        assert world is not None
        for entry in self.bodies:
            node = entry.node
            if not node.fixed:
                self._send_body(entry)
            for collidable in entry.carried:
                if _floats(collidable.translation) != entry.sent['position']:
                    collidable.translation = node.position
                if _floats(collidable.rotation) != entry.sent['orientation']:
                    collidable.rotation = node.orientation
        for joint in self.joints:
            self._send_joint(joint)

    def _send_body(self, entry: _Body) -> None:
        """Set a moving body's position, orientation and velocities where they changed"""
        world, node, index = self.world, entry.node, entry.index
        assert world is not None
        turn = np.asarray(world.orientation[index], dtype='d')
        arm = mathutil.quat_to_matrix(turn) @ entry.com
        spin = np.asarray(world.angular_velocity[index], dtype='d')
        values = {
            'position': np.asarray(world.position[index], dtype='d') - arm,
            'orientation': rotation(turn),
            'linearVelocity': np.asarray(world.linear_velocity[index], dtype='d'),
            'angularVelocity': spin,
        }
        for name, value in values.items():
            if _floats(value) != entry.sent[name]:
                setattr(node, name, value)
                entry.sent[name] = _floats(getattr(node, name))

    def _send_joint(self, entry: _Joint) -> None:
        """Set a joint's outputs that its `forceOutput` names"""
        names = [str(name) for name in entry.node.forceOutput]
        offered = JOINT_OUTPUTS[entry.kind]
        wanted = offered if 'ALL' in names else [name for name in offered if name in names]
        if not wanted:
            return
        values = self._joint_values(entry)
        for name in wanted:
            value = values.get(name)
            if value is None:
                continue
            flat = _floats(value)
            if flat != entry.sent.get(name):
                setattr(entry.node, name, value)
                entry.sent[name] = flat

    def _joint_values(self, entry: _Joint) -> dict[str, Any]:
        """Every output a joint offers, as the bodies stand"""
        world, joint, kind, node = self.world, entry.joint, entry.kind, entry.node
        found: dict[str, Any] = {}
        if hasattr(joint, 'anchor_a') and hasattr(joint, 'local_a'):
            found['body1AnchorPoint'] = joint.anchor_a(world)
            found['body2AnchorPoint'] = joint.anchor_b(world)
        if kind == 'SingleAxisHingeJoint':
            found['angle'] = joint.angle(world)
            found['angleRate'] = joint.angle_rate(world)
        elif kind in ('DoubleAxisHingeJoint', 'UniversalJoint'):
            found['body1Axis'] = joint.axis1(world)
            found['body2Axis'] = joint.axis2(world)
            if kind == 'DoubleAxisHingeJoint':
                found['hinge1Angle'] = joint.angle1(world)
                found['hinge1AngleRate'] = joint.angle1_rate(world)
                found['hinge2Angle'] = joint.angle2(world)
                found['hinge2AngleRate'] = joint.angle2_rate(world)
        elif kind == 'SliderJoint':
            found['separation'] = joint.separation(world)
            found['separationRate'] = joint.separation_rate(world)
        elif kind == 'MotorJoint':
            for number in range(len(joint.axes_world)):
                found['motor%dAngle' % (number + 1)] = (
                    joint.angle(world, number) if node.autoCalc
                    else float(getattr(node, 'axis%dAngle' % (number + 1))))
                found['motor%dAngleRate' % (number + 1)] = joint.angle_rate(world, number)
        return found


def contact_fields(touch: Touch, collection: Any) -> dict[str, Any]:
    """The fields of the `Contact` a `CollisionSensor` sends for one touch"""
    found = {
        'position': touch.point, 'contactNormal': touch.normal, 'depth': touch.depth,
        'geometry1': touch.first, 'geometry2': touch.second,
        'body1': carrier(touch.first), 'body2': carrier(touch.second),
    }
    for name in ('appliedParameters', 'bounce', 'minBounceSpeed', 'frictionCoefficients',
                 'surfaceSpeed', 'softnessConstantForceMix', 'softnessErrorCorrection'):
        found[name] = getattr(collection, name)
    found['slipCoefficients'] = collection.slipFactors
    return found


def touched(touches: Sequence[Touch]) -> list[Any]:
    """The collidables a set of touches involves, each once, in the order met"""
    found: list[Any] = []
    for touch in touches:
        for node in (touch.first, touch.second):
            if not any(node is other for other in found):
                found.append(node)
    return found

