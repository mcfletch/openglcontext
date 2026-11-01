"""Ragdolls: a skeleton of bodies joined by swing-twist joints, and the handle a game drives one by.

A :class:`RagdollSpec` lists the bones parents first. Each bone is a body
whose frame is its joint's frame: its ``translation`` and ``rotation`` are
the rest pose in the parent joint's frame (the root's in the ragdoll's own
frame), as a glTF node's are, and its collision shape is a capsule of
``radius`` from the joint along ``axis`` for ``length`` metres. A joint's
limits are a twist about the bone and a swing cone of two half angles
(radians); ``bend`` turns the cone's centre so a knee swings one way.

:meth:`Physics.add_ragdoll <OpenGLContext.physics.service.Physics.add_ragdoll>`
puts one in the world and returns a :class:`Ragdoll`. Its bones are
:class:`~OpenGLContext.physics.body.Body` handles, so handlers, joints,
impulses and ray hits name them as they name any body. A ragdoll is in one
of three modes (:class:`RagdollMode`): kinematic bones follow the pose target
exactly, powered bones are turned towards it by motors of a torque limit per
bone (``strength``, N m), limp bones fall. The pose target is a held pose
(:meth:`Ragdoll.set_pose`) or a clip of sampled poses (:meth:`Ragdoll.play`),
which the world thread evaluates every tick.

This module holds no engine type: the Jolt engine turns a spec into its own
settings when the ragdoll is added.
"""
from __future__ import annotations

import dataclasses
import enum
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.service import Physics
    from OpenGLContext.physics.types import Poses

__all__ = ['Ragdoll', 'RagdollBone', 'RagdollMode', 'RagdollSpec', 'forward_kinematics',
           'pose_rows', 'quat_conjugate', 'quat_multiply', 'quat_rotate']

Vector = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]
_IDENTITY: Quaternion = (0.0, 0.0, 0.0, 1.0)


class RagdollMode(enum.Enum):
    """How a ragdoll's bones move: following the pose, driven towards it, or falling."""

    KINEMATIC = 'kinematic'
    POWERED = 'powered'
    LIMP = 'limp'

    @classmethod
    def coerce(cls, value: RagdollMode | str) -> RagdollMode:
        """The mode ``value`` names: a member, or its name or value in any case."""
        if isinstance(value, cls):
            return value
        text = str(value).strip().lower()
        for member in cls:
            if text in (member.value, member.name.lower()):
                return member
        raise ValueError('a ragdoll mode is kinematic, powered or limp, not %r' % (value,))


@dataclasses.dataclass
class RagdollBone:
    """One bone: a joint of the skeleton and the capsule that moves with it.

    ``parent`` is the index of the parent bone, -1 for the root. The capsule
    runs ``length`` metres from the joint along ``axis`` (a unit vector in
    the joint's frame) with ``radius``; a ``length`` under twice the radius
    makes a sphere of ``radius`` centred half way. ``mass`` is kg.
    ``twist`` is the (min, max) twist about ``axis`` and ``swing`` the swing
    cone's half angles, radians: the first bounds turns about ``plane_axis``
    (None for a direction square to ``axis``), the second turns about the
    third axis. ``bend`` (rad) turns the cone's centre about ``plane_axis``.
    ``strength`` (N m) is the motors' torque limit when powered and
    ``friction`` (N m) holds the joint in every mode.
    """

    name: str
    parent: int
    translation: Vector
    rotation: Quaternion = _IDENTITY
    radius: float = 0.05
    length: float = 0.2
    axis: Vector = (0.0, 1.0, 0.0)
    mass: float = 1.0
    twist: tuple[float, float] = (-0.3, 0.3)
    swing: tuple[float, float] = (0.6, 0.6)
    bend: float = 0.0
    plane_axis: Vector | None = None
    strength: float = 300.0
    friction: float = 0.5


