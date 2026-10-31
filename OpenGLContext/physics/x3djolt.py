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
- a body's inertia is its shapes', scaled to its mass;
- the collection's iterations, error correction, force mixing and surface
  thickness, and the bodies' sleep speeds, are Jolt's own;
- a slider's force pushes its second body along the axis, and the first back,
  as a force each step.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
import pyjoltphysics as pj

from OpenGLContext.physics import x3drigid
from OpenGLContext.physics.joltengine import _shape_of, axis_angles, default_threads
from OpenGLContext.physics.omi_adapter import proxy_from_shape
from OpenGLContext.physics.settings import default_engine
from OpenGLContext.physics.x3drigid import (
    _BODY_OUTPUTS, _CARRIED, _LEVEL, JOINT_OUTPUTS, _Body, _carry, _floats, _inner_collidables,
    _Joint, _kept, _kind, _same, _suspension, collidable_parts, members, pose_of, quaternion,
    single_shape,
)

__all__ = ['JoltRigidSystem', 'make_rigid_system']


def make_rigid_system(collection: Any) -> x3drigid.RigidSystem:
    """The simulation of ``collection`` on the physics engine of the run."""
    if default_engine() == 'jolt':
        return JoltRigidSystem(collection)
    return x3drigid.RigidSystem(collection)


