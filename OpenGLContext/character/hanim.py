"""HAnim humanoids as arithmetic: names, skin weights, motion channels, poses, with no GL

The X3D HAnim nodes (:mod:`OpenGLContext.scenegraph.hanim`) are drawn and
animated from what this module works out, and it reads no scenegraph:

- :func:`canonical_joint` and :func:`joint_level` read a joint's name as the
  HAnim standard (ISO/IEC 19774-1) gives it, through the aliases and levels of
  articulation pyvrml97 generates from the X3D Unified Object Model
  (:mod:`vrml.x3d.hanimnames`).
- :func:`skin_influences` turns the joints' `skinCoordIndex` and
  `skinCoordWeight` into the four joints and weights per vertex a
  :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh` is skinned by.
  :func:`skin_points` is the same sum on the CPU.
- :class:`MotionChannels` reads an `HAnimMotion`'s BVH-style `channels` and
  `values`; :func:`motion_frame` is where its playback has got to.
- :func:`blend_values` is an `HAnimPose`'s transition, and
  :func:`limited_rotation` a rotation held to a joint's limits.

Skinning follows X3D's rule for a humanoid: each joint moves a vertex by
``weight * (M v - v)``, where ``M`` is the joint's binding matrix times its
transform in the humanoid's coordinates, so a vertex is posed at
``v + sum(weight * (M v - v))``. Weights need not sum to one. The palette a
skin is drawn with keeps its first matrix, :data:`REST_JOINT`, for the
identity, and the part of a vertex's weight its joints leave out is that
joint's: ``(1 - sum(weight)) v + sum(weight M v)`` is the same sum written as
the linear blend the renderer computes.
"""
from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Iterable, Sequence
from typing import Any, Optional

import numpy as np
from vrml.vrml97 import transformmatrix
from vrml.x3d import hanimnames

from OpenGLContext.loaders.gltf.animation import (
    quat_multiply_rows, quat_slerp_rows, quat_xyzw_to_vrml_rows, vrml_to_quat_xyzw,
)

__all__ = [
    'IGNORED', 'INFLUENCES', 'REST_JOINT', 'ROOT_NAMES', 'WEIGHT_TOLERANCE',
    'JointValues', 'MotionChannels',
    'binding_matrices', 'binding_matrix', 'blend_values', 'canonical_joint', 'convex',
    'displacement',
    'joint_level', 'joint_reach', 'limited_rotation', 'motion_frame', 'posed_bounds',
    'skin_influences', 'skin_points', 'within_level',
]

#: The palette entry that leaves a vertex where it is: the identity.
REST_JOINT = 0
#: Joints a vertex is skinned by, as the renderer's JOINTS_0/WEIGHTS_0 hold them.
INFLUENCES = 4
#: How far from one a vertex's weights may sum and be read as one. Exported
#: skins carry rounding of a few thousandths, which is renormalised rather
#: than held at rest.
WEIGHT_TOLERANCE = 0.005
#: Other names for the root joint: BVH's and HAnim 1's.
ROOT_NAMES = {'HumanoidRoot': 'humanoid_root'}
#: The name an `HAnimMotion` gives a channel group that drives no joint.
IGNORED = 'IGNORED'


def canonical_joint(name: Any) -> str:
    """The standard name for joint `name`: aliases and the BVH root read as HAnim's

    A name the standard does not list is kept as it is, without surrounding
    space.
    """
    text = str(name).strip()
    if text in hanimnames.JOINT_LOA:
        return text
    return ROOT_NAMES.get(text) or hanimnames.JOINT_ALIASES.get(text, text)


def joint_level(name: Any) -> Optional[int]:
    """The level of articulation (0 to 4) the standard puts joint `name` at; None if unlisted"""
    return hanimnames.JOINT_LOA.get(canonical_joint(name))


def within_level(name: Any, loa: int) -> bool:
    """Whether a humanoid of level of articulation `loa` has joint `name`

    A level below zero has every joint, as does a name the standard does not
    list.
    """
    level = joint_level(name)
    return int(loa) < 0 or level is None or level <= int(loa)


# -- skinning -----------------------------------------------------------------

