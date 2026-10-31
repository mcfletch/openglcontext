"""X3D's RigidBodyPhysics on omi_physics, the deprecated omi engine -- no GL

:class:`OmiRigidSystem` is :class:`~OpenGLContext.physics.x3drigid.RigidSystem`
with its world an omi_physics :class:`~omi_physics.world.PhysicsWorld`, and
:class:`OmiSensing` finds a `CollisionSensor`'s touches with omi's narrow
phase. :func:`~OpenGLContext.physics.x3djolt.make_rigid_system` and
:func:`~OpenGLContext.physics.x3djolt.make_sensing` choose these where the
run's engine is ``'omi'``. Importing this module needs omi_physics, the
``omi-physics`` extra; it is deleted with the omi engine.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
from omi_physics import joints as omi_joints
from omi_physics import mathutil, model
from omi_physics.body import make_proxy
from omi_physics.collide import collide
from omi_physics.world import PhysicsWorld

from OpenGLContext.physics.omi_adapter import omi_shape
from OpenGLContext.physics.settings import default_backend
from OpenGLContext.physics.x3drigid import (
    _BODY_OUTPUTS, _PARKED, _SURFACE, ACCURATE_STEP, MAX_FRAME, MIN_SURFACE_THICKNESS, STEP, ContactRule,
    RigidSystem, Touch, _Body, _damping, _floats, _inner_collidables, _Joint, _key, _kept, _kind, _same,
    _suspension, _turn_onto, carrier, collidable_parts, members, pose_of, quaternion, single_shape,
)
from OpenGLContext.physics import x3drigid

__all__ = ['OmiRigidSystem', 'OmiSensing', 'omi_contact']


def omi_contact(rule: ContactRule) -> model.ContactParameters:
    """omi's contact parameters for a rule"""
    first, second = rule.frictions
    return model.ContactParameters(
        restitution=rule.restitution, bounce_speed=rule.bounce_speed,
        friction=first if first == second else (first, second),
        friction_direction=rule.friction_direction, surface_speed=rule.surface_speed,
        slip=rule.slip, softness=rule.softness, error_correction=rule.error_correction)


def _rotations(turns: np.ndarray) -> np.ndarray:
    """Unit quaternions (n, 4) as X3D rotations (n, 4), each angle in [0, pi]"""
    turns = turns / np.linalg.norm(turns, axis=1, keepdims=True)
    turns = np.where(turns[:, 3:4] < 0.0, -turns, turns)
    angle = 2.0 * np.arccos(np.clip(turns[:, 3], -1.0, 1.0))
    length = np.linalg.norm(turns[:, :3], axis=1)
    axis = np.divide(turns[:, :3], length[:, None], out=np.zeros((len(turns), 3)),
                     where=length[:, None] >= 1e-12)
    axis[length < 1e-12] = (0.0, 0.0, 1.0)
    angle[length < 1e-12] = 0.0
    return np.concatenate([axis, angle[:, None]], axis=1)