@dataclasses.dataclass
class RagdollSpec:
    """A skeleton of :class:`RagdollBone` and the settings its bodies share.

    ``self_collision`` lets bones collide with each other, except a bone and
    its parent and bones whose shapes overlap in the rest pose.
    ``motor_frequency`` (Hz) and ``motor_damping`` (ratio) are the joint
    motors' spring. ``root_force`` (N) and ``root_torque`` (N m) limit the
    spring of ``root_frequency`` and ``root_damping`` holding a powered
    ragdoll's root bone to its target; 0 leaves the root free, so a powered
    ragdoll keeps its pose and falls over. ``friction`` and ``restitution``
    are the bones' surface, ``linear_damping`` and ``angular_damping`` 1/s.
    """

    bones: list[RagdollBone]
    self_collision: bool = True
    motor_frequency: float = 10.0
    motor_damping: float = 1.0
    root_frequency: float = 3.0
    root_damping: float = 1.0
    root_force: float = 0.0
    root_torque: float = 0.0
    friction: float = 0.6
    restitution: float = 0.0
    linear_damping: float = 0.05
    angular_damping: float = 0.3
    gravity_factor: float = 1.0

    def __post_init__(self) -> None:
        if not self.bones:
            raise ValueError('a ragdoll has at least one bone')
        for i, bone in enumerate(self.bones):
            if (i == 0) != (bone.parent == -1) or bone.parent >= i:
                raise ValueError('bone %d (%s): a parent comes before its children, and only '
                                 'the first bone has none' % (i, bone.name))
            for name in ('mass', 'radius'):
                value = getattr(bone, name)
                if not (math.isfinite(value) and value > 0.0):
                    raise ValueError('bone %d (%s): %s is a positive number, not %r'
                                     % (i, bone.name, name, value))
            if not (math.isfinite(bone.length) and bone.length >= 0.0):
                raise ValueError('bone %d (%s): length is finite and not negative, not %r'
                                 % (i, bone.name, bone.length))
        names = [bone.name for bone in self.bones]
        if len(set(names)) != len(names):
            raise ValueError('bone names are unique')

    def __len__(self) -> int:
        return len(self.bones)

    @property
    def names(self) -> list[str]:
        """The bone names, in bone order."""
        return [bone.name for bone in self.bones]

    @property
    def parents(self) -> np.ndarray:
        """(B,) parent indices, -1 for the root."""
        return np.array([bone.parent for bone in self.bones], dtype=np.int32)

    @property
    def mass(self) -> float:
        """The bones' total mass, kg."""
        return float(sum(bone.mass for bone in self.bones))

    def index(self, name: str) -> int:
        """The index of the bone called ``name``."""
        for i, bone in enumerate(self.bones):
            if bone.name == name:
                return i
        raise KeyError('no bone is called %r' % (name,))

    def rest_translations(self) -> np.ndarray:
        """(B, 3) rest translations, each in its parent joint's frame."""
        return np.array([bone.translation for bone in self.bones], dtype='d')

    def rest_rotations(self) -> np.ndarray:
        """(B, 4) rest rotations ``(x, y, z, w)``, each in its parent joint's frame."""
        return np.array([bone.rotation for bone in self.bones], dtype='d')

    # -- builders ---------------------------------------------------------
    @classmethod
    def from_skeleton(cls, names: Sequence[str], parents: Sequence[int],
                      translations: Any, rotations: Any = None,
                      radius: float | Any = 0.05, mass: float = 70.0,
                      **settings: Any) -> RagdollSpec:
        """Capsule bones for a skeleton, as a character rig describes one.

        ``translations`` (B, 3) and ``rotations`` (B, 4) are the rest pose in
        each parent joint's frame, parents first. A bone's capsule runs from
        its joint to its first child's, of ``radius`` (m, one or a bone each);
        a bone without children carries one 0.9 times as long as its own
        translation, continuing its direction. ``mass`` (kg) is shared among
        the bones by capsule volume. ``settings`` are further fields.
        """
        count = len(names)
        moves = np.asarray(translations, dtype='d').reshape(count, 3)
        turns = (np.tile(np.array(_IDENTITY), (count, 1)) if rotations is None
                 else np.asarray(rotations, dtype='d').reshape(count, 4))
        radii = np.broadcast_to(np.asarray(radius, dtype='d'), (count,))
        first_child = [-1] * count
        for i, parent in enumerate(parents):
            if parent >= 0 and first_child[parent] < 0:
                first_child[parent] = i
        reaches = []
        for i in range(count):
            if first_child[i] >= 0:
                reach = moves[first_child[i]]
            else:
                own = moves[i]
                own_length = float(np.linalg.norm(own))
                direction = (quat_rotate(quat_conjugate(turns[i]), own / own_length)
                             if own_length else np.array([0.0, 1.0, 0.0]))
                reach = direction * 0.9 * own_length
            reaches.append(np.asarray(reach, dtype='d'))
        volumes = [_capsule_volume(float(radii[i]), float(np.linalg.norm(reaches[i])))
                   for i in range(count)]
        total = sum(volumes)
        bones = []
        for i in range(count):
            length = float(np.linalg.norm(reaches[i]))
            axis = reaches[i] / length if length > 1e-9 else np.array([0.0, 1.0, 0.0])
            bones.append(RagdollBone(
                name=str(names[i]), parent=int(parents[i]), translation=_vector(moves[i]),
                rotation=_quaternion(turns[i]), radius=float(radii[i]), length=length,
                axis=_vector(axis), mass=mass * volumes[i] / total))
        return cls(bones=bones, **settings)

    @classmethod
    def humanoid(cls, height: float = 1.8, mass: float = 70.0, **settings: Any) -> RagdollSpec:
        """An 11-bone standing figure ``height`` metres tall, Y up, facing +Z.

        Pelvis (the root, at 0.55 of the height), chest, head, upper and lower
        arms hanging at the sides, thighs and shins, with the limits of
        :data:`HUMANOID_LIMITS`: knees bend back and elbows forward, hips
        swing forward further than back, the neck and shoulders move most.
        """
        s = height / 1.8
        names = ['pelvis', 'chest', 'head', 'upper_arm_l', 'lower_arm_l', 'upper_arm_r',
                 'lower_arm_r', 'thigh_l', 'shin_l', 'thigh_r', 'shin_r']
        parents = [-1, 0, 1, 1, 3, 1, 5, 0, 7, 0, 9]
        translations = np.array([
            (0.0, 0.99, 0.0), (0.0, 0.30, 0.0), (0.0, 0.32, 0.0),
            (0.19, 0.24, 0.0), (0.0, -0.30, 0.0), (-0.19, 0.24, 0.0), (0.0, -0.30, 0.0),
            (0.10, -0.06, 0.0), (0.0, -0.44, 0.0), (-0.10, -0.06, 0.0), (0.0, -0.44, 0.0),
        ]) * s
        radius = np.array([0.12, 0.13, 0.10, 0.05, 0.045, 0.05, 0.045,
                           0.07, 0.055, 0.07, 0.055]) * s
        out = cls.from_skeleton(names, parents, translations, radius=radius, mass=mass,
                                **settings)
        roles = {'chest': 'spine', 'head': 'head', 'upper_arm_l': 'upper_arm',
                 'upper_arm_r': 'upper_arm', 'lower_arm_l': 'lower_arm',
                 'lower_arm_r': 'lower_arm', 'thigh_l': 'thigh', 'thigh_r': 'thigh',
                 'shin_l': 'shin', 'shin_r': 'shin'}
        for bone in out.bones:
            role = roles.get(bone.name)
            if role is not None:
                apply_limits(bone, role, mass)
        return out

    # -- files ------------------------------------------------------------
    def as_dict(self) -> dict[str, Any]:
        """The spec as plain data: lists and numbers, for a file or a document's extras."""
        out: dict[str, Any] = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)
                               if f.name != 'bones'}
        out['bones'] = [{f.name: _plain(getattr(bone, f.name))
                         for f in dataclasses.fields(bone)} for bone in self.bones]
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RagdollSpec:
        """The spec :meth:`as_dict` wrote; a field it does not name takes its default."""
        values = dict(data)
        bones = []
        for entry in values.pop('bones'):
            fields = dict(entry)
            for name in ('translation', 'rotation', 'axis', 'twist', 'swing'):
                if name in fields:
                    fields[name] = tuple(float(v) for v in fields[name])
            if fields.get('plane_axis') is not None:
                fields['plane_axis'] = tuple(float(v) for v in fields['plane_axis'])
            bones.append(RagdollBone(**fields))
        return cls(bones=bones, **values)


