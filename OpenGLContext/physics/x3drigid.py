"""X3D's RigidBodyPhysics, read from the nodes -- no GL

A `RigidBodyCollection` is a :class:`RigidSystem`: a physics world holding a
body for each enabled `RigidBody` of the collection, and a static body for
each collidable that is in no body but that the collection's `collider`, or a
`Contact` sent to its `set_contacts`, names. :meth:`RigidSystem.advance` steps
it by a frame's time, in fixed steps of :data:`STEP` seconds
(:data:`ACCURATE_STEP` where the collection prefers accuracy), and sends what
moved: each body's `position`, `orientation`, `linearVelocity` and
`angularVelocity`, the `translation` and `rotation` of the collidables a body
carries, and each joint's outputs its `forceOutput` names. This module reads
the nodes into the engine's own records; the world is
:class:`~OpenGLContext.physics.x3djolt.JoltRigidSystem`, which
:func:`~OpenGLContext.physics.x3djolt.make_rigid_system` makes.

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
they stand, without stepping anything
(:func:`~OpenGLContext.physics.x3djolt.make_sensing`).

A collidable carried by a body is drawn and collided where the body is: its
`translation` and `rotation` are the body's. A `CollidableOffset` places the
collidable it holds by that collidable's own `translation` and `rotation`, in
the body's frame. A collidable in no body is where its own fields put it.

Geometry becomes a :class:`~OpenGLContext.physics.proxy.Proxy` by its kind
(:func:`geometry_shape`): a `Box`, `Sphere`, `Cylinder` or `Cone` as itself,
any other geometry that has triangles as its mesh, which for a body that moves
is the mesh's convex hull. A collidable reached through a `CollisionSpace`
whose `useGeometry` is false collides as the box that bounds it. A body's
default inertia is its shapes' (:func:`OpenGLContext.physics.massprops.inertia_diagonal`).
"""
from __future__ import annotations

import math
import weakref
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Optional

import numpy as np
from vrml import cache, protofunctions
from vrml import node as vrml_node
from vrml.x3d import interpolation

from OpenGLContext.physics import massprops
from OpenGLContext.physics.proxy import Proxy

__all__ = ['ACCURATE_STEP', 'MAX_FRAME', 'MIN_SURFACE_THICKNESS', 'NOMINAL_STEP', 'STEP', 'ContactRule',
           'RigidSystem', 'ShapePart', 'Touch', 'collidable_parts', 'contact_parameters',
           'geometry_shape', 'members', 'shape_of_geometry']


#: The fixed step a collection is simulated in, in seconds.
STEP = 1.0 / 120.0
#: The step of a collection whose `preferAccuracy` is true.
ACCURATE_STEP = 1.0 / 240.0
#: The most time one frame advances a collection by, in seconds.
MAX_FRAME = 0.25
#: The least overlap, in metres, a resting contact keeps. A contact pushed
#: fully apart each step parts, falls back and meets again on the next, so a
#: `contactSurfaceThickness` below this is read as this.
MIN_SURFACE_THICKNESS = 0.005
#: The step X3D's per-step quantities are read against: the damping factors
#: and a suspension's force mixing and error correction.
NOMINAL_STEP = 1.0 / 60.0

_LEVEL = np.array([0.0, 0.0, 0.0, 1.0])
_IDENTITY_INERTIA = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
_SHAPE_KEY = 'x3drigid-proxy'
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




def turn_by(first: Any, second: Any) -> np.ndarray:
    """The quaternion turning by `second` then by `first`, each (x, y, z, w)"""
    return np.asarray(massprops._multiply(first, second), dtype='d')  # noqa: SLF001 the module's own quaternion product


# -- shapes ---------------------------------------------------------------
@dataclass(frozen=True)
class ShapePart:
    """One shape of a collidable or a body, placed in its frame"""
    shape: Proxy
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: A unit quaternion (x, y, z, w).
    orientation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)


def geometry_shape(geometry: Any, moving: bool) -> Optional[Proxy]:
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
        found: Optional[Proxy] = holder.data[0]
        return found
    shape = shape_of_geometry(geometry, moving)
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