class OmiRigidSystem(RigidSystem):
    """A `RigidBodyCollection` simulated on an omi_physics world"""

    def __init__(self, collection: Any) -> None:
        super().__init__(collection)
        self.world: Optional[PhysicsWorld] = None
        #: omi's parameters for each rule, made once.
        self._omi_rules: dict[ContactRule, model.ContactParameters] = {}

    # -- building ---------------------------------------------------------
    def build(self) -> None:
        """Make the world from the collection's nodes, as they stand"""
        self._forget_carried()
        self.world = world = PhysicsWorld(sleep_enabled=True, backend=default_backend())
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
        world.set_pair_rule(self._omi_rule)

    def _add_body(self, world: PhysicsWorld, node: Any) -> None:
        """Put one X3D body into the world"""
        moving = not node.fixed
        entry, proxy = self._body_entry(node)
        com = entry.com
        shape = None if proxy is None else omi_shape(proxy)
        motion = model.Motion(type=model.DYNAMIC if moving else model.STATIC,
                              mass=max(float(node.mass), 1e-9),
                              inertiaDiagonal=self._inertia(node, proxy))
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
        entry.sent = {name: _kept(getattr(node, name)) for name in _BODY_OUTPUTS}
        self.held[entry.index] = set(entry.collidables)
        self.bodies.append(entry)


    def _held_index(self, collidable: Any, bounds: bool = False) -> Optional[int]:
        """The world index of what holds a collidable, adding a static body for a free one"""
        for entry in self.bodies:
            if collidable in entry.collidables:
                return entry.index
        found = self.free.get(collidable)
        if found is not None:
            return found
        assert self.world is not None
        proxy = single_shape(collidable_parts(collidable, False, bounds))
        if proxy is None:
            return None
        shape = omi_shape(proxy)
        world = self.world
        position, turn = pose_of(collidable)
        index = world.add_body(model.Motion(type=model.STATIC), collider=model.Collider(
            shape=world.add_shape(shape)),
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
            node, index, sent = entry.node, entry.index, entry.sent
            position, turn = node.position, node.orientation
            if not _same(position, sent['position']) or not _same(turn, sent['orientation']):
                quat = quaternion(turn)
                world.place_body(index, np.asarray(position, dtype='d')
                                 + mathutil.quat_to_matrix(quat) @ entry.com, quat)
                sent['position'], sent['orientation'] = _kept(position), _kept(turn)
                world.wake(index)
                entry.moved, entry.resting = True, False
            linear, angular = node.linearVelocity, node.angularVelocity
            if not _same(linear, sent['linearVelocity']) or \
                    not _same(angular, sent['angularVelocity']):
                self._set_velocity(entry, np.asarray(linear, dtype='d'),
                                   np.asarray(angular, dtype='d'))
                sent['linearVelocity'], sent['angularVelocity'] = _kept(linear), _kept(angular)
                entry.resting = False
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
        source = node if node.autoDisable else self.collection
        settings = (_key(node.forces), _key(node.torques), node.useGlobalGravity,
                    node.autoDamp, float(node.linearDampingFactor),
                    float(node.angularDampingFactor), node.useFiniteRotation,
                    source.autoDisable, float(source.disableLinearSpeed),
                    float(source.disableAngularSpeed), float(source.disableTime))
        if settings == entry.settings:
            return
        entry.settings = settings
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
        solver.slop = max(float(collection.contactSurfaceThickness), MIN_SURFACE_THICKNESS)
        speed = float(collection.maxCorrectionSpeed)
        solver.max_correction = speed * step if speed > 0.0 else math.inf

    def _omi_rule(self, a: int, b: int) -> Any:
        """Whether, and how, the bodies at `a` and `b` meet this step, in omi's terms"""
        rule = self._rule(a, b)
        if not isinstance(rule, ContactRule):
            return False
        found = self._omi_rules.get(rule)
        if found is None:
            found = self._omi_rules[rule] = omi_contact(rule)
        return found

    def _park_surfaces(self, unused: list[int]) -> None:
        """Move the surfaces no contact needs this frame out of the way"""
        assert self.world is not None
        for index in unused:
            self.world.place_body(index, _PARKED)

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
        """Set each body's and joint's outputs where they changed

        A body asleep since it was last sent sends nothing. The values are
        worked out for every moving body at once; a field is set only where
        its value differs from what it holds.
        """
        world = self.world
        assert world is not None
        awake = world.awake
        movers = [entry for entry in self.bodies
                  if not entry.node.fixed and not (entry.resting and not awake[entry.index])]
        if movers:
            rows = np.array([entry.index for entry in movers], dtype=np.intp)
            turns = np.asarray(world.orientation[rows], dtype='d')
            arms = np.einsum('nij,nj->ni', mathutil.quat_to_matrix(turns),
                             np.array([entry.com for entry in movers], dtype='d'))
            values = {
                'position': np.asarray(world.position[rows], dtype='d') - arms,
                'orientation': _rotations(turns),
                'linearVelocity': np.asarray(world.linear_velocity[rows], dtype='d'),
                'angularVelocity': np.asarray(world.angular_velocity[rows], dtype='d'),
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
                entry.resting = not awake[entry.index]
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




class OmiSensing:
    """A `CollisionSensor`'s touches found by omi's narrow phase

    Each collidable's omi proxy is kept between calls, rebuilt when its shape
    or its pose changes. Two collidables of one body are not tested.
    """

    def __init__(self) -> None:
        self.kept: dict[Any, tuple[Any, tuple[float, ...], Any]] = {}

    def detect(self, collection: Any) -> list[Touch]:
        """Where the collidables of a `CollisionCollection` touch, as they stand"""
        kept = self.kept
        placed: list[tuple[Any, Any]] = []
        for collidable, proxy, position, turn in x3drigid.placed_members(collection):
            pose = tuple(float(value) for value in (*position, *turn))
            entry = kept.get(collidable)
            if entry is None or entry[0] is not proxy or entry[1] != pose:
                entry = (proxy, pose, make_proxy(omi_shape(proxy), position, turn))
                kept[collidable] = entry
            placed.append((collidable, entry[2]))
        present = {found for found, _ in placed}
        for gone in [node for node in kept if node not in present]:
            del kept[gone]
        if len(placed) < 2:
            return []
        boxes = [omi_proxy.aabb() for _, omi_proxy in placed]
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
