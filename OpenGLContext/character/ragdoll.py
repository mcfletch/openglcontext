"""A rigged character as a ragdoll: bones chosen from its skeleton, sized from its skin.

:class:`RagdollRig` is built once per loaded document. It chooses the bones a
ragdoll needs from the humanoid bone map (:data:`DEFAULT_BONES`: the pelvis,
spine, chest, head, upper and lower limbs, hands and feet); every other joint
(fingers, twist and helper joints, a neck too short to matter) rides its
nearest chosen ancestor at its rest offset. A rig joint between two chosen
bones that spans at least ``bridge`` metres is made a bone too, so an arm
whose upper joint the bone map does not name still bends at the shoulder.
Each bone's capsule runs to its first chosen child (or, for a hand, a foot or
the head, along the skin weighted to it), with a radius read from the skin:
the distance of the vertices weighted to it from its axis. Masses are shared
by capsule volume; limits are :data:`~OpenGLContext.physics.ragdolls.HUMANOID_LIMITS`
by role, or a document's own (``limits=``).

The rig's arithmetic is in the world: a bone's pose target and the pose that
comes back are world positions and orientations, so a document in centimetres
or turned Z-up becomes a ragdoll in metres, Y up. ``placement`` is the world
matrix of the document's root (row-vector, as the renderer's), identity for a
model drawn where it was loaded.

:class:`RagdollFigure` is the per-frame part: it sends the animation's pose
to the ragdoll as its target (one batch a frame) while the figure follows the
animation, and writes the ragdoll's bone poses back into the skins' joint
matrices, one bulk read a frame.
"""
from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from OpenGLContext.character.humanoid import BONE_PARENT
from OpenGLContext.physics.ragdolls import (
    HUMANOID_LIMITS, RagdollBone, RagdollMode, RagdollSpec, apply_limits, quat_conjugate,
    quat_multiply, quat_rotate,
)

if TYPE_CHECKING:
    from OpenGLContext.character.mixer import AnimationMixer
    from OpenGLContext.character.rig import Rig
    from OpenGLContext.physics.ragdolls import Ragdoll
    from OpenGLContext.physics.service import Physics

__all__ = ['DEFAULT_BONES', 'ROLES', 'RagdollFigure', 'RagdollRig', 'limits_from_hanim',
           'matrix_quaternions']

#: The humanoid bones a ragdoll is made of where the model has them, parents first.
DEFAULT_BONES: tuple[str, ...] = (
    'hips', 'spine', 'chest', 'head',
    'leftUpperArm', 'leftLowerArm', 'leftHand',
    'rightUpperArm', 'rightLowerArm', 'rightHand',
    'leftUpperLeg', 'leftLowerLeg', 'leftFoot',
    'rightUpperLeg', 'rightLowerLeg', 'rightFoot',
)

#: The limit set (a key of HUMANOID_LIMITS) each humanoid bone takes; hips are the root.
ROLES: dict[str, str] = {
    'spine': 'spine', 'chest': 'spine', 'upperChest': 'spine', 'neck': 'neck', 'head': 'head',
    'leftShoulder': 'shoulder', 'rightShoulder': 'shoulder',
    'leftUpperArm': 'upper_arm', 'rightUpperArm': 'upper_arm',
    'leftLowerArm': 'lower_arm', 'rightLowerArm': 'lower_arm',
    'leftHand': 'hand', 'rightHand': 'hand',
    'leftUpperLeg': 'thigh', 'rightUpperLeg': 'thigh',
    'leftLowerLeg': 'shin', 'rightLowerLeg': 'shin',
    'leftFoot': 'foot', 'rightFoot': 'foot',
}

#: Each role's share of a body's mass (Dempster's segment fractions, as Winter's
#: Biomechanics tabulates them); the torso's half is shared among the spine bones.
MASS_SHARES: dict[str, float] = {
    'root': 0.142, 'spine': 0.18, 'neck': 0.02, 'head': 0.081, 'shoulder': 0.01,
    'upper_arm': 0.028, 'lower_arm': 0.016, 'hand': 0.006,
    'thigh': 0.1, 'shin': 0.0465, 'foot': 0.0145,
}