def shape_of_geometry(geometry: Any, moving: bool) -> Optional[Proxy]:
    """The collision shape of an X3D geometry node, worked out afresh (:func:`geometry_shape`)"""
    kind = _kind(geometry)
    if kind == 'Box':
        return Proxy.box(tuple(float(value) for value in geometry.size))
    if kind == 'Sphere':
        return Proxy.sphere(float(geometry.radius))
    if kind == 'Cylinder':
        return Proxy.cylinder(height=float(geometry.height), radius=float(geometry.radius))
    if kind == 'Cone':
        return Proxy.cylinder(height=float(geometry.height), radius=float(geometry.bottomRadius),
                              radius_top=0.0)
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
        from OpenGLContext.physics.cooking import convex_hull  # noqa: PLC0415 cooking is read only for meshes
        hull, _faces = convex_hull(points[corners])
        return Proxy.convex(hull)
    return Proxy.trimesh(points, corners.reshape(-1, 3))


def collidable_parts(collidable: Any, moving: bool, bounds_only: bool = False) -> list[ShapePart]:
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
        matrix = massprops.rotation_matrix(turn)
        return [ShapePart(part.shape, _triple(place + matrix @ np.asarray(part.position)),
                          _quad(turn_by(turn, part.orientation)))
                for part in collidable_parts(inner, moving, bounds_only)]
    if kind != 'CollidableShape' or not collidable.shape:
        return []
    shape = geometry_shape(getattr(collidable.shape, 'geometry', None), moving)
    if shape is None:
        return []
    if bounds_only:
        low, high = massprops.bounds(shape)
        return [ShapePart(Proxy.box(tuple(high - low)), _triple(0.5 * (low + high)))]
    return [ShapePart(shape)]


def _triple(values: Any) -> tuple[float, float, float]:
    x, y, z = (float(value) for value in values)
    return x, y, z


def _quad(values: Any) -> tuple[float, float, float, float]:
    x, y, z, w = (float(value) for value in values)
    return x, y, z, w


def single_shape(parts: Sequence[ShapePart]) -> Optional[Proxy]:
    """One shape made of `parts`: the part's own where there is one, unmoved; None for none

    A lone shape at its body's origin stays itself rather than becoming a
    compound, so a box or a sphere keeps the engines' direct tests.
    """
    if not parts:
        return None
    if len(parts) == 1 and not any(parts[0].position) \
            and np.allclose(parts[0].orientation, _LEVEL):
        return parts[0].shape
    return Proxy.compound([(part.shape, part.position, part.orientation) for part in parts])


def mesh_free(proxy: Proxy) -> bool:
    """Whether a proxy holds no triangle mesh: whether it can be swept or cast"""
    if proxy.kind == 'trimesh':
        return False
    if proxy.kind == 'compound':
        return all(mesh_free(part) for part, _position, _turn in proxy.params['parts'])
    return True


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


# -- how a pair meets -----------------------------------------------------
@dataclass(frozen=True)
class ContactRule:
    """How two bodies meet: a `CollisionCollection`'s or a `Contact`'s parameters

    `restitution` is the bounce, applied at an approach of at least
    `bounce_speed` m/s (None for the engine's own threshold). `frictions` are
    the coefficients along the first and second friction directions, the
    first along `friction_direction` where one is given. `surface_speed`
    (m/s) and `slip` are along the same two directions. `softness` (force
    mixing) and `error_correction` are None where the collection's own apply.
    """
    restitution: float = 0.0
    bounce_speed: Optional[float] = None
    frictions: tuple[float, float] = (0.0, 0.0)
    friction_direction: Optional[tuple[float, float, float]] = None
    surface_speed: tuple[float, float] = (0.0, 0.0)
    slip: tuple[float, float] = (0.0, 0.0)
    softness: Optional[float] = None
    error_correction: Optional[float] = None

    def reversed(self) -> ContactRule:
        """The rule read from the other body: the surface moving the other way"""
        return replace(self, surface_speed=(-self.surface_speed[0], -self.surface_speed[1]))


def contact_parameters(source: Any) -> ContactRule:
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
        direction = _triple(source.frictionDirection)
    bounce = 'BOUNCE' in applied
    return ContactRule(
        restitution=float(source.bounce) if bounce else 0.0,
        bounce_speed=float(source.minBounceSpeed) if bounce else None,
        frictions=(first, second if 'FRICTION_COEFFICIENT-2' in applied else first),
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
               place + massprops.rotation_matrix(turn) @ np.asarray(inner.translation, dtype='d'),
               turn_by(turn, inner_turn))


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
                + massprops.rotation_matrix(body_turn) @ place)
    return position, turn_by(body_turn, turn)


