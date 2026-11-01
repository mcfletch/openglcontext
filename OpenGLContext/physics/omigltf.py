"""The OMI glTF physics extensions of a document, read into the engine's own types.

``OMI_physics_shape``, ``OMI_physics_body``, ``OMI_physics_gravity`` and
``OMI_physics_joint`` describe a document's bodies. :func:`load_document`
reads their blocks into a :class:`PhysicsDocument`: shapes as
:class:`~OpenGLContext.physics.proxy.Proxy` objects, physics materials as
:class:`~OpenGLContext.physics.types.Material` and collision filters as
:class:`~OpenGLContext.physics.types.CollisionFilter`, with each node's body
under its node index. Field names are the extensions' own.

A ``convex`` or ``trimesh`` shape names a glTF mesh rather than carrying
points; it is a :class:`MeshShape`, and the scenery tracker builds it from the
triangles the node carrying the body draws
(:mod:`OpenGLContext.physics.colliders`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.records import Motion
from OpenGLContext.physics.types import CollisionFilter, Material

__all__ = ['SUPPORTED', 'BodyMotion', 'Collider', 'Gravity', 'Joint', 'JointAttach', 'JointDrive',
           'JointLimit', 'MeshShape', 'NodeBody', 'PhysicsDocument', 'Trigger', 'load_document']

#: The extensions :func:`load_document` reads.
SUPPORTED = ('OMI_physics_shape', 'OMI_physics_body', 'OMI_physics_gravity', 'OMI_physics_joint')

_Vec = tuple[float, ...]


def _floats(values: Any) -> _Vec:
    return tuple(float(v) for v in values)


@dataclass(frozen=True, slots=True)
class MeshShape:
    """A ``convex`` or ``trimesh`` shape (``kind``): the glTF ``mesh`` it names, -1 for none."""
    kind: str
    mesh: int = -1


@dataclass(frozen=True, slots=True)
class BodyMotion:
    """A body's ``motion`` block: its type, mass in kilograms, and starting motion."""
    type: str = 'dynamic'
    mass: float = 1.0
    centerOfMass: _Vec = (0.0, 0.0, 0.0)
    inertiaDiagonal: _Vec = (0.0, 0.0, 0.0)
    inertiaOrientation: _Vec = (0.0, 0.0, 0.0, 1.0)
    linearVelocity: _Vec = (0.0, 0.0, 0.0)
    angularVelocity: _Vec = (0.0, 0.0, 0.0)
    gravityFactor: float = 1.0

    def body(self) -> tuple[str, Motion]:
        """The kind of body this motion makes (``static``, ``dynamic``, ``kinematic``) and its motion."""
        kind = self.type if self.type in ('dynamic', 'kinematic') else 'static'
        return kind, Motion(float(self.mass), 0.0, 0.0, float(self.gravityFactor))


@dataclass(frozen=True, slots=True)
class Collider:
    """A body's ``collider`` block: indices of its shape, physics material and collision filter (-1 for none)."""
    shape: int = -1
    physicsMaterial: int = -1
    collisionFilter: int = -1


@dataclass(frozen=True, slots=True)
class Trigger:
    """A body's ``trigger`` block: the shape it senses with and its collision filter."""
    shape: int = -1
    collisionFilter: int = -1


