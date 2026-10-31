"""X3D's RigidBodyPhysics on Jolt, through pyjoltphysics -- no GL

:class:`JoltRigidSystem` is :class:`~OpenGLContext.physics.x3drigid.RigidSystem`
with its world a pyjoltphysics world stepped in lockstep with the frame: the
same reading of the collection's nodes (bodies, collidables, joints, the
collider, the contacts sent to it), the same fields sent back, the steps run
by the Jolt world thread. :func:`make_rigid_system` makes the one the physics
engine of the run names (``OPENGLCONTEXT_PHYSICS_ENGINE``).

Where the two differ:

- what collides is decided as the omi system decides it, by the contact
  filter, once for each pair as it first touches; the answer holds until the
  pair parts;
- a pair meets with the collider's bounce and first friction coefficient, as
  each body's material, and a contact sent to ``set_contacts`` makes its pair
  meet with those too;
- the products of inertia off the diagonal are not used, as on omi;
- the collection's iterations, error correction, force mixing and surface
  thickness are Jolt's own; a body that may rest (``autoDisable``) rests by
  Jolt's sleep speeds and time rather than its own;
- a slider's force pushes its second body along the axis, and the first back,
  as a force each step.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
import pyjoltphysics as pj

from OpenGLContext.physics import x3drigid
from OpenGLContext.physics.engine import require_omi
from OpenGLContext.physics.joltengine import _shape_of, _vec3, axis_angles, default_threads
from OpenGLContext.physics.settings import default_engine
from OpenGLContext.physics.x3drigid import (
    _BODY_OUTPUTS, _PARKED, _SURFACE, ContactRule, _Body, _floats, _inner_collidables, _Joint, _kept, _kind, _same, _suspension,
    _turn_onto, collidable_parts, members, pose_of, quaternion, single_shape,
)

__all__ = ['JoltRigidSystem', 'make_rigid_system']


def make_rigid_system(collection: Any) -> x3drigid.RigidSystem:
    """The simulation of ``collection`` on the physics engine of the run

    Raises :class:`~OpenGLContext.physics.engine.EngineUnavailable` for the
    omi engine without omi_physics.
    """
    if default_engine() == 'jolt':
        return JoltRigidSystem(collection)
    require_omi('X3D RigidBodyCollection')
    from OpenGLContext.physics.x3domi import OmiRigidSystem  # noqa: PLC0415 omi_physics loads on use

    return OmiRigidSystem(collection)


def _matrix(turn: np.ndarray) -> np.ndarray:
    x, y, z, w = (float(v) for v in turn)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The quaternion turning by ``b`` then by ``a``, each ``(x, y, z, w)``."""
    ax, ay, az, aw = (float(v) for v in a)
    bx, by, bz, bw = (float(v) for v in b)
    return np.array([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz])


def _conjugate(turn: np.ndarray) -> np.ndarray:
    return np.array([-turn[0], -turn[1], -turn[2], turn[3]], dtype='d')


def _unit(values: Any) -> np.ndarray:
    vector = np.asarray(values, dtype='d')
    length = float(np.linalg.norm(vector))
    return vector / length if length > 1e-12 else vector


def _vector(values: Any, default: tuple[float, float, float]) -> np.ndarray:
    """A field's 3-vector, or ``default`` for a joint without that field."""
    return np.asarray(default if values is None else _floats(values), dtype='d')


class _Frames:
    """Where a joint's anchor and axes sit on each of its bodies, from the poses it was made at.

    ``ends`` are the world uids of X3D's body1 and body2 (0 for the world);
    each local value is in that body's frame, or the world's for an end of 0.
    """

    def __init__(self, ends: tuple[int, int], poses: dict[int, tuple[np.ndarray, np.ndarray]],
                 anchor: Any, axes: tuple[Any, Any], motor_axes: list[Any]) -> None:
        self.ends = ends
        self.start = [poses.get(end, (np.zeros(3), np.array([0.0, 0.0, 0.0, 1.0])))
                      for end in ends]
        point = _vector(anchor, (0.0, 0.0, 0.0))
        self.anchors = [_matrix(turn).T @ (point - position) for position, turn in self.start]
        self.axes = [_matrix(turn).T @ _unit(_vector(axis, (0.0, 1.0, 0.0)))
                     for (_position, turn), axis in zip(self.start, axes, strict=True)]
        self.motor_axes = [_unit(_vector(axis, (0.0, 0.0, 0.0))) for axis in motor_axes]


def _limits(low: float, high: float) -> Optional[tuple[float, float]]:
    if low <= -math.pi and high >= math.pi:
        return None
    return max(low, -math.pi), min(high, math.pi)


#: The least speed, in rad/s or m/s, at which a joint meeting its stop bounces off it.
STOP_BOUNCE_SPEED = 0.1
#: How near its stop, in radians or metres, a joint is read as having met it.
_STOP_REACH = 0.05