def moving(collidable: Any) -> bool:
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


def placed_members(collection: Any) -> list[tuple[Any, Proxy, np.ndarray, np.ndarray]]:
    """Each collidable of a collection with its shape and where it is: (node, shape, position, turn)"""
    found = []
    for collidable, bounds in members(collection):
        shape = single_shape(collidable_parts(collidable, moving(collidable), bounds))
        if shape is not None:
            found.append((collidable, shape, *pose_of(collidable)))
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
    #: The values last sent on the body's fields, by name, as the fields hold them.
    sent: dict[str, np.ndarray] = field(default_factory=dict)
    #: Whether the body's collidables are to be moved to it on the next send.
    moved: bool = True
    #: Whether the body was asleep when it was last sent, and so sends nothing
    #: more until it wakes.
    resting: bool = False
    #: The fields :meth:`RigidSystem._body_settings` last applied.
    settings: Any = None


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


#: A body's outputs, each also an input.
_BODY_OUTPUTS = ('position', 'orientation', 'linearVelocity', 'angularVelocity')


def _kept(value: Any) -> np.ndarray:
    """A copy of a field's value, as a single-precision field holds it"""
    return np.array(value, dtype=np.float32).ravel()


def _same(value: Any, kept: np.ndarray) -> bool:
    """Whether a value is what :func:`_kept` kept"""
    return bool(np.array_equal(np.asarray(value, dtype=np.float32).ravel(), kept))


def _key(value: Any) -> bytes:
    """A field's value as bytes, to compare with what it was"""
    return np.asarray(value, dtype=np.float32).tobytes()


def _floats(values: Any) -> tuple[float, ...]:
    """A field's value as a tuple of floats"""
    return tuple(float(value) for value in np.asarray(values, dtype='d').ravel())


