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
matrices and the joints something hangs on, one bulk read a frame.
:meth:`RagdollFigure.knock_down` is a death: the blow, the figure's own
momentum, and the motors fading to limp.

:class:`RagdollBudget` caps how many figures a game keeps simulated, the
oldest frozen in the pose it reached when a new one comes in.

:class:`CharacterRagdoll` is a physics character's fall: the animated body
handed to a ragdoll that starts where the figure was drawn, moving as the
character moved, and handed back to the animation over a blend once the body
has come to rest. The ragdoll exists only between the two.
"""
from __future__ import annotations

import copy
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from OpenGLContext.character.humanoid import BONE_PARENT
from OpenGLContext.character.rig import matrix_quaternions
from OpenGLContext.loaders.gltf.animation import quat_slerp_rows
from OpenGLContext.physics.ragdolls import (
    HUMANOID_LIMITS, RagdollBone, RagdollMode, RagdollSpec, apply_limits, quat_conjugate,
    quat_multiply, quat_rotate,
)

if TYPE_CHECKING:
    from OpenGLContext.character.mixer import AnimationMixer
    from OpenGLContext.character.rig import Rig
    from OpenGLContext.physics.character import Character
    from OpenGLContext.physics.ragdolls import Ragdoll
    from OpenGLContext.physics.service import Physics

__all__ = ['DEFAULT_BONES', 'ROLES', 'CharacterRagdoll', 'RagdollBudget', 'RagdollFigure',
           'RagdollRest', 'RagdollRig', 'limits_from_hanim', 'matrix_quaternions']

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
        chosen = np.zeros(rig.n, dtype=bool)
        chosen[self.slots] = True
        #: The slots that ride a bone, and those above the root, which ride nothing.
        self._riders = np.flatnonzero((self.bone_of_slot >= 0) & ~chosen)
        self._above = np.flatnonzero(self.bone_of_slot < 0)
        # Per generation below the first, the slots whose parent is not a bone: their
        # offsets chain on through the parent's.
        self._chains = [(level[~chosen[rig.parent[level]]])
                        for level in rig.levels[1:]]
        self._offsets_pose: Any = None
        self._offsets = np.zeros((0, 4, 4))
        self._bone_scale = np.ones(len(self.slots))

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

    def placed(self, placement: Any) -> RagdollRig:
        """This rig for a figure whose document root is at ``placement``; the bones are shared."""
        made = copy.copy(self)
        made.placement = np.asarray(placement, dtype='d').reshape(4, 4)
        return made

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
        offsets = self._offsets_of(pose)
        bones = np.zeros((len(self.slots), 4, 4))
        bones[:, :3, :3] = quat_to_row_matrices(np.asarray(orientations, dtype='d'))
        bones[:, 3, :3] = np.asarray(positions, dtype='d')
        bones[:, 3, 3] = 1.0
        bones = bones @ np.linalg.inv(place)
        bones[:, :3, :3] *= self._bone_scale[:, None, None]
        worlds = np.empty((self.rig.n, 4, 4))
        worlds[self._above] = offsets[self._above]
        worlds[self._riders] = offsets[self._riders] @ bones[self.bone_of_slot[self._riders]]
        worlds[self.slots] = bones
        return worlds

    def _offsets_of(self, pose: tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
        """Each slot's matrix in the frame of the bone it rides, or of the document above the root.

        Worked out again only when ``pose`` is a different object, so a figure
        whose animation has stopped composes its riders once.
        """
        if pose is self._offsets_pose:
            return self._offsets
        local = self.rig.local_matrices(*pose)
        offsets = local.copy()
        for chain in self._chains:
            if len(chain):
                offsets[chain] = local[chain] @ offsets[self.rig.parent[chain]]
        composed = self.rig.world_matrices(*pose)
        self._bone_scale = np.linalg.norm(composed[self.slots, 0, :3], axis=1)
        self._offsets, self._offsets_pose = offsets, pose
        return offsets


class RagdollFigure:
    """A character model whose skeleton a ragdoll drives.

    The ragdoll starts standing in the animation's pose at the moment the
    figure is made. While :attr:`following`, :meth:`update` advances the
    model's animation and sends its pose to the ragdoll as the target; the
    ragdoll's mode says how the bones meet it (kinematic: exactly; powered: by
    motors; limp: not at all). :meth:`draw` writes the ragdoll's bones into the
    skins once a frame. The model's own ``update`` is not called while a
    figure drives it, nor while it is in a
    :class:`~OpenGLContext.character.crowd.Crowd`.

    ``rig`` is a :class:`RagdollRig` to share between figures of one
    document (give each its own ``placement``); without one it is built from
    ``model`` with ``build``. ``queryable`` False lets rays, sweeps and
    overlaps pass through the bones (:attr:`~OpenGLContext.physics.body.Body.queryable`).
    """

    def __init__(self, physics: Physics, model: Any, rig: RagdollRig | None = None,
                 mode: RagdollMode | str = 'kinematic', placement: Any = None,
                 collision_filter: Any = None, queryable: bool = True,
                 **build: Any) -> None:
        self.physics = physics
        self.model = model
        self.mixer: AnimationMixer = model.mixer
        if rig is not None and placement is not None:
            rig = rig.placed(placement)
        elif placement is not None:
            build['placement'] = placement
        self.rig = rig if rig is not None else RagdollRig.from_model(model, **build)
        #: Whether :meth:`update` sends the animation's pose as the target.
        self.following = True
        pose = self.mixer.blended_pose()
        turns, moves = self.rig.targets(pose)
        self.ragdoll: Ragdoll = physics.add_ragdoll(self.rig.spec, mode=mode,
                                                     collision_filter=collision_filter,
                                                     pose=(turns, moves), queryable=queryable)
        self._pose = pose
        #: Seconds until a knock-down's motors are off and the figure stops following.
        self._limp_in: float | None = None
        self._drawn: np.ndarray | None = None
        self._drawn_settled = False
        #: Whether the bones report their waking (:meth:`_listen`), and whether one
        #: has woken since a draw found them all asleep.
        self._listening = False
        self._woken = True

    @property
    def placement(self) -> np.ndarray:
        """The world matrix of the document's root (row-vector)."""
        return self.rig.placement

    @placement.setter
    def placement(self, matrix: Any) -> None:
        self.rig.placement = np.asarray(matrix, dtype='d').reshape(4, 4)

    def set_mode(self, mode: RagdollMode | str, blend: float = 0.0) -> None:
        """Change the ragdoll's mode over ``blend`` seconds; see :meth:`Ragdoll.set_mode`."""
        if RagdollMode(mode) is not RagdollMode.KINEMATIC:
            self._listen()
        self.ragdoll.set_mode(mode, blend)

    def _listen(self) -> None:
        """Have every bone report its waking, so a settled figure's draw reads nothing."""
        if self._listening or not self.ragdoll.alive:
            return
        self._listening = True
        for bone in self.ragdoll.bones:
            bone.addEventHandler('wake', function=self._wake)

    def _wake(self, collision: Any) -> None:  # noqa: ARG002 an event handler is given the event
        self._woken = True

    def knock_down(self, impulse: Any = None, point: Any = None, velocity: Any = None,
                   blend: float = 0.3, bone: int | str | None = None) -> None:
        """Strike the figure and let it fall: powered at once, limp over ``blend`` seconds.

        ``velocity`` (m/s) is added to every bone, the speed the figure was
        moving at or a blast's throw. ``impulse`` (N s) lands on ``bone``, or
        on the bone nearest the world ``point`` (where a shot met the figure),
        or on the root. The motors fade from full strength to none over the
        blend while the figure still follows its animation, so a death clip
        shapes the first moments of the fall; after the blend it stops
        following.
        """
        self._listen()
        if self.ragdoll.mode is RagdollMode.KINEMATIC:
            self.ragdoll.set_mode(RagdollMode.POWERED)
        if velocity is not None:
            self.ragdoll.push(velocity)
        if impulse is not None:
            which = bone if bone is not None else (
                self.ragdoll.nearest_bone(point) if point is not None else 0)
            self.ragdoll.hit(which, impulse, point)
        self.ragdoll.set_mode(RagdollMode.LIMP, blend)
        self._limp_in = max(0.0, float(blend))
        self._drawn_settled = False

    @property
    def settled(self) -> bool:
        """Whether every bone is asleep, or the ragdoll is gone."""
        return not self.ragdoll.alive or all(body.asleep for body in self.ragdoll.bones)

    def update(self, dt: float) -> None:
        """While following, advance the animation ``dt`` seconds and send its pose as the target.

        A figure that is not following holds the pose it last took, which is
        what the joints riding its bones keep, and costs nothing here.
        """
        if self._limp_in is not None:
            self._limp_in -= max(0.0, float(dt))
            if self._limp_in <= 0.0:
                self._limp_in = None
                self.following = False
        if not self.following:
            return
        started = time.perf_counter()
        self.mixer.advance(dt)
        self._pose = self.mixer.blended_pose()
        turns, moves = self.rig.targets(self._pose)
        self.ragdoll.set_pose(turns, moves, position=(0.0, 0.0, 0.0),
                              rotation=(0.0, 0.0, 0.0, 1.0))
        self.physics.note_render_cost('ragdolls', time.perf_counter() - started)

    def draw(self) -> np.ndarray:
        """Write the ragdoll's bones into the skins and joints; the rig-slot world matrices.

        Once the bones are asleep, or the ragdoll is removed, the pose last
        written stands and is returned without being written again. After a
        :meth:`knock_down` or a change out of kinematic mode the bones report
        their waking, so a settled figure reads nothing from the world until
        one of them wakes; before that, each draw reads whether they sleep.
        """
        if self._drawn is not None and (not self.ragdoll.alive or (self._drawn_settled and (
                not self._woken if self._listening else self.settled))):
            return self._drawn
        started = time.perf_counter()
        poses = self.ragdoll.poses()
        settled = not self.ragdoll.alive or bool(np.all(poses.asleep))
        worlds = self.rig.worlds(poses.position, poses.orientation, self._pose)
        self.mixer.reskin_from(worlds)
        self.mixer.write_joints_from(worlds)
        self._drawn, self._drawn_settled = worlds, settled
        if settled:
            self._woken = False
        self.physics.note_render_cost('ragdolls', time.perf_counter() - started)
        return worlds

    def remove(self) -> None:
        """Take the ragdoll out of the world; the model keeps the last pose drawn."""
        self.ragdoll.remove()