#: Joint limits by role: (twist (min, max), swing half angles, bend, plane axis or None,
#: strength at 70 kg). The limbs hang along -y; a plane axis of +x (across the hips) makes
#: the first half angle and the bend bound bending forward and back.
HUMANOID_LIMITS: dict[str, tuple[tuple[float, float], tuple[float, float], float,
                                 Vector | None, float]] = {
    'spine': ((-0.3, 0.3), (0.4, 0.3), 0.0, None, 600.0),
    'neck': ((-0.5, 0.5), (0.4, 0.4), 0.0, None, 200.0),
    'head': ((-0.8, 0.8), (0.6, 0.5), 0.0, None, 150.0),
    'shoulder': ((-0.2, 0.2), (0.3, 0.3), 0.0, None, 250.0),
    'upper_arm': ((-0.6, 0.6), (1.4, 1.2), 0.0, None, 250.0),
    'lower_arm': ((-0.6, 0.6), (0.7, 0.05), -0.7, (1.0, 0.0, 0.0), 250.0),
    'hand': ((-0.3, 0.3), (0.6, 0.4), 0.0, None, 100.0),
    'thigh': ((-0.4, 0.4), (1.0, 0.5), -0.5, (1.0, 0.0, 0.0), 600.0),
    'shin': ((-0.1, 0.1), (0.65, 0.05), 0.65, (1.0, 0.0, 0.0), 250.0),
    'foot': ((-0.2, 0.2), (0.5, 0.3), 0.0, None, 150.0),
}