@dataclass(frozen=True, slots=True)
class Gravity:
    """Document gravity, or a node's gravity volume: ``gravity`` in metres a second squared."""
    type: str = 'directional'
    gravity: float = 9.81
    direction: _Vec = (0.0, -1.0, 0.0)
    priority: int = 0
    replace: bool = False
    stop: bool = False
    center: _Vec = (0.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class JointLimit:
    """One limit of a joint over some of its linear and angular axes."""
    linearAxes: tuple[int, ...] = ()
    angularAxes: tuple[int, ...] = ()
    min: float = -math.inf
    max: float = math.inf
    stiffness: float = math.inf
    damping: float = 0.0


@dataclass(frozen=True, slots=True)
class JointDrive:
    """One drive of a joint: a motor or spring on one axis."""
    type: str = 'linear'
    mode: str = 'force'
    axis: int = 0
    maxForce: float = math.inf
    positionTarget: float | None = None
    velocityTarget: float | None = None
    stiffness: float = 0.0
    damping: float = 0.0


@dataclass(frozen=True, slots=True)
class Joint:
    """A ``physicsJoints`` entry: its limits and drives."""
    limits: tuple[JointLimit, ...] = ()
    drives: tuple[JointDrive, ...] = ()


@dataclass(frozen=True, slots=True)
class JointAttach:
    """A body's ``joint`` block: the joint, the node at its other end, and whether the two collide."""
    joint: int = -1
    connectedNode: int = -1
    enableCollision: bool = False


@dataclass(slots=True)
class NodeBody:
    """The OMI physics one glTF node carries; a block the node lacks is None."""
    motion: BodyMotion | None = None
    collider: Collider | None = None
    trigger: Trigger | None = None
    gravity: Gravity | None = None
    joint: JointAttach | None = None


@dataclass(slots=True)
class PhysicsDocument:
    """A document's shapes, materials, filters and joints, its gravity, and each node's body by node index."""
    shapes: list[Proxy | MeshShape] = field(default_factory=list)
    materials: list[Material] = field(default_factory=list)
    filters: list[CollisionFilter] = field(default_factory=list)
    joints: list[Joint] = field(default_factory=list)
    global_gravity: Gravity | None = None
    node_bodies: dict[int, NodeBody] = field(default_factory=dict)
    #: The proxy made for each shape index, where a node's own triangles made it.
    proxies: dict[int, Proxy] = field(default_factory=dict)


def _shape(entry: dict[str, Any]) -> Proxy | MeshShape:
    kind = entry['type']
    p = entry.get(kind, {})
    if kind == 'box':
        return Proxy.box(p.get('size', (1.0, 1.0, 1.0)))
    if kind == 'sphere':
        return Proxy.sphere(p.get('radius', 0.5))
    if kind == 'capsule':
        return Proxy.capsule(p.get('height', 1.0), p.get('radius', 0.5))
    if kind == 'cylinder':
        return Proxy.cylinder(p.get('height', 2.0), p.get('radiusBottom', 0.5),
                              p.get('radiusTop', 0.5))
    if kind in ('convex', 'trimesh'):
        return MeshShape(kind, int(p.get('mesh', -1)))
    raise ValueError('unknown OMI shape type %r' % (kind,))


def _material(d: dict[str, Any]) -> Material:
    return Material(staticFriction=float(d.get('staticFriction', 0.6)),
                    dynamicFriction=float(d.get('dynamicFriction', 0.6)),
                    restitution=float(d.get('restitution', 0.0)),
                    frictionCombine=str(d.get('frictionCombine', 'average')),
                    restitutionCombine=str(d.get('restitutionCombine', 'average')))


def _filter(d: dict[str, Any]) -> CollisionFilter:
    return CollisionFilter(
        collisionSystems=tuple(d.get('collisionSystems', ())),
        collideWithSystems=(tuple(d['collideWithSystems']) if 'collideWithSystems' in d else None),
        notCollideWithSystems=tuple(d.get('notCollideWithSystems', ())))


def _motion(d: dict[str, Any]) -> BodyMotion:
    return BodyMotion(
        type=str(d['type']), mass=float(d.get('mass', 1.0)),
        centerOfMass=_floats(d.get('centerOfMass', (0, 0, 0))),
        inertiaDiagonal=_floats(d.get('inertiaDiagonal', (0, 0, 0))),
        inertiaOrientation=_floats(d.get('inertiaOrientation', (0, 0, 0, 1))),
        linearVelocity=_floats(d.get('linearVelocity', (0, 0, 0))),
        angularVelocity=_floats(d.get('angularVelocity', (0, 0, 0))),
        gravityFactor=float(d.get('gravityFactor', 1.0)))


def _gravity(d: dict[str, Any]) -> Gravity:
    return Gravity(type=str(d.get('type', 'directional')), gravity=float(d.get('gravity', 9.81)),
                   direction=_floats(d.get('direction', (0, -1, 0))),
                   priority=int(d.get('priority', 0)), replace=bool(d.get('replace', False)),
                   stop=bool(d.get('stop', False)), center=_floats(d.get('center', (0, 0, 0))))


def _joint(d: dict[str, Any]) -> Joint:
    limits = tuple(JointLimit(
        linearAxes=tuple(limit.get('linearAxes', ())), angularAxes=tuple(limit.get('angularAxes', ())),
        min=float(limit.get('min', -math.inf)), max=float(limit.get('max', math.inf)),
        stiffness=float(limit.get('stiffness', math.inf)), damping=float(limit.get('damping', 0.0)))
        for limit in d.get('limits', ()))
    drives = tuple(JointDrive(
        type=str(drive.get('type', 'linear')), mode=str(drive.get('mode', 'force')),
        axis=int(drive.get('axis', 0)), maxForce=float(drive.get('maxForce', math.inf)),
        positionTarget=drive.get('positionTarget'), velocityTarget=drive.get('velocityTarget'),
        stiffness=float(drive.get('stiffness', 0.0)), damping=float(drive.get('damping', 0.0)))
        for drive in d.get('drives', ()))
    return Joint(limits, drives)


def _node_body(ext: dict[str, Any]) -> NodeBody | None:
    body = ext.get('OMI_physics_body')
    gravity = ext.get('OMI_physics_gravity')
    if not body and not gravity:
        return None
    found = NodeBody()
    if body:
        if 'motion' in body:
            found.motion = _motion(body['motion'])
        if 'collider' in body:
            given = body['collider']
            found.collider = Collider(int(given.get('shape', -1)),
                                      int(given.get('physicsMaterial', -1)),
                                      int(given.get('collisionFilter', -1)))
        if 'trigger' in body:
            given = body['trigger']
            found.trigger = Trigger(int(given.get('shape', -1)), int(given.get('collisionFilter', -1)))
        if 'joint' in body:
            given = body['joint']
            found.joint = JointAttach(int(given.get('joint', -1)), int(given.get('connectedNode', -1)),
                                      bool(given.get('enableCollision', False)))
    if gravity:
        found.gravity = _gravity(gravity)
    return found


def load_document(gltf: dict[str, Any]) -> PhysicsDocument:
    """The OMI physics blocks of a glTF JSON dictionary (``extensions`` and ``nodes``) as a document.

    Raises ValueError for a shape of a type the extension does not define.
    """
    document = PhysicsDocument()
    top = gltf.get('extensions') or {}
    for entry in (top.get('OMI_physics_shape') or {}).get('shapes', ()):
        document.shapes.append(_shape(entry))
    bodies = top.get('OMI_physics_body') or {}
    document.materials.extend(_material(entry) for entry in bodies.get('physicsMaterials', ()))
    document.filters.extend(_filter(entry) for entry in bodies.get('collisionFilters', ()))
    joints = top.get('OMI_physics_joint') or {}
    document.joints.extend(_joint(entry) for entry in joints.get('physicsJoints', ()))
    if top.get('OMI_physics_gravity'):
        document.global_gravity = _gravity(top['OMI_physics_gravity'])
    for index, node in enumerate(gltf.get('nodes') or ()):
        found = _node_body(node.get('extensions') or {})
        if found is not None:
            document.node_bodies[index] = found
    return document