#: The limb chains, root to tip, whose order the hierarchy settles where names do not.
_CHAINS = tuple((side + 'UpperArm', side + 'LowerArm', side + 'Hand') for side in ('left', 'right')) \
    + tuple((side + 'UpperLeg', side + 'LowerLeg', side + 'Foot') for side in ('left', 'right'))

#: The radius of a bone the skin says nothing about, as a share of its length.
_BARE_RADIUS = 0.2
#: Bounds on a radius read from the skin, metres.
_RADIUS_RANGE = (0.02, 0.25)


class RagdollRig:
    """The bones a ragdoll is made of for one skeleton, and the arithmetic between the two.

    ``slots`` are the rig slots of the bones, in bone order, parents first;
    ``bone_of_slot`` the bone each rig slot rides (-1 for slots above the
    root); ``spec`` the :class:`~OpenGLContext.physics.ragdolls.RagdollSpec`
    in metres, its rest pose the rig's at ``placement``.
    """

    def __init__(self, rig: Rig, slots: Sequence[int], names: Sequence[str],
                 spec: RagdollSpec, placement: np.ndarray) -> None:
        self.rig = rig
        self.slots = np.asarray(slots, dtype=np.intp)
        self.names = list(names)
        self.spec = spec
        self.placement = np.asarray(placement, dtype='d')
        self.parents = spec.parents
        self.bone_of_slot = _riders(rig, self.slots)
        # Per generation of the rig, the slots a bone drives, for writing them in while composing.
        chosen = np.zeros(rig.n, dtype=bool)
        chosen[self.slots] = True
        self._row_of_slot = np.full(rig.n, -1, dtype=np.intp)
        self._row_of_slot[self.slots] = np.arange(len(self.slots))
        self._levels = [(level, level[chosen[level]]) for level in rig.levels]

    # -- building ---------------------------------------------------------
    @classmethod
    def from_model(cls, model: Any, **named: Any) -> RagdollRig:
        """The ragdoll of a :class:`~OpenGLContext.character.model.CharacterModel`; see :meth:`build`."""
        if model.humanoid is None:
            raise ValueError('the model has no humanoid skeleton to make a ragdoll of')
        return cls.build(model.mixer, model.humanoid.bones, **named)

    @classmethod
    def build(cls, mixer: AnimationMixer, bones: Mapping[str, int],
              chosen: Sequence[str] = DEFAULT_BONES, mass: float = 70.0,
              placement: Any = None, bridge: float = 0.12,
              limits: Mapping[str, tuple[Any, Any]] | None = None,
              **settings: Any) -> RagdollRig:
        """Choose the bones of ``mixer``'s rig, size them from its skins and return the rig.

        ``bones`` maps humanoid bone names to glTF node indices (a
        :class:`~OpenGLContext.character.humanoid.Humanoid`'s ``bones``).
        ``chosen`` are the humanoid bones to make; the model must have
        ``hips``. ``mass`` is kg in all. ``bridge`` (m) is the span at which a
        joint between two chosen bones becomes a bone. ``limits`` maps a bone
        name to a joint's (llimit, ulimit), HAnim's Euler angles about the
        joint's X, Y and Z (radians), in place of the role's.
        ``settings`` are further :class:`RagdollSpec` fields.
        """
        rig = mixer.rig
        place = np.eye(4) if placement is None else np.asarray(placement, dtype='d')
        if 'hips' not in bones or rig.slot_of.get(int(bones['hips'])) is None:
            raise ValueError('a ragdoll needs the hips bone, which the model does not name')
        picked: dict[int, str] = {}
        for name in chosen:
            node = bones.get(name)
            slot = None if node is None else rig.slot_of.get(int(node))
            if slot is not None:
                picked[slot] = name
        _order_chains(rig, picked)
        worlds = rig.world_matrices(*rig.rest_pose()) @ place
        positions = worlds[:, 3, :3].copy()
        picked.update(_bridged(rig, picked, positions, bridge))
        root = rig.slot_of[int(bones['hips'])]
        # Keep only the root and bones under it, parents first (rig slots are breadth-first).
        slots = sorted(slot for slot in picked if _under(rig, slot, root))
        names = [picked[slot] for slot in slots]
        rotations = matrix_quaternions(worlds[:, :3, :3])
        parent_of = {slot: _chosen_parent(rig, slot, set(slots)) for slot in slots}
        index = {slot: i for i, slot in enumerate(slots)}
        parents = [-1 if parent_of[slot] < 0 else index[parent_of[slot]] for slot in slots]
        moves, turns = _relative(positions[slots], rotations[slots], parents)
        riders = _riders(rig, np.asarray(slots, dtype=np.intp))
        skin = _skin_points(mixer, worlds, riders)
        left = _figure_left(slots, names, positions)
        made = []
        for i, slot in enumerate(slots):
            axis, length = _bone_extent(rig, i, slot, slots, parents, positions, rotations, skin)
            radius = _bone_radius(skin.get(i), positions[slot], rotations[slot], axis, length)
            bone = RagdollBone(name=names[i], parent=parents[i], translation=_vector(moves[i]),
                               rotation=_quaternion(turns[i]), radius=radius, length=length,
                               axis=_vector(axis))
            role = ROLES.get(names[i]) or ROLES.get(names[i].split('/')[0])
            if role is not None:
                apply_limits(bone, role, mass)
                if bone.plane_axis is not None:
                    # The table's plane axis is the figure's left; in this joint's frame here.
                    bone.plane_axis = _square_to(quat_rotate(quat_conjugate(rotations[slot]), left),
                                                 axis)
            if limits and names[i] in limits:
                lower, upper = limits[names[i]]
                bone.twist, bone.swing = limits_from_hanim(lower, upper, axis)
            made.append(bone)
        _share_mass(made, names, mass)
        settings.setdefault('root_force', 0.0)
        return cls(rig, slots, names, RagdollSpec(bones=made, **settings), place)

    # -- the arithmetic -----------------------------------------------------
    def bone_poses(self, pose: tuple[np.ndarray, np.ndarray, np.ndarray],
                   placement: Any = None) -> tuple[np.ndarray, np.ndarray]:
        """World positions (B, 3) and orientations (B, 4) of the bones in a rig pose."""
        place = self.placement if placement is None else np.asarray(placement, dtype='d')
        worlds = self.rig.world_matrices(*pose)[self.slots] @ place
        return worlds[:, 3, :3].copy(), matrix_quaternions(worlds[:, :3, :3])

    def targets(self, pose: tuple[np.ndarray, np.ndarray, np.ndarray],
                placement: Any = None) -> tuple[np.ndarray, np.ndarray]:
        """The ragdoll pose target of a rig pose: rotations (B, 4) and translations (B, 3).

        Each in its parent bone's frame, the root's in the world, for
        :meth:`~OpenGLContext.physics.ragdolls.Ragdoll.set_pose` with the
        ragdoll's frame at the origin.
        """
        positions, rotations = self.bone_poses(pose, placement)
        moves, turns = _relative(positions, rotations, list(self.parents))
        return turns, moves

    def worlds(self, positions: Any, orientations: Any,
               pose: tuple[np.ndarray, np.ndarray, np.ndarray],
               placement: Any = None) -> np.ndarray:
        """``(N, 4, 4)`` rig-slot world matrices with the bones at the world poses given.

        ``positions`` (B, 3) and ``orientations`` (B, 4) are the bones' world
        poses (a ragdoll's); every other slot rides its parent with its local
        transform from ``pose``. The matrices are in the document's space, as
        the skins read them, each bone keeping the scale the pose gives it.
        """
        place = self.placement if placement is None else np.asarray(placement, dtype='d')
        unplace = np.linalg.inv(place)
        local = self.rig.local_matrices(*pose)
        worlds = local.copy()
        bones = np.zeros((len(self.slots), 4, 4))
        turns = quat_to_row_matrices(np.asarray(orientations, dtype='d'))
        bones[:, :3, :3] = turns
        bones[:, 3, :3] = np.asarray(positions, dtype='d')
        bones[:, 3, 3] = 1.0
        bones = bones @ unplace
        rows = self._row_of_slot
        for depth, (level, driven) in enumerate(self._levels):
            if depth:
                worlds[level] = local[level] @ worlds[self.rig.parent[level]]
            if len(driven):
                scale = np.linalg.norm(worlds[driven, 0, :3], axis=1)
                made = bones[rows[driven]].copy()
                made[:, :3, :3] *= scale[:, None, None]
                worlds[driven] = made
        return worlds