def apply_limits(bone: RagdollBone, role: str, mass: float = 70.0) -> RagdollBone:
    """Give ``bone`` the limits and strength :data:`HUMANOID_LIMITS` lists for ``role``.

    The strength scales with the figure's ``mass`` (kg) from the 70 kg the
    table is for. Returns the bone.
    """
    twist, swing, bend, plane, strength = HUMANOID_LIMITS[role]
    bone.twist, bone.swing, bone.bend, bone.plane_axis = twist, swing, bend, plane
    bone.strength = strength * mass / 70.0
    return bone


def forward_kinematics(spec: RagdollSpec, rotations: Any = None, translations: Any = None,
                       position: Any = (0.0, 0.0, 0.0),
                       rotation: Any = _IDENTITY) -> tuple[np.ndarray, np.ndarray]:
    """Each joint's world position (B, 3) and orientation (B, 4) for a pose.

    ``rotations`` (B, 4) and ``translations`` (B, 3) are in each parent
    joint's frame, None for the rest pose's; ``position`` and ``rotation``
    place the ragdoll's frame in the world.
    """
    count = len(spec.bones)
    turns = (spec.rest_rotations() if rotations is None
             else np.asarray(rotations, dtype='d').reshape(count, 4))
    moves = (spec.rest_translations() if translations is None
             else np.asarray(translations, dtype='d').reshape(count, 3))
    out_p = np.empty((count, 3))
    out_q = np.empty((count, 4))
    base_p = np.asarray(position, dtype='d').reshape(3)
    base_q = _unit(np.asarray(rotation, dtype='d').reshape(4))
    for i, bone in enumerate(spec.bones):
        frame_p, frame_q = ((base_p, base_q) if bone.parent < 0
                            else (out_p[bone.parent], out_q[bone.parent]))
        out_p[i] = frame_p + quat_rotate(frame_q, moves[i])
        out_q[i] = _unit(quat_multiply(frame_q, _unit(turns[i])))
    return out_p, out_q