class RagdollBudget:
    """At most :attr:`limit` figures simulated at once, the oldest frozen past it.

    A figure frozen is removed from the world (:meth:`RagdollFigure.remove`)
    and keeps the pose it last drew, so a pile of bodies costs the frame no
    more than ``limit`` ragdolls do. Each ragdoll costs its bones in the world
    thread's tick and one bulk read a frame until it settles.
    """

    def __init__(self, limit: int) -> None:
        self._figures: list[Any] = []
        self._limit = 0
        self.limit = limit

    @property
    def limit(self) -> int:
        """How many figures stay simulated; 0 freezes every one at once."""
        return self._limit

    @limit.setter
    def limit(self, value: int) -> None:
        count = int(value)
        if count < 0:
            raise ValueError('a ragdoll budget is 0 or more figures, not %r' % (value,))
        self._limit = count
        self._trim()

    @property
    def figures(self) -> tuple[Any, ...]:
        """The figures simulated now, oldest first."""
        return tuple(self._figures)

    def __len__(self) -> int:
        return len(self._figures)

    def __contains__(self, figure: Any) -> bool:
        return any(held is figure for held in self._figures)

    def admit(self, figure: Any) -> list[Any]:
        """Count ``figure`` in; the figures frozen to make room for it, oldest first.

        With a limit of 0 the figure itself is frozen and returned.
        """
        self.release(figure)
        self._figures.append(figure)
        return self._trim()

    def release(self, figure: Any) -> None:
        """Stop counting ``figure``, which its owner has removed or frozen itself."""
        self._figures = [held for held in self._figures if held is not figure]

    def _trim(self) -> list[Any]:
        frozen = []
        while len(self._figures) > self._limit:
            oldest = self._figures.pop(0)
            oldest.remove()
            frozen.append(oldest)
        return frozen