class RagdollFigure:
    """A character model whose skeleton a ragdoll drives.

    While :attr:`following`, :meth:`update` advances the model's animation
    and sends its pose to the ragdoll as the target; the ragdoll's mode says
    how the bones meet it (kinematic: exactly; powered: by motors; limp: not
    at all). :meth:`draw` writes the ragdoll's bones into the skins once a
    frame. The model's own ``update`` is not called while a figure drives it.
    """

    def __init__(self, physics: Physics, model: Any, rig: RagdollRig | None = None,
                 mode: RagdollMode | str = 'kinematic', placement: Any = None,
                 collision_filter: Any = None, **build: Any) -> None:
        self.physics = physics
        self.model = model
        self.mixer: AnimationMixer = model.mixer
        if placement is not None:
            build['placement'] = placement
        self.rig = rig if rig is not None else RagdollRig.from_model(model, **build)
        #: Whether :meth:`update` sends the animation's pose as the target.
        self.following = True
        pose = self.mixer.blended_pose()
        turns, moves = self.rig.targets(pose)
        self.ragdoll: Ragdoll = physics.add_ragdoll(self.rig.spec, mode=mode,
                                                     collision_filter=collision_filter)
        self.ragdoll.set_pose(turns, moves)
        self._pose = pose

    @property
    def placement(self) -> np.ndarray:
        """The world matrix of the document's root (row-vector)."""
        return self.rig.placement

    @placement.setter
    def placement(self, matrix: Any) -> None:
        self.rig.placement = np.asarray(matrix, dtype='d').reshape(4, 4)

    def set_mode(self, mode: RagdollMode | str, blend: float = 0.0) -> None:
        """Change the ragdoll's mode over ``blend`` seconds; see :meth:`Ragdoll.set_mode`."""
        self.ragdoll.set_mode(mode, blend)

    def update(self, dt: float) -> None:
        """Advance the animation ``dt`` seconds and, while following, send its pose as the target."""
        started = time.perf_counter()
        self.mixer.advance(dt)
        self._pose = self.mixer.blended_pose()
        if self.following:
            turns, moves = self.rig.targets(self._pose)
            self.ragdoll.set_pose(turns, moves, position=(0.0, 0.0, 0.0),
                                  rotation=(0.0, 0.0, 0.0, 1.0))
        self.physics.note_render_cost('ragdolls', time.perf_counter() - started)

    def draw(self) -> np.ndarray:
        """Write the ragdoll's bones into the skins; the rig-slot world matrices written."""
        started = time.perf_counter()
        poses = self.ragdoll.poses()
        worlds = self.rig.worlds(poses.position, poses.orientation, self._pose)
        self.mixer.reskin_from(worlds)
        self.physics.note_render_cost('ragdolls', time.perf_counter() - started)
        return worlds

    def remove(self) -> None:
        """Take the ragdoll out of the world; the model keeps the last pose it was given."""
        self.ragdoll.remove()