def _matrix(turn: np.ndarray) -> np.ndarray:
    x, y, z, w = (float(v) for v in turn)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _limits(low: float, high: float) -> Optional[tuple[float, float]]:
    if low <= -math.pi and high >= math.pi:
        return None
    return max(low, -math.pi), min(high, math.pi)


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

    def signature(self) -> tuple[Any, ...]:
        return (*super().signature(), bool(self.collection.preferAccuracy))

    # -- building -----------------------------------------------------------
    def build(self) -> None:
        """Make the world from the collection's nodes, as they stand"""
        for entry in self.bodies:
            for collidable in entry.collidables:
                if x3drigid.carrier(collidable) is entry.node:
                    del _CARRIED[collidable]
        if self.jolt is not None:
            self.jolt.stop()
        self._step = x3drigid.ACCURATE_STEP if self.collection.preferAccuracy else x3drigid.STEP
        gravity = tuple(float(v) for v in self.collection.gravity)
        self.jolt = world = pj.World(pj.WorldSettings(
            tick_hz=1.0 / self._step, gravity=gravity, threads=default_threads(),
            penetration_slop=x3drigid.MIN_SURFACE_THICKNESS))
        self._gravity = gravity
        self.world = None
        self.bodies, self.joints, self.held, self.free = [], [], {}, {}
        self._joint_ids, self._angles, self._forces = [], {}, {}
        self._sliders = []
        self._surfaces, self._surfaces_used = [], 0
        self._materials, self._paired = {}, {}
        for node in self._bodies():
            self._add_jolt_body(node)
        for collidable, bounds in members(self.collection.collider):
            self._held_index(collidable, bounds)
        by_node = {entry.node: entry.index for entry in self.bodies}
        for node in self.collection.joints:
            if node:
                self._add_jolt_joint(node, by_node)
        world.set_contact_filter(self._verdict, recheck=True)

    def _define_material(self) -> int:
        """A material of the collider's bounce and first friction coefficient, one for each body."""
        assert self.jolt is not None
        collider = self.collection.collider
        friction, restitution = 0.6, 0.0
        if collider:
            parameters = x3drigid.contact_parameters(collider)
            given = parameters.friction
            friction = float(given[0] if isinstance(given, tuple) else given)
            restitution = float(parameters.restitution)
        return self.jolt.materials.define(friction=max(friction, 0.0),
                                          restitution=max(restitution, 0.0))

    def _verdict(self, a: int, b: int, point: Any, normal: Any, approach: float) -> bool:
        return self._rule(int(a), int(b)) is not False

    def _add_jolt_body(self, node: Any) -> None:
        """Put one X3D body into the world"""
        assert self.jolt is not None
        moving = not node.fixed
        com = np.asarray(node.centerOfMass, dtype='d')
        parts = []
        entry = _Body(node, -1, com)
        for collidable in node.geometry:
            if not collidable:
                continue
            entry.carried.append(collidable)
            for held in _inner_collidables(collidable):
                entry.collidables.add(held)
            _carry(node, collidable, np.zeros(3), _LEVEL.copy())
            for part in collidable_parts(collidable, moving):
                parts.append(type(part)(part.shape, tuple(np.asarray(part.position) - com),
                                        part.orientation))
        shape = single_shape(parts)
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
            made = _shape_of(proxy_from_shape(shape), moving)
            batch = pj.BodyBatch.of_shape(
                origin[None], made, motion=pj.MotionType.DYNAMIC if moving else pj.MotionType.STATIC,
                mass=max(float(node.mass), 1e-9) if moving else 1.0, **values)
        (uid,), _seq = self.jolt.add_bodies(batch)
        entry.index = int(uid)
        self._materials[int(uid)] = material
        if moving:
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
            np.asarray(position, dtype='d')[None], _shape_of(proxy_from_shape(shape), False),
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
        # pyjoltphysics reads a joint as its first body against its second; X3D reads
        # body2 against body1.
        b, a = ends
        if a == 0:
            a, b = b, 0
        kind = _kind(node)
        made: Optional[pj.Joint] = None
        if kind == 'BallJoint':
            made = pj.Joint.ball(a, b, anchor=_floats(node.anchorPoint))
        elif kind == 'SingleAxisHingeJoint':
            made = pj.Joint.hinge(a, b, anchor=_floats(node.anchorPoint), axis=_floats(node.axis),
                                  limits=_limits(float(node.minAngle), float(node.maxAngle)))
        elif kind == 'DoubleAxisHingeJoint':
            stiffness, damping = _suspension(float(node.suspensionForce),
                                             float(node.suspensionErrorCorrection))
            mass = max(float(node.body2.mass), 1e-9) if node.body2 else 1.0
            suspension = None
            if stiffness > 0.0:
                suspension = (math.sqrt(stiffness / mass) / (2.0 * math.pi),
                              damping / (2.0 * math.sqrt(stiffness * mass)))
            made = pj.Joint.two_axis_hinge(
                a, b, anchor=_floats(node.anchorPoint), axis1=_floats(node.axis1),
                axis2=_floats(node.axis2),
                limits1=_limits(float(node.minAngle1), float(node.maxAngle1)),
                motor1=self._motor(node.desiredAngularVelocity1, node.maxTorque1),
                motor2=self._motor(node.desiredAngularVelocity2, node.maxTorque2),
                suspension=suspension)
        elif kind == 'SliderJoint':
            low, high = float(node.minSeparation), float(node.maxSeparation)
            limits = (min(low, 0.0), max(high, 0.0)) if low <= high else None
            made = pj.Joint.slider(a, b, axis=_floats(node.axis), limits=limits)
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
        self._joint_settings(entry)

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
            self.jolt.set_joint_motors([jid], pj.MotorMode.VELOCITY,
                                       float(node.desiredAngularVelocity1),
                                       float(node.maxTorque1) or math.inf, axis=4)
            self.jolt.set_joint_motors([jid], pj.MotorMode.VELOCITY,
                                       float(node.desiredAngularVelocity2),
                                       float(node.maxTorque2) or math.inf, axis=5)
        elif entry.kind == 'MotorJoint':
            for number in range(min(max(int(node.enabledAxes), 0), 3)):
                self.jolt.set_joint_motors([jid], pj.MotorMode.VELOCITY,
                                           float(getattr(node, 'axis%dTorque' % (number + 1))),
                                           axis=number)

    def _read_inputs(self) -> None:
        """Apply what was sent to the bodies, and the settings read every frame"""
        world = self.jolt
        assert world is not None
        gravity = tuple(float(v) for v in self.collection.gravity)
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
            if row is None or np.any(np.asarray(snapshot.position[row]) != placed):
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
        settings = (x3drigid._key(node.forces), x3drigid._key(node.torques),
                    node.useGlobalGravity, node.autoDamp, float(node.linearDampingFactor),
                    float(node.angularDampingFactor))
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

    def _read_contacts(self) -> None:
        """The pairs the `Contact` nodes sent since the last frame name"""
        collider = self.collection.collider
        self._collider = set()
        self._collider_parameters = None
        if collider and collider.enabled:
            self._collider = {node for node, _ in members(collider)}
            self._collider_parameters = x3drigid.contact_parameters(collider)
        routed = {}
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
            if ends[0] is not None and ends[1] is not None and ends[0] != ends[1]:
                routed[(int(ends[0]), int(ends[1]))] = parameters = x3drigid.contact_parameters(contact)
                self._pair(int(ends[0]), int(ends[1]), parameters)
        self.contacts = []
        self._routed = routed

    def _pair(self, one: int, other: int, parameters: Any) -> None:
        """Have the bodies ``one`` and ``other`` meet with a contact's bounce and friction."""
        assert self.jolt is not None
        first, second = self._materials.get(one), self._materials.get(other)
        if first is None or second is None:
            return
        given = parameters.friction
        friction = max(float(given[0] if isinstance(given, tuple) else given), 0.0)
        values = (friction, max(float(parameters.restitution), 0.0))
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
            world.run_ticks(1)
            self._waiting = max(self._waiting - self._step, 0.0)
        self._send()
        return self.awake()

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
        """The outputs a joint offers that the world's joint rows give, with their rates"""
        found: dict[str, Any] = {}
        snapshot = None if self.jolt is None else self.jolt.latest()
        if snapshot is None:
            return found
        jid = self._joint_ids[self.joints.index(entry)]
        joints = snapshot.joints
        row = joints.rows.get(jid)
        if row is None:
            return found
        value, value2 = float(joints.value[row]), float(joints.value2[row])
        names = {'SingleAxisHingeJoint': (('angle', value),),
                 'DoubleAxisHingeJoint': (('hinge1Angle', value), ('hinge2Angle', value2)),
                 'SliderJoint': (('separation', value),)}.get(entry.kind, ())
        last = self._angles.setdefault(jid, {})
        now = float(snapshot.time)
        then = last.get('time')
        for name, reading in names:
            found[name] = reading
            if name in last and then is not None and now > then:
                change = reading - last[name]
                if entry.kind != 'SliderJoint':
                    change = (change + math.pi) % (2.0 * math.pi) - math.pi
                found[name + 'Rate'] = change / (now - then)
            last[name] = reading
        last['time'] = now
        return {name: value for name, value in found.items()
                if name in JOINT_OUTPUTS.get(entry.kind, ())}