class _Stop:
    """A joint's stops, which it bounces off by its node's bounce field

    ``ends`` are the world uids of X3D's body1 and body2 (0 for the world);
    ``axis`` is in body1's frame, or the world's; ``sign`` turns the motion
    of body2 against body1 along the axis into the engine's joint reading.
    """

    __slots__ = ('anchor', 'axis', 'bounce', 'ends', 'jid', 'linear', 'limits', 'sign')

    def __init__(self, jid: int, ends: tuple[int, int], axis: np.ndarray, anchor: np.ndarray,
                 limits: tuple[float, float], sign: float, linear: bool, bounce: str) -> None:
        self.jid = jid
        self.ends = ends
        self.axis = axis
        #: The anchor in body1's frame, or the world's.
        self.anchor = anchor
        self.limits = limits
        self.sign = sign
        self.linear = linear
        #: The node's field holding the bounce.
        self.bounce = bounce


class JoltRigidSystem(x3drigid.RigidSystem):
    """A `RigidBodyCollection` simulated on a pyjoltphysics world."""

    def __init__(self, collection: Any) -> None:
        super().__init__(collection)
        self.jolt: Optional[pj.World] = None
        self._step = x3drigid.STEP
        #: The pyjoltphysics joint of each X3D joint entry, by the entry's place.
        self._joint_ids: list[int] = []
        #: Each body's last angles, for the joints' rates.
        self._angles: dict[int, dict[str, float]] = {}
        self._forces: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._gravity: Optional[tuple[float, ...]] = None
        #: Each body's material row, by world uid, which a routed contact's pair entry names.
        self._materials: dict[int, int] = {}
        #: Each slider's bodies (the second, then the first or 0), its axis in the first's
        #: frame, and its node, whose sliderForce pushes along the axis.
        self._sliders: list[tuple[int, int, np.ndarray, Any]] = []
        self._paired: dict[tuple[int, int], tuple[float, float]] = {}
        #: Each body's pose as it was added, by world uid, which its joints are measured from.
        self._origins: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        #: Each joint's anchor and axes on its bodies, by the entry's place.
        self._frames: list[_Frames] = []
        #: The joints with stops, and the node each reads its bounce from.
        self._stops: list[tuple[_Stop, Any]] = []
        #: Each moving body's mass and inertia diagonal, by world uid.
        self._masses: dict[int, tuple[float, np.ndarray]] = {}

    def signature(self) -> tuple[Any, ...]:
        """Everything the world is built from, with the world's own settings"""
        return (*super().signature(), bool(self.collection.preferAccuracy), self._world_settings())

    def _world_settings(self) -> tuple[float, float, float]:
        """Jolt's least bounce speed, sleep speed and time before sleep, from the collection

        The least bounce speed is the collider's ``minBounceSpeed`` where it
        applies ``BOUNCE``. Rest follows the collection's ``autoDisable``
        thresholds, or else those of the first body that rests by its own:
        Jolt holds one sleep speed and time for a world, and measures the
        speed of each body's furthest points against ``disableLinearSpeed``.
        X3D's 0 for a threshold is read as Jolt's own.
        """
        defaults = pj.WorldSettings()
        bounce = defaults.min_velocity_for_restitution
        collider = self.collection.collider
        if collider and collider.enabled:
            least = x3drigid.contact_parameters(collider).bounce_speed
            if least is not None:
                bounce = max(float(least), 0.0)
        source = self.collection
        if not source.autoDisable:
            source = next((body for body in self._bodies() if body.autoDisable), source)
        speed = float(source.disableLinearSpeed)
        after = float(source.disableTime)
        return (bounce, speed if speed > 0.0 else defaults.sleep_velocity,
                after if after > 0.0 else defaults.time_before_sleep)

    # -- building -----------------------------------------------------------
    def build(self) -> None:
        """Make the world from the collection's nodes, as they stand"""
        self._forget_carried()
        if self.jolt is not None:
            self.jolt.stop()
        self._step = x3drigid.ACCURATE_STEP if self.collection.preferAccuracy else x3drigid.STEP
        gravity = _vec3(self.collection.gravity)
        bounce, sleep_speed, sleep_after = self._world_settings()
        self.jolt = world = pj.World(pj.WorldSettings(
            tick_hz=1.0 / self._step, gravity=gravity, threads=default_threads(),
            penetration_slop=x3drigid.MIN_SURFACE_THICKNESS, min_velocity_for_restitution=bounce,
            sleep_velocity=sleep_speed, time_before_sleep=sleep_after))
        self._gravity = gravity
        self.bodies, self.joints, self.held, self.free = [], [], {}, {}
        self._joint_ids, self._angles, self._forces = [], {}, {}
        self._sliders = []
        self._surfaces, self._surfaces_used = [], 0
        self._materials, self._paired = {}, {}
        self._origins, self._frames = {}, []
        self._stops, self._masses = [], {}
        for node in self._bodies():
            self._add_jolt_body(node)
        for collidable, bounds in members(self.collection.collider):
            self._held_index(collidable, bounds)
        by_node = {entry.node: entry.index for entry in self.bodies}
        for node in self.collection.joints:
            if node:
                self._add_jolt_joint(node, by_node)
        world.set_contact_filter(self._verdict, recheck=True)
        world.flush()

    def _define_material(self) -> int:
        """A material of the collider's bounce and first friction coefficient, one for each body."""
        assert self.jolt is not None
        collider = self.collection.collider
        friction, restitution = 0.6, 0.0
        if collider:
            rule = x3drigid.contact_parameters(collider)
            friction, restitution = rule.frictions[0], rule.restitution
        return self.jolt.materials.define(friction=max(friction, 0.0),
                                          restitution=max(restitution, 0.0))

    def _verdict(self, a: int, b: int, point: Any, normal: Any, approach: float) -> bool:
        return self._rule(int(a), int(b)) is not False

    def _add_jolt_body(self, node: Any) -> None:
        """Put one X3D body into the world"""
        assert self.jolt is not None
        moving = not node.fixed
        entry, shape = self._body_entry(node)
        com = entry.com
        turn = quaternion(node.orientation)
        origin = np.asarray(node.position, dtype='d') + _matrix(turn) @ com
        material = self._define_material()
        values: dict[str, Any] = {
            'orientations': np.asarray(turn, dtype='d')[None], 'material': material,
            'flags': pj.BodyFlag.FILTER_CONTACTS,
        }
        if shape is None:
            # A body with no collidable is a mass the joints and forces move; it meets nothing.
            batch = pj.BodyBatch.spheres(origin[None], radius=0.01,
                                         motion=pj.MotionType.DYNAMIC if moving
                                         else pj.MotionType.STATIC,
                                         mass=max(float(node.mass), 1e-9), group=0, mask=0,
                                         **values)
        else:
            made = self.jolt.add_shape(_shape_of(shape, moving))
            # Jolt turns a body about its shapes' centre; the X3D body turns about its
            # centre of mass, which is the body's origin here.
            centre = self.jolt.shape_info(made).center_of_mass if moving else (0.0, 0.0, 0.0)
            batch = pj.BodyBatch.of_shape(
                origin[None], made, motion=pj.MotionType.DYNAMIC if moving else pj.MotionType.STATIC,
                mass=max(float(node.mass), 1e-9) if moving else 1.0,
                center_of_mass=tuple(-float(v) for v in centre), **values)
        (uid,), _seq = self.jolt.add_bodies(batch)
        entry.index = int(uid)
        entry.moved = True
        self._materials[int(uid)] = material
        self._origins[int(uid)] = (origin, turn)
        if moving:
            inertia = np.asarray(self._inertia(node, shape), dtype='d')
            self._masses[int(uid)] = (max(float(node.mass), 1e-9), inertia)
            self.jolt.set_motion([uid], inertia=np.diag(inertia))
            self.jolt.set_velocities([uid], np.asarray(node.linearVelocity, dtype='d'),
                                     np.asarray(node.angularVelocity, dtype='d'))
        entry.sent = {name: _kept(getattr(node, name)) for name in _BODY_OUTPUTS}
        self.held[entry.index] = set(entry.collidables)
        self.bodies.append(entry)

    def _held_index(self, collidable: Any, bounds: bool = False) -> Optional[int]:
        """The world uid of what holds a collidable, adding a static body for a free one"""
        for entry in self.bodies:
            if collidable in entry.collidables:
                return entry.index
        found = self.free.get(collidable)
        if found is not None:
            return found
        assert self.jolt is not None
        shape = single_shape(collidable_parts(collidable, False, bounds))
        if shape is None:
            return None
        position, turn = pose_of(collidable)
        material = self._define_material()
        (uid,), _seq = self.jolt.add_bodies(pj.BodyBatch.of_shape(
            np.asarray(position, dtype='d')[None], _shape_of(shape, False),
            motion=pj.MotionType.STATIC, orientations=np.asarray(turn, dtype='d')[None],
            material=material, flags=pj.BodyFlag.FILTER_CONTACTS))
        self.free[collidable] = int(uid)
        self._materials[int(uid)] = material
        self.held[int(uid)] = set(_inner_collidables(collidable))
        return int(uid)

    def _add_jolt_joint(self, node: Any, by_node: dict[Any, int]) -> None:
        """Put one X3D joint into the world, where both its bodies are in it"""
        assert self.jolt is not None
        ends = []
        for body in (node.body1, node.body2):
            if not body:
                ends.append(0)
            elif body in by_node:
                ends.append(by_node[body])
            else:
                return
        if ends == [0, 0]:
            return
        frames = _Frames((ends[0], ends[1]), self._origins, getattr(node, 'anchorPoint', None),
                         (getattr(node, 'axis1', getattr(node, 'axis', None)),
                          getattr(node, 'axis2', getattr(node, 'axis', None))),
                         [getattr(node, 'motor%dAxis' % (number + 1), (0.0, 0.0, 0.0))
                          for number in range(3)])
        # pyjoltphysics reads a joint as its first body against its second; X3D reads
        # body2 against body1.
        b, a = ends
        sign = 1.0
        if a == 0:
            a, b, sign = b, 0, -1.0
        kind = _kind(node)
        made: Optional[pj.Joint] = None
        stops: Optional[tuple[float, float]] = None
        if kind == 'BallJoint':
            made = pj.Joint.ball(a, b, anchor=_floats(node.anchorPoint))
        elif kind == 'SingleAxisHingeJoint' and not np.any(_floats(node.axis)):
            # A hinge with no axis holds only its anchor, as a ball does.
            made = pj.Joint.ball(a, b, anchor=_floats(node.anchorPoint))
        elif kind == 'SingleAxisHingeJoint':
            stops = _limits(float(node.minAngle), float(node.maxAngle))
            made = pj.Joint.hinge(a, b, anchor=_floats(node.anchorPoint), axis=_floats(node.axis),
                                  limits=stops)
        elif kind == 'DoubleAxisHingeJoint':
            stiffness, damping = _suspension(float(node.suspensionForce),
                                             float(node.suspensionErrorCorrection))
            mass = max(float(node.body2.mass), 1e-9) if node.body2 else 1.0
            suspension = None
            if stiffness > 0.0:
                suspension = (math.sqrt(stiffness / mass) / (2.0 * math.pi),
                              damping / (2.0 * math.sqrt(stiffness * mass)))
            stops = _limits(float(node.minAngle1), float(node.maxAngle1))
            made = pj.Joint.two_axis_hinge(
                a, b, anchor=_floats(node.anchorPoint), axis1=_floats(node.axis1),
                axis2=_floats(node.axis2), limits1=stops,
                motor1=self._motor(node.desiredAngularVelocity1, node.maxTorque1),
                motor2=self._motor(node.desiredAngularVelocity2, node.maxTorque2),
                suspension=suspension)
        elif kind == 'SliderJoint':
            low, high = float(node.minSeparation), float(node.maxSeparation)
            stops = (min(low, 0.0), max(high, 0.0)) if low <= high else None
            made = pj.Joint.slider(a, b, axis=_floats(node.axis), limits=stops)
            axis = np.asarray(_floats(node.axis), dtype='d')
            axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
            if b:
                turn = quaternion(node.body1.orientation)
                axis = _matrix(turn).T @ axis
            self._sliders.append((a, b, axis, node))
        elif kind == 'UniversalJoint':
            made = pj.Joint.universal(a, b, anchor=_floats(node.anchorPoint),
                                      axis1=_floats(node.axis1), axis2=_floats(node.axis2))
        elif kind == 'MotorJoint':
            count = min(max(int(node.enabledAxes), 0), 3)
            if count:
                axes = [_floats(getattr(node, 'motor%dAxis' % (number + 1)))
                        for number in range(count)]
                made = pj.Joint.motor(a, b, axes=axes, torques=[0.0] * count, collide=True)
        if made is None:
            return
        jid = self.jolt.add_joint(made)
        entry = _Joint(node, None, kind)
        self.joints.append(entry)
        self._joint_ids.append(int(jid))
        self._frames.append(frames)
        self._joint_settings(entry)
        if stops is not None:
            bounce = {'SingleAxisHingeJoint': 'stopBounce', 'SliderJoint': 'stopBounce',
                      'DoubleAxisHingeJoint': 'stop1Bounce'}[kind]
            self._stops.append((_Stop(int(jid), frames.ends, frames.axes[0], frames.anchors[0],
                                      stops, sign, kind == 'SliderJoint', bounce), node))

    @staticmethod
    def _motor(speed: Any, torque: Any) -> Optional[pj.Motor]:
        if float(torque) <= 0.0:
            return None
        return pj.Motor(pj.MotorMode.VELOCITY, float(speed), float(torque))

    # -- each frame -----------------------------------------------------------
    def _joint_settings(self, entry: _Joint) -> None:
        """Give a joint its X3D joint's motors as they are now"""
        if self.jolt is None:
            return
        jid = self._joint_ids[self.joints.index(entry)]
        node = entry.node
        if entry.kind == 'DoubleAxisHingeJoint':
            # A hinge's motor drives at no more than its maxTorque; at 0 it is off.
            for axis, speed, torque in ((4, node.desiredAngularVelocity1, node.maxTorque1),
                                        (5, node.desiredAngularVelocity2, node.maxTorque2)):
                torque = float(torque)
                self.jolt.set_joint_motors(
                    [jid], pj.MotorMode.VELOCITY if torque > 0.0 else pj.MotorMode.OFF,
                    float(speed), max(torque, 0.0), axis=axis)
        elif entry.kind == 'MotorJoint':
            for number in range(min(max(int(node.enabledAxes), 0), 3)):
                self.jolt.set_joint_motors([jid], pj.MotorMode.VELOCITY,
                                           float(getattr(node, 'axis%dTorque' % (number + 1))),
                                           axis=number)

    def _read_inputs(self) -> None:
        """Apply what was sent to the bodies, and the settings read every frame"""
        world = self.jolt
        assert world is not None
        gravity = _vec3(self.collection.gravity)
        if gravity != self._gravity:
            world.set_gravity(gravity)
            self._gravity = gravity
        for entry in self.bodies:
            node, uid, sent = entry.node, entry.index, entry.sent
            position, turn = node.position, node.orientation
            if not _same(position, sent['position']) or not _same(turn, sent['orientation']):
                quat = quaternion(turn)
                world.set_transforms([uid], (np.asarray(position, dtype='d')
                                             + _matrix(quat) @ entry.com)[None], quat[None])
                sent['position'], sent['orientation'] = _kept(position), _kept(turn)
                entry.moved, entry.resting = True, False
            linear, angular = node.linearVelocity, node.angularVelocity
            if not node.fixed and (not _same(linear, sent['linearVelocity'])
                                   or not _same(angular, sent['angularVelocity'])):
                world.set_velocities([uid], np.asarray(linear, dtype='d'),
                                     np.asarray(angular, dtype='d'))
                sent['linearVelocity'], sent['angularVelocity'] = _kept(linear), _kept(angular)
                entry.resting = False
            self._jolt_body_settings(entry)
        snapshot = world.latest()
        for collidable, uid in self.free.items():
            placed, facing = pose_of(collidable)
            row = None if snapshot is None else snapshot.rows.get(uid)
            if snapshot is None or row is None or np.any(np.asarray(snapshot.position[row]) != placed):
                world.set_transforms([uid], np.asarray(placed, dtype='d')[None],
                                     np.asarray(facing, dtype='d')[None])
        for joint in self.joints:
            self._joint_settings(joint)

    def _jolt_body_settings(self, entry: _Body) -> None:
        """A body's forces, damping and gravity, as its fields are now"""
        world, node = self.jolt, entry.node
        assert world is not None
        if node.fixed:
            return
        rests = bool(node.autoDisable or self.collection.autoDisable)
        settings = (x3drigid._key(node.forces), x3drigid._key(node.torques),
                    node.useGlobalGravity, node.autoDamp, float(node.linearDampingFactor),
                    float(node.angularDampingFactor), rests)
        if settings == entry.settings:
            return
        entry.settings = settings
        force = np.asarray(node.forces, dtype='d').reshape(-1, 3).sum(axis=0)
        torque = np.asarray(node.torques, dtype='d').reshape(-1, 3).sum(axis=0)
        if force.any() or torque.any():
            self._forces[entry.index] = (force, torque)
        else:
            self._forces.pop(entry.index, None)
        damped = bool(node.autoDamp)
        world.set_motion([entry.index],
                         linear_damping=x3drigid._damping(node.linearDampingFactor) if damped else 0.0,
                         angular_damping=(x3drigid._damping(node.angularDampingFactor)
                                          if damped else 0.0),
                         gravity_factor=1.0 if node.useGlobalGravity else 0.0)
        world.set_flags([entry.index], pj.BodyFlag.NO_SLEEP, not rests)

    def _park_surfaces(self, unused: list[int]) -> None:
        """Move the surfaces no contact needs this frame out of the way"""
        if self.jolt is not None:
            for uid in unused:
                self.jolt.set_transforms([uid], _PARKED[None], np.array([[0.0, 0.0, 0.0, 1.0]]))

    def _surface(self, point: np.ndarray, into: np.ndarray) -> int:
        """A static body whose face passes through `point`, solid along `into`, for this frame"""
        world = self.jolt
        assert world is not None
        length = float(np.linalg.norm(into))
        into = into / length if length > 1e-12 else np.array([0.0, -1.0, 0.0])
        if self._surfaces_used < len(self._surfaces):
            uid = self._surfaces[self._surfaces_used]
        else:
            material = self._define_material()
            (made,), _seq = world.add_bodies(pj.BodyBatch.boxes(
                _PARKED[None], size=(2 * _SURFACE,) * 3, motion=pj.MotionType.STATIC,
                material=material, flags=pj.BodyFlag.FILTER_CONTACTS))
            uid = int(made)
            self._surfaces.append(uid)
            self._materials[uid] = material
            self.held[uid] = set()
        self._surfaces_used += 1
        # The box's +y face is turned to face away from the solid.
        world.set_transforms([uid], (point + into * _SURFACE)[None],
                             np.asarray(_turn_onto((0.0, 1.0, 0.0), -into), dtype='d')[None])
        return uid

    def _pair(self, one: int, other: int, rule: ContactRule) -> None:
        """Have the bodies ``one`` and ``other`` meet with a contact's bounce and first friction."""
        assert self.jolt is not None
        first, second = self._materials.get(one), self._materials.get(other)
        if first is None or second is None:
            return
        values = (max(float(rule.frictions[0]), 0.0), max(float(rule.restitution), 0.0))
        key = (min(first, second), max(first, second))
        if self._paired.get(key) != values:
            self._paired[key] = values
            self.jolt.materials.pair(first, second, friction=values[0], restitution=values[1])

    def advance(self, seconds: float) -> bool:
        """Step the collection by `seconds` and send what moved; whether anything is awake"""
        if not self.collection.enabled:
            return False
        signature = self.signature()
        if self.jolt is None or signature != self._signature:
            self.build()
            self._signature = signature
        world = self.jolt
        assert world is not None
        self._read_inputs()
        self._read_contacts()
        self._waiting = min(self._waiting + max(float(seconds), 0.0), x3drigid.MAX_FRAME)
        while self._waiting >= self._step * (1.0 - 1e-9):
            for uid, (force, torque) in self._forces.items():
                world.add_forces([uid], force)
                world.add_torques([uid], torque)
            self._push_sliders()
            approach = self._approaches()
            world.run_ticks(1)
            if approach:
                self._bounce(approach)
            self._waiting = max(self._waiting - self._step, 0.0)
        self._send()
        return self.awake()

    def _motion(self, snapshot: pj.Snapshot, uid: int) -> Optional[tuple[np.ndarray, ...]]:
        """A body's position, turn, linear and angular velocity; None for the world"""
        row = snapshot.rows.get(uid) if uid else None
        if row is None:
            return None
        return (np.asarray(snapshot.position[row], dtype='d'),
                np.asarray(snapshot.orientation[row], dtype='d'),
                np.asarray(snapshot.linear_velocity[row], dtype='d'),
                np.asarray(snapshot.angular_velocity[row], dtype='d'))

    def _stop_rate(self, stop: _Stop, snapshot: pj.Snapshot) -> tuple[float, np.ndarray]:
        """How fast body2 moves against body1 along a stop's axis, and the axis in the world"""
        first, second = (self._motion(snapshot, end) for end in stop.ends)
        axis = stop.axis if first is None else _matrix(first[1]) @ stop.axis
        which = 2 if stop.linear else 3
        rate = 0.0
        if second is not None:
            rate += float(np.dot(second[which], axis))
        if first is not None:
            rate -= float(np.dot(first[which], axis))
        return rate, axis

    def _approaches(self) -> list[tuple[_Stop, float, float]]:
        """Each bouncing stop's joint, the speed it moves at and the bounce, before a step"""
        snapshot = None if self.jolt is None else self.jolt.latest()
        if snapshot is None:
            return []
        found = []
        for stop, node in self._stops:
            bounce = float(getattr(node, stop.bounce))
            if bounce > 0.0:
                found.append((stop, self._stop_rate(stop, snapshot)[0], min(bounce, 1.0)))
        return found

    def _bounce(self, approach: list[tuple[_Stop, float, float]]) -> None:
        """Send back each joint a step brought onto its stop, at its bounce times the speed it met it at

        Jolt's limits stop a joint dead; the bounce is set on the bodies'
        velocities for the next step, shared between them by how hard each is
        to move along the axis.
        """
        world = self.jolt
        assert world is not None
        snapshot = world.latest()
        if snapshot is None:
            return
        rows = snapshot.joints.rows
        for stop, before, bounce in approach:
            row = rows.get(stop.jid)
            if row is None:
                continue
            reading, toward = float(snapshot.joints.value[row]), stop.sign * before
            low, high = stop.limits
            if not ((toward > STOP_BOUNCE_SPEED and reading >= high - _STOP_REACH)
                    or (toward < -STOP_BOUNCE_SPEED and reading <= low + _STOP_REACH)):
                continue
            after, axis = self._stop_rate(stop, snapshot)
            wanted = -bounce * before
            # Already going back at least as fast: the step did not meet the stop.
            if (wanted - after) * before >= 0.0:
                continue
            self._send_back(stop, snapshot, axis, wanted - after)

    def _send_back(self, stop: _Stop, snapshot: pj.Snapshot, axis: np.ndarray, change: float) -> None:
        """Change how fast body2 moves against body1 along ``axis`` by ``change``"""
        assert self.jolt is not None
        first = self._motion(snapshot, stop.ends[0])
        anchor = stop.anchor if first is None else first[0] + _matrix(first[1]) @ stop.anchor
        shares = []
        for end, side in zip(stop.ends, (-1.0, 1.0), strict=True):
            motion, held = self._motion(snapshot, end), self._masses.get(end)
            if motion is None or held is None:
                continue
            mass, inertia = held
            arm = motion[0] - anchor
            if stop.linear:
                ease = 1.0 / mass
            else:
                along = _matrix(motion[1]).T @ axis
                across = arm - float(np.dot(arm, axis)) * axis
                ease = 1.0 / (float(np.dot(along * along, inertia)) + mass * float(np.dot(across, across)))
            shares.append((end, side, ease, motion, arm))
        total = sum(ease for _end, _side, ease, _motion, _arm in shares)
        for end, side, ease, motion, arm in shares:
            amount = side * change * ease / total
            if stop.linear:
                linear, angular = motion[2] + amount * axis, motion[3]
            else:
                angular = motion[3] + amount * axis
                linear = motion[2] + np.cross(amount * axis, arm)
            self.jolt.set_velocities([end], linear, angular)

    def _push_sliders(self) -> None:
        """Each slider's force along its axis, for the next step: the second body forward, the first back."""
        if not self._sliders:
            return
        world = self.jolt
        assert world is not None
        snapshot = world.latest()
        for body, frame, axis, node in self._sliders:
            push = float(node.sliderForce)
            if not push:
                continue
            along = axis
            if frame and snapshot is not None and frame in snapshot.rows:
                along = _matrix(np.asarray(snapshot.orientation[snapshot.rows[frame]], dtype='d')) @ axis
            world.add_forces([body], along * push)
            if frame:
                world.add_forces([frame], -along * push)

    def awake(self) -> bool:
        """Whether any body of the collection is moving"""
        snapshot = None if self.jolt is None else self.jolt.latest()
        if snapshot is None:
            return False
        rows = snapshot.rows
        return any(not entry.node.fixed and entry.index in rows
                   and bool(snapshot.awake[rows[entry.index]]) for entry in self.bodies)

    # -- what is sent -----------------------------------------------------------
    def _send(self) -> None:
        """Set each body's and joint's outputs where they changed"""
        snapshot = None if self.jolt is None else self.jolt.latest()
        if snapshot is None:
            return
        rows = snapshot.rows
        movers = [entry for entry in self.bodies if not entry.node.fixed and entry.index in rows
                  and not (entry.resting and not snapshot.awake[rows[entry.index]])]
        if movers:
            take = np.array([rows[entry.index] for entry in movers], dtype=np.intp)
            turns = np.asarray(snapshot.orientation[take], dtype='d')
            arms = np.array([_matrix(turn) @ entry.com for turn, entry in zip(turns, movers,
                                                                                strict=True)])
            values = {
                'position': np.asarray(snapshot.position[take], dtype='d') - arms,
                'orientation': axis_angles(turns),
                'linearVelocity': np.asarray(snapshot.linear_velocity[take], dtype='d'),
                'angularVelocity': np.asarray(snapshot.angular_velocity[take], dtype='d'),
            }
            for row, entry in enumerate(movers):
                node, sent = entry.node, entry.sent
                for name in _BODY_OUTPUTS:
                    value = values[name][row]
                    if not _same(value, sent[name]):
                        setattr(node, name, value)
                        sent[name] = _kept(getattr(node, name))
                        if name in ('position', 'orientation'):
                            entry.moved = True
                entry.resting = not bool(snapshot.awake[rows[entry.index]])
        for entry in self.bodies:
            if entry.moved:
                for collidable in entry.carried:
                    collidable.translation = entry.node.position
                    collidable.rotation = entry.node.orientation
                entry.moved = False
        for joint in self.joints:
            self._send_joint(joint)

    def _joint_values(self, entry: _Joint) -> dict[str, Any]:
        """Every output a joint offers, as the bodies stand"""
        found: dict[str, Any] = {}
        snapshot = None if self.jolt is None else self.jolt.latest()
        if snapshot is None:
            return found
        place = self.joints.index(entry)
        jid, frames = self._joint_ids[place], self._frames[place]
        poses = []
        for end, start in zip(frames.ends, frames.start, strict=True):
            row = snapshot.rows.get(end) if end else None
            if row is None:
                poses.append((start, np.zeros(3)) if end else
                             ((np.zeros(3), np.array([0.0, 0.0, 0.0, 1.0])), np.zeros(3)))
            else:
                poses.append(((np.asarray(snapshot.position[row], dtype='d'),
                               np.asarray(snapshot.orientation[row], dtype='d')),
                              np.asarray(snapshot.angular_velocity[row], dtype='d')))
        (first, spin1), (second, spin2) = poses
        kind = entry.kind
        if kind in ('BallJoint', 'SingleAxisHingeJoint', 'DoubleAxisHingeJoint', 'UniversalJoint'):
            found['body1AnchorPoint'] = first[0] + _matrix(first[1]) @ frames.anchors[0]
            found['body2AnchorPoint'] = second[0] + _matrix(second[1]) @ frames.anchors[1]
        if kind in ('DoubleAxisHingeJoint', 'UniversalJoint'):
            found['body1Axis'] = _matrix(first[1]) @ frames.axes[0]
            found['body2Axis'] = _matrix(second[1]) @ frames.axes[1]
        if kind == 'MotorJoint':
            # The turn of body2 against body1 since the joint was made, in the world's frame.
            turned = [_multiply(pose[1], _conjugate(np.asarray(start[1], dtype='d')))
                      for pose, start in zip((first, second), frames.start, strict=True)]
            drift = _multiply(turned[1], _conjugate(turned[0]))
            if drift[3] < 0.0:
                drift = -drift
            for number in range(min(max(int(entry.node.enabledAxes), 0), 3)):
                axis = _matrix(first[1]) @ (_matrix(frames.start[0][1]).T
                                            @ frames.motor_axes[number])
                angle = 2.0 * math.atan2(float(np.dot(drift[:3], axis)), float(drift[3]))
                found['motor%dAngle' % (number + 1)] = (
                    math.remainder(angle, 2.0 * math.pi) if entry.node.autoCalc
                    else float(getattr(entry.node, 'axis%dAngle' % (number + 1))))
                found['motor%dAngleRate' % (number + 1)] = float(np.dot(spin2 - spin1, axis))
        joints = snapshot.joints
        row = joints.rows.get(jid)
        if row is None:
            return found
        value, value2 = float(joints.value[row]), float(joints.value2[row])
        names = {'SingleAxisHingeJoint': (('angle', value),),
                 'DoubleAxisHingeJoint': (('hinge1Angle', value), ('hinge2Angle', value2)),
                 'SliderJoint': (('separation', value),)}.get(kind, ())
        last = self._angles.setdefault(jid, {})
        now = float(snapshot.time)
        then = last.get('time')
        for name, reading in names:
            found[name] = reading
            found[name + 'Rate'] = 0.0
            if name in last and then is not None and now > then:
                change = reading - last[name]
                if kind != 'SliderJoint':
                    change = (change + math.pi) % (2.0 * math.pi) - math.pi
                found[name + 'Rate'] = change / (now - then)
            last[name] = reading
        last['time'] = now
        return found