def limits_from_hanim(lower: Any, upper: Any,
                      axis: Any) -> tuple[tuple[float, float], tuple[float, float]]:
    """A swing-twist joint's (twist, swing) from HAnim's Euler limits about the joint's X, Y, Z.

    The axis closest to the bone's ``axis`` is the twist, its (lower, upper)
    taken as they are; the larger magnitude reached about each of the other
    two is a half angle of the swing cone. An axis whose two limits are equal
    is free, as HAnim reads it: its half angle is pi.
    """
    low = (list(np.asarray(lower, dtype='d').ravel()) + [0.0, 0.0, 0.0])[:3]
    high = (list(np.asarray(upper, dtype='d').ravel()) + [0.0, 0.0, 0.0])[:3]
    along = int(np.argmax(np.abs(np.asarray(axis, dtype='d'))))
    others = [k for k in range(3) if k != along]

    def reach(k: int) -> float:
        if low[k] == high[k]:
            return float(np.pi)
        return float(max(abs(low[k]), abs(high[k])))

    twist = ((-np.pi, np.pi) if low[along] == high[along]
             else (float(min(low[along], high[along])), float(max(low[along], high[along]))))
    return (float(twist[0]), float(twist[1])), (reach(others[0]), reach(others[1]))


# -- arithmetic ----------------------------------------------------------------------