def skin_influences(count: int, influences: Iterable[tuple[Any, Any]],
                    slots: int = INFLUENCES) -> tuple[np.ndarray, np.ndarray]:
    """``(joints, weights)``, each ``(count, slots)``: the palette entries posing each vertex

    count -- the skin's points
    influences -- each joint's ``(skinCoordIndex, skinCoordWeight)``, in the
        order of the humanoid's `joints`; joint ``n`` is palette entry
        ``n + 1``, after :data:`REST_JOINT`

    An index with no weight beside it moves its vertex wholly; one past the
    points is left out, as is a weight of zero. A joint naming a vertex twice
    moves it by the sum. What a vertex's weights leave out of one is
    :data:`REST_JOINT`'s, unless they sum to within :data:`WEIGHT_TOLERANCE`
    of one. Where more than `slots` joints reach a vertex, the heaviest are
    kept and their weights scaled to the whole.
    """
    count = int(count)
    vertices: list[np.ndarray] = []
    joints: list[np.ndarray] = []
    weights: list[np.ndarray] = []
    for number, (indices, values) in enumerate(influences, start=1):
        index = np.asarray(indices, dtype=np.int64).ravel()
        weight = np.asarray(values, dtype=np.float64).ravel()[:len(index)]
        if len(weight) < len(index):
            weight = np.concatenate([weight, np.ones(len(index) - len(weight))])
        kept = (index >= 0) & (index < count) & (weight != 0)
        vertices.append(index[kept])
        joints.append(np.full(int(kept.sum()), number, dtype=np.int64))
        weights.append(weight[kept])
    table_joints = np.zeros((count, slots), dtype=np.uint32)
    table_weights = np.zeros((count, slots), dtype=np.float32)
    if not count:
        return table_joints, table_weights
    vertex = np.concatenate(vertices) if vertices else np.zeros(0, np.int64)
    joint = np.concatenate(joints) if joints else np.zeros(0, np.int64)
    weight = np.concatenate(weights) if weights else np.zeros(0)
    # One entry per (vertex, joint), however often the joint names the vertex.
    span = int(joint.max(initial=0)) + 1
    keys, where = np.unique(vertex * span + joint, return_inverse=True)
    weight = np.bincount(where, weights=weight, minlength=len(keys))
    vertex, joint = keys // span, keys % span
    total = np.bincount(vertex, weights=weight, minlength=count)
    rest = 1.0 - total
    resting = np.flatnonzero(np.abs(rest) > WEIGHT_TOLERANCE)
    vertex = np.concatenate([vertex, resting])
    joint = np.concatenate([joint, np.full(len(resting), REST_JOINT)])
    weight = np.concatenate([weight, rest[resting]])
    order = np.lexsort((-np.abs(weight), vertex))
    vertex, joint, weight = vertex[order], joint[order], weight[order]
    first = np.searchsorted(vertex, vertex, side='left')
    rank = np.arange(len(vertex)) - first
    kept = rank < slots
    table_joints[vertex[kept], rank[kept]] = joint[kept]
    table_weights[vertex[kept], rank[kept]] = weight[kept]
    sums = table_weights.sum(axis=1, dtype=np.float64)
    empty = np.abs(sums) < 1e-9
    table_joints[empty] = REST_JOINT
    table_weights[empty] = 0.0
    table_weights[empty, 0] = 1.0
    sums[empty] = 1.0
    table_weights /= sums[:, None].astype(np.float32)
    return table_joints, table_weights


def skin_points(points: Any, joints: np.ndarray, weights: np.ndarray,
                palette: np.ndarray) -> np.ndarray:
    """`points` posed by the row-vector matrices of `palette` through the influence tables"""
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    blended = np.einsum('nk,nkij->nij', weights.astype(np.float64),
                        np.asarray(palette, dtype=np.float64)[joints])
    homogeneous = np.concatenate([points, np.ones((len(points), 1))], axis=1)
    posed: np.ndarray = np.einsum('ni,nij->nj', homogeneous, blended)[:, :3]
    return posed


def convex(weights: np.ndarray) -> bool:
    """Whether every vertex is a weighted average of its joints: no weight below zero

    Only then does :func:`posed_bounds` contain the posed skin.
    """
    return bool((np.asarray(weights) >= 0).all())