@dataclass(frozen=True)
class RagdollRest:
    """Where a fallen body lies.

    ``feet`` is the point on the ground under the pelvis, metres, where a
    capsule stands to get up; ``heading`` the direction from the pelvis to the
    head about +Y, radians from +Z (the
    :class:`~OpenGLContext.character.facing.Facing` convention); ``speed`` the
    pelvis's speed, metres a second, near 0 for a body at rest; ``pelvis`` its
    world position.
    """

    feet: np.ndarray
    heading: float
    speed: float
    pelvis: np.ndarray


class CharacterRagdoll:
    """A physics character's body as a ragdoll from a fall until it is handed back to the animation.

    ``character`` is a :class:`~OpenGLContext.physics.character.Character`
    wearing a model with a humanoid skeleton; ``rig`` its
    :class:`RagdollRig`, built from the model as it stands now where None
    (``build`` are :meth:`RagdollRig.build`'s options). Building a rig reads
    the skin and costs milliseconds, so a game making a character per round
    builds it once and passes it to each. The character's :attr:`ragdoll`
    is this object from the call on.

    The capsule decides where the character is. :meth:`fall` knocks it down
    and starts a ragdoll in the pose the figure was last drawn in, each bone
    moving with the capsule's velocity: its motors hold that pose for
    :attr:`powered` seconds and let go over :attr:`limp_blend`, and the body
    tumbles under the world's gravity against everything in it except the
    characters. :meth:`rest` says where it lies. :meth:`recover` removes the
    ragdoll, stands the capsule where the body lies, still knocked down, and
    draws the figure blending from the body's last pose to the animation's
    over ``blend`` seconds; the game ends the knocked-down state with
    :meth:`Character.get_up <OpenGLContext.physics.character.Character.get_up>`
    when its rules say so. While a ragdoll or a blend draws the figure the
    character's node follows the body, joint transforms are not written
    and the animation's clips still advance, so a get-up clip played while
    the character is down is at the point its time says when the blend
    reaches it.

    A character that is not falling or blending holds no ragdoll and does no
    ragdoll arithmetic.
    """

    def __init__(self, character: Character, rig: RagdollRig | None = None, *,
                 powered: float = 0.12, limp_blend: float = 0.2,
                 collision_filter: Any = None, **build: Any) -> None:
        model = character.model
        if model is None:
            raise ValueError('a character needs a model to fall as a ragdoll')
        self.character = character
        if rig is None:
            build.setdefault('placement', _local_matrix(model.group))
            rig = RagdollRig.from_model(model, **build)
        #: The bones the ragdoll is made of, built once.
        self.rig = rig
        #: Seconds the motors hold the pose of the fall, and the seconds they let go over.
        self.powered = float(powered)
        self.limp_blend = float(limp_blend)
        #: The collision filter of the bones, or None for the world's default.
        self.collision_filter = collision_filter
        #: The ragdoll from :meth:`fall` to :meth:`recover`, or None.
        self.ragdoll: Ragdoll | None = None
        self._age = 0.0
        self._limp = False
        #: The body's last bone poses and the blend's length and progress, while blending.
        self._from: tuple[np.ndarray, np.ndarray] | None = None
        self._blend = 0.0
        self._blended = 0.0
        head = 'head' if 'head' in rig.names else rig.names[-1]
        self._head = rig.names.index(head)
        character.ragdoll = self

    # -- state ------------------------------------------------------------
    @property
    def tumbling(self) -> bool:
        """Whether a ragdoll draws the figure."""
        return self.ragdoll is not None

    @property
    def blending(self) -> bool:
        """Whether the figure is blending from the body's last pose to the animation."""
        return self._from is not None

    @property
    def active(self) -> bool:
        """Whether a ragdoll or a blend draws the figure, not the animation alone."""
        return self.ragdoll is not None or self._from is not None

    def placement(self, drawn: bool = True) -> np.ndarray:
        """The world matrix (row-vector) of the model's root.

        The model's own transform, the turn, and the node at the character's
        feet as the frame draws them, or with ``drawn`` false as the last step
        left them; under the body while a ragdoll holds it. The node is taken
        to be in world coordinates, as
        :meth:`Physics.add_character <OpenGLContext.physics.service.Physics.add_character>`
        makes it.
        """
        character = self.character
        matrix: np.ndarray = (_local_matrix(character.model.group)
                              @ _local_matrix(character.turn_node))
        node = character.node
        if node is None:
            return matrix
        local = _local_matrix(node).copy()
        if self.ragdoll is None:
            local[3, :3] = character.drawn_position if drawn else character.position
        placed: np.ndarray = matrix @ local
        return placed

    # -- the fall -----------------------------------------------------------
    def fall(self, impulse: Any = None, bone: int | str | None = None, point: Any = None,
             velocity: Any = None) -> Ragdoll:
        """Knock the character down and hand its body to a ragdoll; returns the ragdoll.

        The bones start in the pose the figure was drawn in, each moving at
        ``velocity`` (m/s), the capsule's velocity where None. ``impulse``
        (N s) strikes ``bone`` (an index or name, the root where None) at its
        centre of mass or at the world ``point``: the blow of what tripped
        it. A character already falling keeps its ragdoll and takes the blow.
        """
        character = self.character
        if self.ragdoll is not None:
            if impulse is not None:
                self.ragdoll.hit(0 if bone is None else bone, impulse, point)
            return self.ragdoll
        moving = character.velocity if velocity is None else velocity
        # The world's bodies are where the last step left them, a part step ahead of where the
        # frame draws them, so the bones start against the capsule as stepped.
        pose = character.model.mixer.blended_pose()
        positions, orientations = self.rig.bone_poses(pose, self.placement(drawn=False))
        moves, turns = _relative(positions, orientations, list(self.rig.parents))
        ragdoll = character.physics.add_ragdoll(
            self.rig.spec, mode='powered', collision_filter=self.collision_filter,
            pose=(turns, moves), velocity=moving, blocks_characters=False)
        if impulse is not None:
            ragdoll.hit(0 if bone is None else bone, impulse, point)
        self.ragdoll = ragdoll
        self._from = None
        self._age = 0.0
        self._limp = False
        character.knock_down()
        return ragdoll

    def rest(self) -> RagdollRest:
        """Where the fallen body lies now; raises RuntimeError while there is no ragdoll."""
        ragdoll = self.ragdoll
        if ragdoll is None:
            raise RuntimeError('the character has not fallen')
        return self._rest(ragdoll, ragdoll.poses())

    def _rest(self, ragdoll: Ragdoll, poses: Any) -> RagdollRest:
        pelvis = poses.position[0].copy()
        toward = poses.position[self._head] - pelvis
        heading = math.atan2(float(toward[0]), float(toward[2]))
        physics = self.character.physics
        # The ground a capsule stands on: what characters walk through, the bones among them,
        # is not ground.
        under = physics.raycast(pelvis + (0.0, _ABOVE, 0.0), (0.0, -1.0, 0.0), _BELOW + _ABOVE,
                                skip=[self.character.body, *physics.passable])
        if under is not None:
            feet = np.asarray(under.point, dtype='d').copy()
        else:
            radius = max(bone.radius for bone in self.rig.spec.bones)
            feet = np.array([pelvis[0], float(poses.position[:, 1].min()) - radius, pelvis[2]])
        return RagdollRest(feet, heading, float(np.linalg.norm(poses.velocity[0])), pelvis)

    def recover(self, blend: float = 0.4, place: bool = True) -> np.ndarray:
        """End the ragdoll and blend the figure back to the animation over ``blend`` seconds.

        With ``place`` the capsule stands where the body lies
        (:attr:`RagdollRest.feet`), which this returns. The character stays
        knocked down. Raises RuntimeError while there is no ragdoll.
        """
        ragdoll = self.ragdoll
        if ragdoll is None:
            raise RuntimeError('the character has not fallen')
        poses = ragdoll.poses()
        rest = self._rest(ragdoll, poses)
        ragdoll.remove()
        self.ragdoll = None
        if place:
            self.character.teleport(rest.feet)
        self._blend = max(0.0, float(blend))
        self._blended = 0.0
        self._from = (poses.position.copy(), poses.orientation.copy()) if self._blend else None
        return rest.feet

    def park(self) -> None:
        """Remove the ragdoll and end any blend: the animation draws the figure from the next frame."""
        if self.ragdoll is not None:
            self.ragdoll.remove()
            self.ragdoll = None
        self._from = None

    # -- the frame ----------------------------------------------------------
    def draw(self, dt: float) -> None:
        """Advance the clips ``dt`` seconds and draw the figure from the ragdoll or the blend.

        The character calls this once a frame in place of the model's
        ``update`` while :attr:`active`.
        """
        started = time.perf_counter()
        mixer = self.character.model.mixer
        mixer.advance(dt)
        pose = mixer.blended_pose()
        ragdoll = self.ragdoll
        if ragdoll is not None:
            self._age += max(0.0, float(dt))
            if not self._limp and self._age >= self.powered:
                ragdoll.set_mode('limp', self.limp_blend)
                self._limp = True
            poses = ragdoll.poses()
            positions, orientations = poses.position, poses.orientation
            self._follow(positions)
            placement = self.placement()
        elif self._from is not None:
            self._blended += max(0.0, float(dt))
            share = min(1.0, self._blended / self._blend)
            weight = share * share * (3.0 - 2.0 * share)
            placement = self.placement()
            goal_p, goal_q = self.rig.bone_poses(pose, placement)
            start_p, start_q = self._from
            positions = start_p + (goal_p - start_p) * weight
            orientations = quat_slerp_rows(start_q, goal_q, weight)
            if share >= 1.0:
                self._from = None
        else:
            return
        mixer.reskin_from(self.rig.worlds(positions, orientations, pose, placement))
        self.character.physics.note_render_cost('ragdolls', time.perf_counter() - started)

    def _follow(self, positions: np.ndarray) -> None:
        """Put the character's node under the body: the pelvis across, its lowest bone up."""
        node = self.character.node
        if node is not None:
            node.translation = (float(positions[0, 0]), float(positions[:, 1].min()),
                                float(positions[0, 2]))


#: How far above the pelvis the ray for the ground under a fallen body starts, and how far below
#: it the ray looks, metres.
_ABOVE = 0.5
_BELOW = 3.0


def _local_matrix(node: Any) -> np.ndarray:
    """A transform node's own matrix (row-vector), identity for a node with none."""
    if node is None or not hasattr(node, 'localMatrices'):
        return np.eye(4)
    forward = node.localMatrices().data[0]
    # An identity transform has no matrix.
    return np.eye(4) if forward is None else np.asarray(forward, dtype='d')


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
    moves = np.array(positions, dtype='d')
    turns = np.array(rotations, dtype='d')
    of = np.asarray(parents, dtype=np.intp)
    child = of >= 0
    inverse = quat_conjugate(turns[of[child]])
    moves[child] = quat_rotate(inverse, moves[child] - moves[of[child]])
    turns[child] = quat_multiply(inverse, turns[child])
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