def matrix_quaternions(rows: np.ndarray) -> np.ndarray:
    """``(N, 4)`` unit quaternions ``(x, y, z, w)`` of ``(N, 3, 3)`` row-vector matrices.

    Scale is divided out of each row first, so a world matrix of a scaled
    document gives the rotation alone.
    """
    m = np.asarray(rows, dtype='d').reshape(-1, 3, 3)
    m = m / np.maximum(np.linalg.norm(m, axis=2, keepdims=True), 1e-12)
    # The column-vector matrix is the transpose of the row-vector one.
    r = np.transpose(m, (0, 2, 1))
    out = np.empty((len(r), 4))
    trace = r[:, 0, 0] + r[:, 1, 1] + r[:, 2, 2]
    for i in range(len(r)):
        a = r[i]
        if trace[i] > 0.0:
            s = 2.0 * np.sqrt(trace[i] + 1.0)
            out[i] = ((a[2, 1] - a[1, 2]) / s, (a[0, 2] - a[2, 0]) / s,
                      (a[1, 0] - a[0, 1]) / s, 0.25 * s)
        elif a[0, 0] > a[1, 1] and a[0, 0] > a[2, 2]:
            s = 2.0 * np.sqrt(1.0 + a[0, 0] - a[1, 1] - a[2, 2])
            out[i] = (0.25 * s, (a[0, 1] + a[1, 0]) / s, (a[0, 2] + a[2, 0]) / s,
                      (a[2, 1] - a[1, 2]) / s)
        elif a[1, 1] > a[2, 2]:
            s = 2.0 * np.sqrt(1.0 + a[1, 1] - a[0, 0] - a[2, 2])
            out[i] = ((a[0, 1] + a[1, 0]) / s, 0.25 * s, (a[1, 2] + a[2, 1]) / s,
                      (a[0, 2] - a[2, 0]) / s)
        else:
            s = 2.0 * np.sqrt(1.0 + a[2, 2] - a[0, 0] - a[1, 1])
            out[i] = ((a[0, 2] + a[2, 0]) / s, (a[1, 2] + a[2, 1]) / s, 0.25 * s,
                      (a[1, 0] - a[0, 1]) / s)
    out /= np.linalg.norm(out, axis=1, keepdims=True)
    return out


def quat_to_row_matrices(quaternions: np.ndarray) -> np.ndarray:
    """``(N, 3, 3)`` row-vector rotation matrices of unit quaternions ``(x, y, z, w)``."""
    from OpenGLContext.character.rig import quat_to_matrices  # noqa: PLC0415 the rig's own arithmetic
    return quat_to_matrices(quaternions)


def _order_chains(rig: Rig, picked: dict[int, str]) -> None:
    """Name each limb chain's bones root to tip in the hierarchy's order.

    A rig that numbers one arm's joints from the hand gives a bone map with
    that arm's hand above its forearm; the joints' depths settle which is which.
    """
    depth = np.zeros(rig.n, dtype=np.intp)
    for d, level in enumerate(rig.levels):
        depth[level] = d
    named = {name: slot for slot, name in picked.items()}
    for chain in _CHAINS:
        present = [name for name in chain if name in named]
        slots = sorted((named[name] for name in present), key=lambda slot: depth[slot])
        for name, slot in zip(present, slots, strict=True):
            picked[slot] = name


def _figure_left(slots: Sequence[int], names: Sequence[str], positions: np.ndarray) -> np.ndarray:
    """The figure's left in the world at rest: from its right hip to its left, else +x."""
    where = dict(zip(names, slots, strict=True))
    for right, left in (('rightUpperLeg', 'leftUpperLeg'), ('rightUpperArm', 'leftUpperArm')):
        if right in where and left in where:
            across: np.ndarray = positions[where[left]] - positions[where[right]]
            length = float(np.linalg.norm(across))
            if length > 1e-6:
                return across / length
    return np.array([1.0, 0.0, 0.0])