def make_sensing() -> Any:
    """What finds a `CollisionSensor`'s touches on the physics engine of the run

    An object whose ``detect(collection)`` gives the touches among a
    `CollisionCollection`'s collidables as they stand
    (:class:`JoltSensing`, or the omi engine's
    :class:`~OpenGLContext.physics.x3domi.OmiSensing`).
    """
    if default_engine() == 'jolt':
        return JoltSensing()
    require_omi('X3D CollisionSensor')
    from OpenGLContext.physics.x3domi import OmiSensing  # noqa: PLC0415 omi_physics loads on use

    return OmiSensing()


#: How far each collidable's shape is cast to find what it overlaps where it
#: stands, in metres; only what it overlaps at the start of the cast is a touch.
_PROBE = 1e-4


class _Sensed:
    """One collidable as a static body of a sensing world"""

    __slots__ = ('cast', 'pose', 'shape', 'uid')

    def __init__(self, uid: int, shape: Any, cast: Optional[int], pose: tuple[float, ...]) -> None:
        self.uid = uid
        self.shape = shape
        #: The shape id the collidable's shape is cast as; None for a shape with a mesh.
        self.cast = cast
        self.pose = pose


class JoltSensing:
    """A `CollisionSensor`'s touches, found by Jolt's narrow phase

    Each collidable is a static body of a pyjoltphysics world that is never
    stepped, moved where the collidable is before each :meth:`detect`. Each
    collidable's shape is then cast a short way (:data:`_PROBE`) from where
    it stands, and every body it overlaps at the start is a touch: one per
    touching pair, at the deepest point, with the normal from the collidable
    met first in the collection toward the other. Two collidables holding
    triangle meshes are not tested against each other: a mesh is not cast.
    """

    def __init__(self) -> None:
        self.world: Optional[pj.World] = None
        self.sensed: dict[Any, _Sensed] = {}

    def _world(self) -> pj.World:
        if self.world is None:
            self.world = pj.World(pj.WorldSettings(threads=1))
        return self.world

    def _place(self, collidable: Any, shape: Any, position: np.ndarray,
               turn: np.ndarray) -> _Sensed:
        """The collidable's body, made or moved to where it is"""
        world = self._world()
        pose = tuple(float(value) for value in (*position, *turn))
        entry = self.sensed.get(collidable)
        if entry is not None and entry.shape is not shape:
            world.remove_bodies([entry.uid])
            if entry.cast is not None:
                world.remove_shape(entry.cast)
            entry = None
        if entry is None:
            (uid,), _seq = world.add_bodies(pj.BodyBatch.of_shape(
                np.asarray(position, dtype='d')[None], _shape_of(shape, False),
                motion=pj.MotionType.STATIC, orientations=np.asarray(turn, dtype='d')[None]))
            cast = world.add_shape(_shape_of(shape, True)) if x3drigid.mesh_free(shape) else None
            entry = self.sensed[collidable] = _Sensed(int(uid), shape, cast, pose)
        elif entry.pose != pose:
            world.set_transforms([entry.uid], np.asarray(position, dtype='d')[None],
                                 np.asarray(turn, dtype='d')[None])
            entry.pose = pose
        return entry

    def detect(self, collection: Any) -> list[x3drigid.Touch]:
        """Where the collidables of a `CollisionCollection` touch, as they stand"""
        placed = [(collidable, self._place(collidable, shape, position, turn))
                  for collidable, shape, position, turn in x3drigid.placed_members(collection)]
        present = {collidable for collidable, _ in placed}
        gone = [node for node in self.sensed if node not in present]
        if gone and self.world is not None:
            self.world.remove_bodies([self.sensed[node].uid for node in gone])
            for node in gone:
                cast = self.sensed.pop(node).cast
                if cast is not None:
                    self.world.remove_shape(cast)
        if len(placed) < 2 or self.world is None:
            return []
        world = self.world
        world.flush()
        order = {entry.uid: place for place, (_node, entry) in enumerate(placed)}
        bodies = [x3drigid.carrier(collidable) for collidable, _ in placed]
        found: dict[tuple[int, int], x3drigid.Touch] = {}
        for place, (_collidable, entry) in enumerate(placed):
            if entry.cast is None:
                continue
            body = bodies[place]
            exclude = [other.uid for other_place, (_node, other) in enumerate(placed)
                       if other_place == place or (body is not None and bodies[other_place] is body)]
            x, y, z = entry.pose[:3]
            hits = world.sweep(entry.cast, (x, y, z), (x, y + _PROBE, z), entry.pose[3:],
                               pj.QueryFilter(exclude=exclude), all_hits=True)
            for hit in hits:
                other = order.get(hit.uid)
                if other is None or hit.fraction > 0.0 or hit.depth <= 0.0:
                    continue
                key = (min(place, other), max(place, other))
                if key in found:
                    continue
                # The hit's normal points from the body met toward the cast shape.
                normal = np.asarray(hit.normal, dtype='d')
                if place == key[0]:
                    normal = -normal
                found[key] = x3drigid.Touch(placed[key[0]][0], placed[key[1]][0],
                                            np.asarray(hit.point, dtype='d'), normal, float(hit.depth))
        return [found[key] for key in sorted(found)]