def joint_signature(joint: Any) -> tuple[Any, ...]:
    """What a joint is built from: its bodies, anchor, axes and motor axes"""
    return (joint, joint.body1, joint.body2,
            *(_key(getattr(joint, name)) for name in
              ('anchorPoint', 'axis', 'axis1', 'axis2', 'motor1Axis', 'motor2Axis', 'motor3Axis')
              if hasattr(joint, name)),
            getattr(joint, 'enabledAxes', None))


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
    """A `RigidBodyCollection` read from its nodes, for an engine's world to simulate

    The world is built from the collection's nodes at the first
    :meth:`advance`, and again whenever what it is built from changes
    (:meth:`signature`): the bodies, their geometry, centre of mass and
    enabled state, the joints' bodies, anchors and axes, the collider. Field
    values that change from frame to frame -- positions and velocities sent
    in, mass and inertia, forces, torques, gravity, motor speeds, stops, the
    collider's bounce and friction -- are read every frame. An engine's subclass provides :meth:`build`,
    :meth:`advance`, :meth:`awake`, :meth:`_held_index`, :meth:`_surface`,
    :meth:`_park_surfaces` and :meth:`_joint_values`.
    """

    def __init__(self, collection: Any) -> None:
        self.collection = collection
        self.bodies: list[_Body] = []
        self.joints: list[_Joint] = []
        #: World index -> the collidables there.
        self.held: dict[int, set[Any]] = {}
        #: Collidable -> the world index of its static body.
        self.free: dict[Any, int] = {}
        self._signature: Any = None
        self._waiting = 0.0
        self._collider: set[Any] = set()
        self._collider_parameters: Optional[ContactRule] = None
        self._routed: dict[tuple[int, int], ContactRule] = {}
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
                    None if not inner else _key(inner.translation),
                    None if not inner else _key(inner.rotation),
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
            bodies.append((body, body.fixed, _key(body.centerOfMass), density,
                           None if not density else geometry_shape(density, True),
                           tuple(self._collidable_signature(collidable, moving)
                                 for collidable in body.geometry if collidable)))
        joints = tuple(joint_signature(joint) for joint in self.collection.joints if joint)
        collider = self.collection.collider
        return (tuple(bodies), joints, collider,
                tuple((node, bounds, self._collidable_signature(node, False))
                      for node, bounds in members(collider)))

    def _forget_carried(self) -> None:
        """Let go of the collidables the bodies of the last build carried"""
        for entry in self.bodies:
            for collidable in entry.collidables:
                if carrier(collidable) is entry.node:
                    del _CARRIED[collidable]

    def _body_entry(self, node: Any) -> tuple[_Body, Optional[Proxy]]:
        """A body's entry, its collidables carried, and its shape about its centre of mass"""
        moving = not node.fixed
        com = np.asarray(node.centerOfMass, dtype='d')
        entry = _Body(node, -1, com)
        parts: list[ShapePart] = []
        for collidable in node.geometry:
            if not collidable:
                continue
            entry.carried.append(collidable)
            for held in _inner_collidables(collidable):
                entry.collidables.add(held)
            _carry(node, collidable, np.zeros(3), _LEVEL.copy())
            for part in collidable_parts(collidable, moving):
                parts.append(ShapePart(part.shape, _triple(np.asarray(part.position) - com),
                                       part.orientation))
        return entry, single_shape(parts)

    @staticmethod
    def _inertia(node: Any, shape: Optional[Proxy]) -> tuple[float, float, float]:
        """The diagonal of a body's inertia: the field's, or worked out from its shapes

        X3D's default, the identity, asks for the inertia of the
        `massDensityModel`'s geometry where there is one, and of the body's
        own shapes otherwise. The products of inertia off the diagonal are
        not used.
        """
        given = _floats(node.inertia)
        mass = max(float(node.mass), 1e-9)
        if given == _IDENTITY_INERTIA or len(given) != 9:
            density = node.massDensityModel
            source = (geometry_shape(density, True) if density else shape)
            if source is not None:
                diagonal = massprops.inertia_diagonal(source, mass)
                if diagonal.any():
                    return float(diagonal[0]), float(diagonal[1]), float(diagonal[2])
        return given[0], given[4], given[8]

    # -- contacts ---------------------------------------------------------
    def _read_contacts(self) -> None:
        """The pairs the `Contact` nodes sent since the last frame name, and how they meet"""
        collider = self.collection.collider
        self._collider = set()
        self._collider_parameters = None
        if collider and collider.enabled:
            self._collider = {node for node, _ in members(collider)}
            self._collider_parameters = contact_parameters(collider)
        routed: dict[tuple[int, int], ContactRule] = {}
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
                routed[(one, other)] = rule = contact_parameters(contact)
                self._pair(one, other, rule)
        self.contacts = []
        self._routed = routed
        self._park_surfaces(self._surfaces[self._surfaces_used:])
        self._surfaces_used = 0

    def _pair(self, one: int, other: int, rule: ContactRule) -> None:
        """Tell the world that the bodies `one` and `other` meet by `rule` over the next frame"""

    def _rule(self, a: int, b: int) -> ContactRule | bool:
        """How the bodies at `a` and `b` meet this step; False where they do not"""
        found = self._routed.get((a, b))
        if found is not None:
            return found
        found = self._routed.get((b, a))
        if found is not None:
            return found.reversed()
        if self._collider_parameters is not None and \
                self.held.get(a, set()) & self._collider and \
                self.held.get(b, set()) & self._collider:
            return self._collider_parameters
        return False

    # -- what an engine provides ------------------------------------------
    def build(self) -> None:
        """Make the world from the collection's nodes, as they stand"""
        raise NotImplementedError

    def advance(self, seconds: float) -> bool:
        """Step the collection by `seconds` and send what moved; whether anything is awake"""
        raise NotImplementedError

    def awake(self) -> bool:
        """Whether any body of the collection is moving"""
        raise NotImplementedError

    def _held_index(self, collidable: Any, bounds: bool = False) -> Optional[int]:
        """The world index of what holds a collidable, adding a static body for a free one"""
        raise NotImplementedError

    def _surface(self, point: np.ndarray, into: np.ndarray) -> int:
        """A static body whose face passes through `point`, solid along `into`, for this frame"""
        raise NotImplementedError

    def _park_surfaces(self, unused: list[int]) -> None:
        """Move the surfaces no contact needs this frame out of the way"""
        raise NotImplementedError

    def _joint_values(self, entry: _Joint) -> dict[str, Any]:
        """Every output a joint offers, as the bodies stand"""
        raise NotImplementedError

    # -- what is sent -----------------------------------------------------
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

    def joint_values(self, entry: _Joint) -> dict[str, Any]:
        """Every output the joint `entry` offers, by field name, as the bodies stand

        The values are what the joint's ``forceOutput`` would send; a rate
        is measured from the last call where the engine has no reading of it.
        """
        return self._joint_values(entry)