def joint_reach(points: Any, joints: np.ndarray, weights: np.ndarray,
                palette_size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per palette entry: the centre and radius of the rest points it moves, and whether it moves any"""
    rest = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    low = np.full((palette_size, 3), np.inf)
    high = np.full((palette_size, 3), -np.inf)
    for column in range(joints.shape[1]):
        reached = weights[:, column] != 0
        if not reached.any():
            continue
        index = joints[reached, column].astype(np.int64)
        np.minimum.at(low, index, rest[reached])
        np.maximum.at(high, index, rest[reached])
    used = np.isfinite(low).all(axis=1)
    low[~used] = 0.0
    high[~used] = 0.0
    centres = (low + high) / 2.0
    span = high - low
    radii = np.linalg.norm(span, axis=1) / 2.0
    return centres, radii, used


def posed_bounds(reach: tuple[np.ndarray, np.ndarray, np.ndarray],
                 palette: np.ndarray) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """``(low, high)`` corners containing a convex skin posed by `palette`; None for no points

    Each vertex is an average of where its joints carry it, and each joint
    carries its own rest points within the sphere about their centre, so the
    spheres carried by the palette contain every posed vertex.
    """
    centres, radii, used = reach
    live = np.flatnonzero(used[:len(palette)])
    if not len(live):
        return None
    matrices = np.asarray(palette, dtype=np.float64)[live]
    homogeneous = np.concatenate([centres[live], np.ones((len(live), 1))], axis=1)
    moved = np.einsum('ji,jik->jk', homogeneous, matrices)[:, :3]
    # A matrix that scales carries the sphere's radius by its largest stretch.
    stretch = np.linalg.norm(matrices[:, :3, :3], ord=2, axis=(1, 2))
    extent = (radii[live] * stretch)[:, None]
    return (moved - extent).min(axis=0), (moved + extent).max(axis=0)


def displacement(count: int, indices: Any, displacements: Any) -> np.ndarray:
    """``(count, 3)``: an `HAnimDisplacer`'s displacement of each point, zero where it has none

    An index past the points, or one with no displacement beside it, is left out.
    """
    out = np.zeros((int(count), 3))
    index = np.asarray(indices, dtype=np.int64).ravel()
    moved = np.asarray(displacements, dtype=np.float64).reshape(-1, 3)
    index = index[:len(moved)]
    kept = (index >= 0) & (index < count)
    np.add.at(out, index[kept], moved[:len(index)][kept])
    return out


def binding_matrix(translation: Any, rotation: Any, scale: Any) -> np.ndarray:
    """The row-vector matrix that scales, turns and then moves a joint's binding

    A missing value leaves that part out.
    """
    found = transformmatrix.transformMatrix(
        translation=None if translation is None else tuple(translation),
        rotation=None if rotation is None else tuple(rotation),
        scale=None if scale is None else tuple(scale))
    if found is None:
        return np.eye(4)
    return np.asarray(found, dtype=np.float64)


def binding_matrices(count: int, positions: Sequence[Any], rotations: Sequence[Any],
                     scales: Sequence[Any]) -> np.ndarray:
    """``(count, 4, 4)``: each joint's binding matrix from the humanoid's `jointBinding...` lists

    A joint past the end of a list takes no value from it; one past all of
    them binds at the identity.
    """
    def at(values: Sequence[Any], index: int) -> Any:
        return values[index] if index < len(values) else None

    return np.stack([
        binding_matrix(at(positions, index), at(rotations, index), at(scales, index))
        for index in range(int(count))
    ]) if count else np.zeros((0, 4, 4))


# -- motion --------------------------------------------------------------------

_POSITIONS = {'Xposition': 0, 'Yposition': 1, 'Zposition': 2}
_ROTATIONS = {'Xrotation': (1.0, 0.0, 0.0), 'Yrotation': (0.0, 1.0, 0.0),
              'Zrotation': (0.0, 0.0, 1.0)}
_SCALES = {'Xscale': 0, 'Yscale': 1, 'Zscale': 2}
_SEPARATORS = re.compile(r'[\s,]+')

#: What one joint is given at a frame: translation, rotation (axis and angle,
#: radians) and scale, each None where its channels do not drive it.
Sample = tuple[Optional[tuple[float, ...]], Optional[tuple[float, ...]],
               Optional[tuple[float, ...]]]


def _axis_quaternions(axis: tuple[float, float, float], degrees: np.ndarray) -> np.ndarray:
    half = np.radians(degrees) / 2.0
    out = np.zeros((len(degrees), 4))
    out[:, :3] = np.outer(np.sin(half), axis)
    out[:, 3] = np.cos(half)
    return out


class MotionChannels:
    """An `HAnimMotion`'s `joints`, `channels` and `values`, as each joint's frames

    `channels` is BVH's: for each joint in turn a count and that many channel
    names, ``Xposition`` to ``Zrotation`` and ``Xscale`` to ``Zscale``.
    `values` holds every channel of every joint for the first frame, then the
    second frame, and so on. Rotations are in degrees and compose in the order
    the channels list them, as BVH's do: ``Zrotation Xrotation Yrotation``
    turns about Y, then X, then Z. A group's name comes from `joints` in the
    same order; :data:`IGNORED`, or a group past the names, drives nothing.
    """

    def __init__(self, joints: str, channels: str, values: Any) -> None:
        names = [name for name in _SEPARATORS.split(str(joints).strip()) if name]
        groups: list[list[str]] = []
        for token in _SEPARATORS.split(str(channels).strip()):
            if not token:
                continue
            if token.lstrip('+-').isdigit():
                groups.append([])
            elif groups:
                groups[-1].append(token)
            else:
                groups.append([token])
        groups = [group for group in groups if group]
        #: Each group's joint, by its standard name; None for one that drives nothing.
        self.names: list[Optional[str]] = [
            None if index >= len(names) or names[index] == IGNORED
            else canonical_joint(names[index])
            for index in range(len(groups))
        ]
        self.channels = groups
        width = sum(len(group) for group in groups)
        flat = np.asarray(values, dtype=np.float64).ravel()
        #: The frames `values` holds whole.
        self.frames = len(flat) // width if width else 0
        table = flat[:self.frames * width].reshape(self.frames, width)
        self.translations: list[Optional[np.ndarray]] = []
        self.rotations: list[Optional[np.ndarray]] = []
        self.scales: list[Optional[np.ndarray]] = []
        column = 0
        for group in groups:
            translation = scale = rotation = None
            for name in group:
                values_here = table[:, column]
                column += 1
                if name in _POSITIONS:
                    if translation is None:
                        translation = np.zeros((self.frames, 3))
                    translation[:, _POSITIONS[name]] = values_here
                elif name in _SCALES:
                    if scale is None:
                        scale = np.ones((self.frames, 3))
                    scale[:, _SCALES[name]] = values_here
                elif name in _ROTATIONS:
                    turn = _axis_quaternions(_ROTATIONS[name], values_here)
                    rotation = turn if rotation is None else quat_multiply_rows(rotation, turn)
            self.translations.append(translation)
            self.rotations.append(rotation)
            self.scales.append(scale)

    def sample(self, position: float) -> list[Sample]:
        """Each group's values at frame `position`, between frames by interpolation

        Rotations are interpolated along the shorter arc; a position outside
        the frames holds the nearest one. Empty where there are no frames.
        """
        if not self.frames:
            return []
        place = min(max(float(position), 0.0), float(self.frames - 1))
        before = int(math.floor(place))
        after = min(before + 1, self.frames - 1)
        part = place - before
        found: list[Sample] = []
        for translation, rotation, scale in zip(self.translations, self.rotations,
                                                self.scales, strict=True):
            moved = None if translation is None else tuple(
                float(value) for value in translation[before] * (1 - part) + translation[after] * part)
            sized = None if scale is None else tuple(
                float(value) for value in scale[before] * (1 - part) + scale[after] * part)
            turned = None
            if rotation is not None:
                blended = quat_slerp_rows(rotation[before:before + 1], rotation[after:after + 1], part)
                turned = tuple(float(value) for value in quat_xyzw_to_vrml_rows(blended)[0])
            found.append((moved, turned, sized))
        return found


def motion_frame(elapsed: float, start: float, duration: float, increment: int,
                 first: float, last: float, loop: bool) -> tuple[float, bool, int]:
    """``(position, finished, cycles)``: where a motion's playback is, `elapsed` seconds on

    start -- the frame it set out from
    duration -- seconds a frame lasts (`frameDuration`)
    increment -- frames it moves each `duration`: negative plays backwards,
        zero holds the frame (`frameIncrement`)
    first, last -- the range it plays (`startFrame`, `endFrame`)
    loop -- whether it starts again from the other end of the range

    `cycles` counts the times it has started the range again since `start`.
    Without `loop` it finishes at the end of the range it is moving towards.
    """
    if duration <= 0 or not increment:
        return start, False, 0
    span = last - first
    if span <= 0:
        return first, True, 0
    position = start + elapsed / duration * increment
    if increment > 0:
        if not loop:
            return (last, True, 0) if position >= last else (position, False, 0)
        offset = position - first
        cycles = int(math.floor(offset / span)) - int(math.floor((start - first) / span))
        return first + offset % span, False, cycles
    if not loop:
        return (first, True, 0) if position <= first else (position, False, 0)
    offset = last - position
    cycles = int(math.floor(offset / span)) - int(math.floor((last - start) / span))
    return last - offset % span, False, cycles


# -- poses ---------------------------------------------------------------------

@dataclasses.dataclass
class JointValues:
    """Translations, rotations (axis and angle) and scales of several joints, a row each"""

    translations: np.ndarray
    rotations: np.ndarray
    scales: np.ndarray

    @classmethod
    def of(cls, translations: Any, rotations: Any, scales: Any) -> JointValues:
        """Rows from sequences of the three values"""
        return cls(np.asarray(translations, dtype=np.float64).reshape(-1, 3),
                   np.asarray(rotations, dtype=np.float64).reshape(-1, 4),
                   np.asarray(scales, dtype=np.float64).reshape(-1, 3))


def blend_values(start: JointValues, target: JointValues, fraction: float) -> JointValues:
    """`start` carried `fraction` of the way to `target`: positions and scales straight, rotations by slerp

    `fraction` is clamped to 0 to 1.
    """
    part = min(max(float(fraction), 0.0), 1.0)
    begin = np.stack([vrml_to_quat_xyzw(row) for row in start.rotations]) \
        if len(start.rotations) else np.zeros((0, 4))
    end = np.stack([vrml_to_quat_xyzw(row) for row in target.rotations]) \
        if len(target.rotations) else np.zeros((0, 4))
    turned = quat_xyzw_to_vrml_rows(quat_slerp_rows(begin, end, part)) if len(begin) \
        else np.zeros((0, 4))
    return JointValues(start.translations + (target.translations - start.translations) * part,
                       turned,
                       start.scales + (target.scales - start.scales) * part)


# -- limits --------------------------------------------------------------------

def _matrix(rotation: Any) -> np.ndarray:
    """The row-vector 3x3 of an axis-and-angle rotation"""
    found = transformmatrix.transformMatrix(rotation=tuple(float(value) for value in rotation))
    if found is None:
        return np.eye(3)
    return np.asarray(found, dtype=np.float64)[:3, :3]


def _euler_xyz(matrix: np.ndarray) -> np.ndarray:
    """Angles (x, y, z) of the row-vector matrix that turns about X, then Y, then Z"""
    column = matrix.T
    y = math.asin(max(-1.0, min(1.0, -column[2, 0])))
    if abs(column[2, 0]) < 1 - 1e-9:
        x = math.atan2(column[2, 1], column[2, 2])
        z = math.atan2(column[1, 0], column[0, 0])
    else:
        x = math.atan2(-column[1, 2], column[1, 1])
        z = 0.0
    return np.array([x, y, z])


def _from_euler_xyz(angles: np.ndarray) -> np.ndarray:
    turned = np.eye(3)
    for axis, angle in zip(np.eye(3), angles, strict=True):
        turned = turned @ _matrix(tuple(axis) + (float(angle),))
    return turned


def limited_rotation(rotation: Any, llimit: Any, ulimit: Any,
                     limitOrientation: Any) -> tuple[float, float, float, float]:
    """`rotation` held within a joint's limits, as axis and angle

    The limits are angles about the X, Y and Z axes of `limitOrientation`,
    turned about X, then Y, then Z. An axis whose lower and upper limit are
    equal is free, which is what a joint declaring no limits has.
    """
    lower = (list(np.asarray(llimit, dtype=np.float64).ravel()) + [0.0, 0.0, 0.0])[:3]
    upper = (list(np.asarray(ulimit, dtype=np.float64).ravel()) + [0.0, 0.0, 0.0])[:3]
    held = [low < high for low, high in zip(lower, upper, strict=True)]
    given = tuple(float(value) for value in rotation)
    if not any(held):
        return given  # type: ignore[return-value]  # four floats from an SFRotation
    frame = _matrix(limitOrientation)
    local = frame @ _matrix(given) @ frame.T
    angles = _euler_xyz(local)
    clamped = np.array([min(max(angle, low), high) if hold else angle
                        for angle, low, high, hold in zip(angles, lower, upper, held, strict=True)])
    if np.allclose(clamped, angles):
        return given  # type: ignore[return-value]  # four floats from an SFRotation
    world = frame.T @ _from_euler_xyz(clamped) @ frame
    homogeneous = np.eye(4)
    homogeneous[:3, :3] = world.T
    quaternion = _matrix_quaternion(homogeneous[:3, :3])
    found = quat_xyzw_to_vrml_rows(quaternion[None, :])[0]
    return (float(found[0]), float(found[1]), float(found[2]), float(found[3]))


def _matrix_quaternion(matrix: np.ndarray) -> np.ndarray:
    """``[x, y, z, w]`` of a column-vector rotation matrix"""
    m = matrix
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        return np.array([(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s,
                         (m[1, 0] - m[0, 1]) / s, 0.25 * s])
    if m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        return np.array([0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s,
                         (m[2, 1] - m[1, 2]) / s])
    if m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        return np.array([(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s,
                         (m[0, 2] - m[2, 0]) / s])
    s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
    return np.array([(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s,
                     (m[1, 0] - m[0, 1]) / s])