class Ragdoll:
    """One ragdoll of a physics service: its bones as bodies, and the commands that drive it.

    Commands take effect at the next tick. :meth:`poses` reads every bone at
    once, positioned as the frame draws them.
    """

    def __init__(self, physics: Physics, ident: int, spec: RagdollSpec,
                 bones: Sequence[Body], mode: RagdollMode) -> None:
        self.physics = physics
        #: Distinguishes this ragdoll from every other the service has made.
        self.id = ident
        #: The spec the ragdoll was made from.
        self.spec = spec
        #: Each bone's body, in bone order.
        self.bones: tuple[Body, ...] = tuple(bones)
        #: The mode last asked for.
        self.mode = mode
        #: False once the ragdoll has been removed.
        self.alive = True

    def __repr__(self) -> str:
        return 'Ragdoll(%d, bones=%d, %s)' % (self.id, len(self.bones), self.mode.value)

    def bone(self, which: int | str) -> Body:
        """The body of a bone, by index or name."""
        return self.bones[which if isinstance(which, int) else self.spec.index(which)]

    def _index(self, which: int | str | Body) -> int:
        if isinstance(which, str):
            return self.spec.index(which)
        if isinstance(which, int):
            if not 0 <= which < len(self.bones):
                raise IndexError('bone %d of %d' % (which, len(self.bones)))
            return which
        for i, body in enumerate(self.bones):
            if body is which:
                return i
        raise ValueError('%r is not a bone of %r' % (which, self))

    # -- commands ---------------------------------------------------------
    def set_mode(self, mode: RagdollMode | str, blend: float = 0.0) -> None:
        """Change mode over ``blend`` seconds.

        Into powered or limp the motors' strength moves to full or none over
        the blend; out of kinematic the bones keep their velocities. Into
        kinematic the bones move from where they are to the pose target over
        the blend, which is how a fallen figure gets up.
        """
        made = RagdollMode.coerce(mode)
        self.mode = made
        self.physics._ragdoll_command(self, 'ragdoll_mode', made, _seconds(blend, 'blend'))

    def set_pose(self, rotations: Any, translations: Any = None, position: Any = None,
                 rotation: Any = None) -> None:
        """Hold a pose target: each joint's rotation (B, 4) and translation (B, 3) in its parent's frame.

        None keeps the rotations or translations held now; ``position`` and
        ``rotation`` (a quaternion ``(x, y, z, w)``) move the ragdoll's
        frame, None keeps it. A held pose serves while no clip plays.
        """
        count = len(self.bones)
        turns = None if rotations is None else pose_rows(rotations, count, 4, 'rotations')
        moves = None if translations is None else pose_rows(translations, count, 3, 'translations')
        self.physics._ragdoll_command(self, 'ragdoll_pose', turns, moves,
                                      _optional(position, 3, 'position'),
                                      _optional(rotation, 4, 'rotation'))

    def place(self, position: Any, rotation: Any = _IDENTITY) -> None:
        """Move the ragdoll's frame, leaving the joints' pose as it is."""
        self.set_pose(None, None, position, rotation)

    def play(self, times: Any, rotations: Any, translations: Any = None,
             loop: bool = False) -> None:
        """Make a clip the pose target, evaluated on the world thread every tick.

        ``times`` (K,) ascend from 0, seconds from the tick that applies the
        clip; ``rotations`` (K, B, 4) and ``translations`` (K, B, 3) are the
        poses at them. Past the last time the clip holds its last pose, or
        with ``loop`` starts again.
        """
        when = np.ascontiguousarray(times, dtype='d').reshape(-1)
        if len(when) and (not np.isfinite(when).all() or (np.diff(when) < 0).any()):
            raise ValueError('clip times are finite and ascend')
        count = len(self.bones)
        turns = np.asarray(rotations, dtype='d').reshape(len(when), count, 4)
        moves = (None if translations is None
                 else np.asarray(translations, dtype='d').reshape(len(when), count, 3))
        self.physics._ragdoll_command(self, 'ragdoll_clip', when, turns, moves, bool(loop))

    def stop(self) -> None:
        """Stop the clip: the held pose is the target again."""
        self.physics._ragdoll_command(self, 'ragdoll_clip', np.zeros(0),
                                      np.zeros((0, len(self.bones), 4)), None, False)

    def set_strength(self, strength: float | Iterable[float]) -> None:
        """Set the motors' torque limit of each bone, N m: one for all, or one a bone."""
        values = np.broadcast_to(np.asarray(strength, dtype='d'), (len(self.bones),)).copy()
        if not (np.isfinite(values).all() and (values >= 0).all()):
            raise ValueError('strength is finite and not negative')
        self.physics._ragdoll_command(self, 'ragdoll_strength', values)

    def hit(self, bone: int | str | Body, impulse: Any, point: Any = None) -> None:
        """An impulse (N s) on a bone, at its centre of mass or at the world ``point`` (a ray's hit)."""
        body = self.bones[self._index(bone)]
        body.apply_impulse(impulse, point)

    def push(self, velocity: Any) -> None:
        """Add ``velocity`` (m/s) to every bone: an impulse of each bone's mass times it.

        The whole figure is thrown alike, as a blast or the speed it was
        running at throws it, and its joints carry no load from it.
        """
        change = np.asarray(_vector(velocity), dtype='d')
        if not np.isfinite(change).all():
            raise ValueError('velocity is three finite numbers, not %r' % (velocity,))
        for bone, body in zip(self.spec.bones, self.bones, strict=True):
            body.apply_impulse(tuple(change * bone.mass))

    def remove(self) -> None:
        """Take the ragdoll and its bones out of the world. Removing twice is harmless."""
        self.physics._remove_ragdoll(self)

    # -- reading ----------------------------------------------------------
    def poses(self, interpolated: bool = True) -> Poses:
        """Every bone's pose, a row a bone in bone order; see :meth:`Physics.poses`."""
        return self.physics.poses(self.bones, interpolated)

    def nearest_bone(self, point: Any) -> int:
        """The index of the bone whose capsule surface is nearest the world ``point``.

        Where a shot met a figure's hitbox, this is the bone the blow lands on.
        """
        where = np.asarray(_vector(point), dtype='d')
        poses = self.poses()
        axes = np.array([bone.axis for bone in self.spec.bones], dtype='d')
        lengths = np.array([bone.length for bone in self.spec.bones], dtype='d')
        radii = np.array([bone.radius for bone in self.spec.bones], dtype='d')
        starts = np.asarray(poses.position, dtype='d')
        directions = quat_rotate(np.asarray(poses.orientation, dtype='d'), axes)
        along = np.clip(np.einsum('ij,ij->i', where - starts, directions), 0.0, lengths)
        closest = starts + along[:, None] * directions
        gaps = np.linalg.norm(where - closest, axis=1) - radii
        return int(np.argmin(gaps))