def _square_to(vector: np.ndarray, axis: np.ndarray) -> tuple[float, float, float]:
    """``vector`` made square to unit ``axis`` and of unit length."""
    made = vector - float(np.dot(vector, axis)) * axis
    length = float(np.linalg.norm(made))
    if length < 1e-6:
        made = np.cross(axis, (0.0, 0.0, 1.0) if abs(axis[2]) < 0.9 else (1.0, 0.0, 0.0))
        length = float(np.linalg.norm(made))
    return _vector(made / length)


def _share_mass(bones: Sequence[RagdollBone], names: Sequence[str], mass: float) -> None:
    """Give each bone its role's share of ``mass`` (:data:`MASS_SHARES`), by volume where it has no role.

    The spine bones split the torso's share by volume, and the shares of the
    bones a skeleton has are scaled to make up the whole.
    """
    volumes = np.array([_volume(bone.radius, bone.length) for bone in bones])
    roles = ['root' if bone.parent < 0 else ROLES.get(name, '') for bone, name in zip(
        bones, names, strict=True)]
    spine = [i for i, role in enumerate(roles) if role == 'spine']
    shares = np.zeros(len(bones))
    for i, role in enumerate(roles):
        if role == 'spine':
            shares[i] = MASS_SHARES['spine'] * volumes[i] / volumes[spine].sum()
        elif role:
            shares[i] = MASS_SHARES[role]
    unknown = shares == 0.0
    if unknown.any():
        known = shares[~unknown]
        per_volume = (known.sum() / volumes[~unknown].sum()) if len(known) else 1.0
        shares[unknown] = volumes[unknown] * per_volume
    for bone, share in zip(bones, shares, strict=True):
        bone.mass = float(mass * share / shares.sum())