# -- quaternions (x, y, z, w), on rows ----------------------------------------

def quat_multiply(a: Any, b: Any) -> np.ndarray:
    """The product ``a b`` of quaternions or rows of them: ``b`` turned, then ``a``."""
    a = np.asarray(a, dtype='d')
    b = np.asarray(b, dtype='d')
    ax, ay, az, aw = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bx, by, bz, bw = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def quat_conjugate(q: Any) -> np.ndarray:
    """The inverse turn of unit quaternions."""
    out = np.array(q, dtype='d')
    out[..., :3] *= -1.0
    return out


def quat_rotate(q: Any, v: Any) -> np.ndarray:
    """Vectors ``v`` turned by unit quaternions ``q`` (rows broadcast)."""
    q = np.asarray(q, dtype='d')
    v = np.asarray(v, dtype='d')
    u = q[..., :3]
    w = q[..., 3:4]
    dot = np.sum(u * v, axis=-1, keepdims=True)
    out: np.ndarray = (2.0 * dot * u + (w * w - np.sum(u * u, axis=-1, keepdims=True)) * v
                       + 2.0 * w * np.cross(u, v))
    return out


def _unit(q: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(q))
    if not (length > 0.0 and math.isfinite(length)):
        raise ValueError('a rotation quaternion has a finite, non-zero length')
    return q / length


def _capsule_volume(radius: float, length: float) -> float:
    if length > 2.0 * radius:
        return math.pi * radius * radius * (length - 2.0 * radius) + 4.0 / 3.0 * math.pi * radius ** 3
    r = max(radius, length / 2.0)
    return 4.0 / 3.0 * math.pi * r ** 3


def _vector(values: Any) -> Vector:
    x, y, z = (float(v) for v in values)
    return (x, y, z)


def _quaternion(values: Any) -> Quaternion:
    x, y, z, w = (float(v) for v in values)
    return (x, y, z, w)


def _plain(value: Any) -> Any:
    if isinstance(value, tuple):
        return [float(v) for v in value]
    return value


def _seconds(value: float, name: str) -> float:
    seconds = float(value)
    if not (math.isfinite(seconds) and seconds >= 0.0):
        raise ValueError('%s is seconds, finite and not negative, not %r' % (name, value))
    return seconds


def pose_rows(values: Any, count: int, width: int, name: str) -> np.ndarray:
    """``values`` as ``count`` finite rows of ``width``, contiguous float64; ValueError otherwise."""
    array = np.asarray(values, dtype='d')
    if array.size != count * width:
        raise ValueError('%s has %d rows of %d for the %d bones, not shape %s'
                         % (name, count, width, count, array.shape))
    array = np.ascontiguousarray(array.reshape(count, width))
    if not np.isfinite(array).all():
        raise ValueError('%s are finite' % (name,))
    return array


def _optional(values: Any, width: int, name: str) -> tuple[float, ...] | None:
    if values is None:
        return None
    array = np.asarray(values, dtype='d').reshape(-1)
    if len(array) != width or not np.isfinite(array).all():
        raise ValueError('%s is %d finite numbers, not %r' % (name, width, values))
    return tuple(float(v) for v in array)