def _relative(positions: np.ndarray, rotations: np.ndarray,
              parents: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
    """Each bone's translation and rotation in its parent's frame; the root's in the world."""
    moves = positions.copy()
    turns = rotations.copy()
    for i, parent in enumerate(parents):
        if parent < 0:
            continue
        inverse = quat_conjugate(rotations[parent])
        moves[i] = quat_rotate(inverse, positions[i] - positions[parent])
        turns[i] = quat_multiply(inverse, rotations[i])
    return moves, turns


def _under(rig: Rig, slot: int, root: int) -> bool:
    while slot >= 0:
        if slot == root:
            return True
        slot = int(rig.parent[slot])
    return False


def _chosen_parent(rig: Rig, slot: int, chosen: set[int]) -> int:
    walk = int(rig.parent[slot])
    while walk >= 0 and walk not in chosen:
        walk = int(rig.parent[walk])
    return walk


def _riders(rig: Rig, slots: np.ndarray) -> np.ndarray:
    """The bone (row of ``slots``) each rig slot rides, -1 above the root."""
    row = np.full(rig.n, -1, dtype=np.intp)
    row[slots] = np.arange(len(slots))
    out = row.copy()
    for slot in range(rig.n):        # breadth-first: a parent's answer is known first
        if out[slot] < 0 and rig.parent[slot] >= 0:
            out[slot] = out[rig.parent[slot]]
    return out


def _bridged(rig: Rig, picked: dict[int, str], positions: np.ndarray,
             bridge: float) -> dict[int, str]:
    """The joints between two chosen bones that span ``bridge`` metres or more, named for the bone."""
    found: dict[int, str] = {}
    chosen = set(picked)
    for slot, name in picked.items():
        child = slot
        walk = int(rig.parent[slot])
        while walk >= 0 and walk not in chosen:
            if float(np.linalg.norm(positions[child] - positions[walk])) >= bridge:
                missing = BONE_PARENT.get(name)
                found[walk] = missing if missing and missing not in picked.values() \
                    else '%s/parent' % (name,)
                break
            child, walk = walk, int(rig.parent[walk])
    return found


class _Skin(dict[int, np.ndarray]):
    """World points of the skin, by the bone they ride."""


def _skin_points(mixer: AnimationMixer, worlds: np.ndarray, riders: np.ndarray) -> _Skin:
    """Each bone's skin vertices at the rest pose, in the world, by each vertex's heaviest joint."""
    gathered: dict[int, list[np.ndarray]] = {}
    for skin, slots, inverse_bind, _mesh_slot in mixer._skin_plans:
        for mesh in skin.meshes:
            base = getattr(mesh, '_base_positions', None)
            if base is None:
                base = getattr(mesh, 'positions', None)
            joints = getattr(mesh, 'skin_joints', None)
            weights = getattr(mesh, 'skin_weights', None)
            if base is None or joints is None or weights is None or not len(base):
                continue
            heaviest = joints[np.arange(len(joints)), np.argmax(weights, axis=1)].astype(np.intp)
            known = (heaviest < len(slots))
            heaviest = np.where(known, heaviest, 0)
            joint_slots = slots[heaviest]
            usable = known & (joint_slots >= 0)
            points = np.concatenate([np.asarray(base, dtype='d'),
                                     np.ones((len(base), 1))], axis=1)
            # v @ inverse_bind @ joint_world, joint by joint.
            for j in np.unique(heaviest[usable]):
                rows = usable & (heaviest == j)
                bone = int(riders[slots[j]])
                if bone < 0:
                    continue
                placed = points[rows] @ inverse_bind[j] @ worlds[slots[j]]
                gathered.setdefault(bone, []).append(placed[:, :3])
    out = _Skin()
    for bone, parts in gathered.items():
        out[bone] = np.concatenate(parts)
    return out


def _bone_extent(rig: Rig, i: int, slot: int, slots: Sequence[int], parents: Sequence[int],
                 positions: np.ndarray, rotations: np.ndarray,
                 skin: Mapping[int, np.ndarray]) -> tuple[np.ndarray, float]:
    """A bone's capsule axis in its own frame and its length, metres."""
    start = positions[slot]
    inverse = quat_conjugate(rotations[slot])
    children = [k for k, parent in enumerate(parents) if parent == i]
    if children:
        reach = positions[slots[children[0]]] - start
        return _axis_length(quat_rotate(inverse, reach))
    rig_children = np.flatnonzero(rig.parent == slot)
    if len(rig_children):
        reach = positions[int(rig_children[0])] - start
        if float(np.linalg.norm(reach)) > 1e-4:
            return _axis_length(quat_rotate(inverse, reach))
    parent = parents[i]
    direction = (start - positions[slots[parent]]) if parent >= 0 else np.array([0.0, 1.0, 0.0])
    length_of = float(np.linalg.norm(direction))
    direction = direction / length_of if length_of > 1e-9 else np.array([0.0, 1.0, 0.0])
    points = skin.get(i)
    if points is not None and len(points):
        along = (points - start) @ direction
        length = float(np.percentile(along, 95)) if len(along) else 0.0
    else:
        length = 0.9 * length_of
    axis, _ = _axis_length(quat_rotate(inverse, direction))
    return axis, max(length, 0.05)


def _axis_length(reach: np.ndarray) -> tuple[np.ndarray, float]:
    length = float(np.linalg.norm(reach))
    if length < 1e-9:
        return np.array([0.0, 1.0, 0.0]), 0.0
    return reach / length, length


def _bone_radius(points: np.ndarray | None, start: np.ndarray, rotation: np.ndarray,
                 axis: np.ndarray, length: float) -> float:
    """The radius that holds most of a bone's skin: the 60th percentile of its distances from the axis."""
    if points is None or not len(points):
        return float(np.clip(_BARE_RADIUS * length, *_RADIUS_RANGE))
    world_axis = quat_rotate(rotation, axis)
    offset = points - start
    along = np.clip(offset @ world_axis, 0.0, length)
    across = np.linalg.norm(offset - along[:, None] * world_axis, axis=1)
    return float(np.clip(np.percentile(across, 60), *_RADIUS_RANGE))


def _volume(radius: float, length: float) -> float:
    if length > 2.0 * radius:
        return float(np.pi * radius * radius * (length - 2.0 * radius) + 4.0 / 3.0 * np.pi * radius ** 3)
    r = max(radius, length / 2.0)
    return float(4.0 / 3.0 * np.pi * r ** 3)


def _vector(values: Any) -> tuple[float, float, float]:
    x, y, z = (float(v) for v in values)
    return (x, y, z)


def _quaternion(values: Any) -> tuple[float, float, float, float]:
    x, y, z, w = (float(v) for v in values)
    return (x, y, z, w)


assert set(ROLES.values()) <= set(HUMANOID_LIMITS)
