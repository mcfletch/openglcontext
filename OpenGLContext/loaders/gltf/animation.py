"""glTF 2.0 animation: the runtime engine and its load-time parsing.

Two halves of one concern:

* **Runtime** (pure Python/numpy, no GL, no network): :class:`Sampler` /
  :class:`Channel` / :class:`Animation` evaluate keyframe channels at a time ``t``
  (STEP / LINEAR / slerp'd rotation / CUBICSPLINE, clamped outside the key range);
  :class:`Player` writes the interpolated TRS, morph weights and
  KHR_animation_pointer values onto the scenegraph ``Transform`` nodes the loader
  built, and :class:`Skin` assembles per-joint matrices for linear-blend skinning.
  ``player.evaluate(t)`` once per frame is the whole runtime contract.

* **Parsing** (:func:`_build_animations` and friends): read ``g.animations`` and a
  document's skins / morph targets into those runtime objects at load time,
  resolving KHR_animation_pointer JSON pointers to live-scenegraph setters.

The parse half runs once at load, feeding the runtime half that runs every frame.
A loaded :class:`~OpenGLContext.loaders.gltf.scene.GLTFScene` exposes a bound
:class:`Player` via :meth:`GLTFScene.player`.
"""
from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional, Sequence, Tuple

import numpy as np

from vrml.vrml97 import transformmatrix

from OpenGLContext.scenegraph.pbrmaterial import uv_transform_matrix
from OpenGLContext.loaders.resolver import Resolver
from OpenGLContext.loaders.gltf.accessors import _read_floats, _read_normalized

if TYPE_CHECKING:
    import pygltflib

log = logging.getLogger(__name__)


# ======================================================================
# Runtime: interpolation + scenegraph binding (evaluated per frame)
# ======================================================================

# glTF stores quaternions as [x, y, z, w].
def quat_normalize(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, dtype='d')
    n = np.linalg.norm(q)
    return q / n if n else np.array([0.0, 0.0, 0.0, 1.0])


def quat_slerp(q0: np.ndarray, q1: np.ndarray, u: float) -> np.ndarray:
    """Spherical linear interpolation of two [x,y,z,w] quaternions.

    Takes the shorter arc (flips ``q1`` when the dot product is negative) and
    falls back to normalised lerp for nearly-parallel inputs, where the ``sin``
    denominator underflows.
    """
    q0 = quat_normalize(q0)
    q1 = quat_normalize(q1)
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1 = -q1
        dot = -dot
    if dot > 0.9995:
        return quat_normalize(q0 + u * (q1 - q0))
    theta0 = math.acos(max(-1.0, min(1.0, dot)))
    sin0 = math.sin(theta0)
    theta = theta0 * u
    s0 = math.sin(theta0 - theta) / sin0
    s1 = math.sin(theta) / sin0
    return quat_normalize(s0 * q0 + s1 * q1)


def quat_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compose two [x,y,z,w] quaternions: the rotation ``b`` then the rotation ``a``."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ])


def vrml_to_quat_xyzw(rotation: Sequence[float]) -> np.ndarray:
    """VRML97 axis-angle (x, y, z, radians) -> glTF quaternion [x,y,z,w]."""
    x, y, z, angle = (float(v) for v in rotation)
    axis = np.array([x, y, z], dtype='d')
    length = float(np.linalg.norm(axis))
    if length < 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0])
    axis = axis / length
    half = angle / 2.0
    return np.concatenate([axis * math.sin(half), [math.cos(half)]])


def quat_xyzw_to_vrml(q: np.ndarray) -> Tuple[float, float, float, float]:
    """glTF quaternion [x,y,z,w] -> VRML97 axis-angle (x, y, z, radians)."""
    x, y, z, w = quat_normalize(q)
    w = max(-1.0, min(1.0, w))
    angle = 2.0 * math.acos(w)
    s = math.sqrt(max(0.0, 1.0 - w * w))
    if s < 1e-8:
        return (0.0, 1.0, 0.0, 0.0)
    return (x / s, y / s, z / s, float(angle))


# ----------------------------------------------------------------------
# The same arithmetic over a whole skeleton at once
# ----------------------------------------------------------------------
# A pose is one rotation per joint, and a blend is the same few operations
# repeated over every one of them. These take ``(N, 4)`` and answer for all N
# rows, taking the same branches per row that the helpers above take per call,
# so the two agree row for row -- see tests/unit/test_quaternion_arrays.py.

#: Below this the slerp denominator underflows and a normalised lerp is used
#: instead; the same threshold the one-at-a-time slerp turns at.
_SLERP_LINEAR_ABOVE = 0.9995

#: The identity rotation, as glTF stores one.
_IDENTITY_ROTATION = np.array([0.0, 0.0, 0.0, 1.0])


def quat_normalize_rows(q: np.ndarray) -> np.ndarray:
    """``(N, 4)`` quaternions scaled to unit length; a zero row becomes identity.

    The length is taken from the dot product rather than ``linalg.norm``, and
    the zero-row case is filled in afterwards rather than by pre-building an
    array of identities to divide into: on the few dozen rows a skeleton has,
    what a call costs is almost entirely what it sets up.
    """
    q = np.asarray(q, dtype='d').reshape(-1, 4)
    lengths = np.sqrt((q * q).sum(axis=1))
    empty = lengths == 0.0
    if empty.any():
        lengths = np.where(empty, 1.0, lengths)
        out = q / lengths[:, None]
        out[empty] = _IDENTITY_ROTATION
        return out
    return q / lengths[:, None]


def quat_slerp_rows(q0: np.ndarray, q1: np.ndarray,
                    u: Any) -> np.ndarray:
    """Spherical linear interpolation row by row.

    ``u`` is one fraction for every row or a fraction per row -- a cross-fade
    weights each joint by whatever drove it, so both are wanted.
    """
    fraction = np.atleast_1d(np.asarray(u, dtype='d'))
    # A cross-fade spends nearly all of its life at one end or the other, and
    # at the start of it there is nothing to interpolate.
    if fraction.size == 1 and fraction[0] == 0.0:
        return quat_normalize_rows(q0)
    a = quat_normalize_rows(q0)
    b = quat_normalize_rows(q1)
    dot = np.sum(a * b, axis=1)
    # The shorter arc: a quaternion and its negation are one rotation.
    b = np.where((dot < 0.0)[:, None], -b, b)
    dot = np.abs(dot)
    theta0 = np.arccos(np.clip(dot, -1.0, 1.0))
    sin0 = np.sin(theta0)
    near = dot > _SLERP_LINEAR_ABOVE
    safe = np.where(near, 1.0, sin0)          # keep the unused branch finite
    theta = theta0 * fraction
    s0 = (np.sin(theta0 - theta) / safe)[:, None]
    s1 = (np.sin(theta) / safe)[:, None]
    fraction_column = np.broadcast_to(fraction, dot.shape)[:, None]
    return quat_normalize_rows(np.where(
        near[:, None], a + fraction_column * (b - a), s0 * a + s1 * b))


def quat_multiply_rows(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compose row by row: the rotation ``b`` then the rotation ``a``."""
    a = np.asarray(a, dtype='d').reshape(-1, 4)
    b = np.asarray(b, dtype='d').reshape(-1, 4)
    ax, ay, az, aw = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
    bx, by, bz, bw = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    return np.stack([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ], axis=1)


def quat_conjugate_rows(q: np.ndarray) -> np.ndarray:
    """The inverse of each unit ``[x, y, z, w]`` row."""
    out = quat_normalize_rows(q)
    out[:, :3] *= -1.0
    return out


def quat_xyzw_to_vrml_rows(q: np.ndarray) -> np.ndarray:
    """``(N, 4)`` quaternions -> ``(N, 4)`` VRML97 axis-angle (x, y, z, radians)."""
    unit = quat_normalize_rows(q)
    w = np.clip(unit[:, 3], -1.0, 1.0)
    angle = 2.0 * np.arccos(w)
    s = np.sqrt(np.maximum(0.0, 1.0 - w * w))
    # Where the axis terms vanish -- no rotation, or a full turn -- any axis
    # names the same rotation, so the field's own default is written.
    vanished = s < 1e-8
    safe = np.where(vanished, 1.0, s)
    out = np.empty((len(unit), 4), dtype='d')
    out[:, :3] = unit[:, :3] / safe[:, None]
    out[:, 3] = angle
    out[vanished] = (0.0, 1.0, 0.0, 0.0)
    return out


_INTERP = ('STEP', 'LINEAR', 'CUBICSPLINE')


class Sampler(object):
    """One animation sampler: keyframe times + output values + interpolation.

    ``values`` is ``(N, C)`` for STEP/LINEAR and ``(3N, C)`` for CUBICSPLINE
    (each key is ``[inTangent, value, outTangent]``). ``is_rotation`` selects
    quaternion-aware interpolation (slerp / renormalise).
    """

    def __init__(self, times: np.ndarray, values: np.ndarray,
                 interpolation: str = 'LINEAR', is_rotation: bool = False) -> None:
        self.times = np.ascontiguousarray(times, dtype='d').ravel()
        self.values = np.ascontiguousarray(values, dtype='d')
        if self.values.ndim == 1:
            self.values = self.values.reshape(-1, 1)
        if interpolation not in _INTERP:
            interpolation = 'LINEAR'
        self.interpolation = interpolation
        self.is_rotation = is_rotation

    @property
    def duration(self) -> float:
        return float(self.times[-1]) if len(self.times) else 0.0

    def _segment(self, t: float) -> Tuple[int, float]:
        """Return (i, u): the segment start index i and the [0,1] fraction u."""
        times = self.times
        n = len(times)
        if t <= times[0]:
            return 0, 0.0
        if t >= times[-1]:
            return n - 1, 0.0
        i = int(np.searchsorted(times, t, side='right')) - 1
        i = max(0, min(i, n - 2))
        dt = times[i + 1] - times[i]
        u = (t - times[i]) / dt if dt > 0 else 0.0
        return i, u

    def evaluate(self, t: float) -> np.ndarray:
        """Interpolated value at time ``t`` as a 1-D float array of length C."""
        n = len(self.times)
        if n == 0:
            return np.zeros(self.values.shape[1])
        i, u = self._segment(t)
        if self.interpolation == 'CUBICSPLINE':
            return self._eval_cubic(i, u, t)
        if n == 1 or u == 0.0:
            return np.array(self._key(i))
        if self.interpolation == 'STEP':
            return np.array(self._key(i))
        a, b = self._key(i), self._key(i + 1)
        if self.is_rotation:
            return quat_slerp(a, b, u)
        return a + (b - a) * u

    # -- helpers ----------------------------------------------------------
    def _key(self, i: int) -> np.ndarray:
        """Value of keyframe i (accounts for the CUBICSPLINE 3-per-key layout)."""
        if self.interpolation == 'CUBICSPLINE':
            return self.values[3 * i + 1]
        return self.values[i]

    def _eval_cubic(self, i: int, u: float, t: float) -> np.ndarray:
        n = len(self.times)
        if n == 1:
            return np.array(self.values[1])           # the sole key's value
        if t <= self.times[0]:
            return np.array(self.values[1])
        if t >= self.times[-1]:
            return np.array(self.values[3 * (n - 1) + 1])
        dt = self.times[i + 1] - self.times[i]
        v0 = self.values[3 * i + 1]
        b0 = self.values[3 * i + 2]                   # out-tangent of key i
        v1 = self.values[3 * (i + 1) + 1]
        a1 = self.values[3 * (i + 1)]                 # in-tangent of key i+1
        u2 = u * u
        u3 = u2 * u
        h00 = 2 * u3 - 3 * u2 + 1
        h10 = u3 - 2 * u2 + u
        h01 = -2 * u3 + 3 * u2
        h11 = u3 - u2
        out = h00 * v0 + h10 * dt * b0 + h01 * v1 + h11 * dt * a1
        if self.is_rotation:
            out = quat_normalize(out)
        return out


class Channel(object):
    """Binds a sampler to a target node's TRS path or morph ``weights``."""

    def __init__(self, node_index: int, path: str, sampler: "Sampler") -> None:
        self.node_index = node_index
        self.path = path              # 'translation'|'rotation'|'scale'|'weights'
        self.sampler = sampler


class PointerChannel(object):
    """A KHR_animation_pointer channel: a sampler driving an arbitrary property via
    a resolved ``setter(value)`` (built by the loader against the live scenegraph --
    a material factor, texture transform, node visibility or light property)."""

    def __init__(self, sampler: "Sampler", setter: Callable[..., Any],
                 pointer: Optional[str] = '') -> None:
        self.sampler = sampler
        self.setter = setter
        self.pointer = pointer


class Animation(object):
    """A named set of channels; ``duration`` is the longest sampler."""

    def __init__(self, name: Optional[str], channels: Iterable["Channel"],
                 pointer_channels: Optional[Iterable["PointerChannel"]] = None) -> None:
        self.name = name or ''
        self.channels: list = list(channels)
        self.pointer_channels: list = list(pointer_channels or [])
        self._duration: Optional[float] = None

    @property
    def duration(self) -> float:
        """How long the clip runs: the longest of its samplers.

        Worked out on first asking and kept, because a playing track reads it
        every frame and a character clip carries a couple of hundred channels.
        A clip given more channels afterwards is re-measured by clearing
        ``_duration``.
        """
        if self._duration is None:
            self._duration = max(
                (c.sampler.duration
                 for c in self.channels + self.pointer_channels), default=0.0)
        return self._duration

    def evaluate(self, t: float) -> dict:
        """Map ``node_index -> {path: value}`` at time ``t`` (value is an array).

        ``rotation`` values are the raw glTF [x,y,z,w] quaternion; ``translation``
        and ``scale`` are 3-vectors; ``weights`` is the morph-weight vector.
        """
        out: dict = {}
        for ch in self.channels:
            out.setdefault(ch.node_index, {})[ch.path] = ch.sampler.evaluate(t)
        return out


def _node_local_rv(transform_node: Any) -> np.ndarray:
    """Row-vector local matrix of a Transform/MatrixTransform (current field values)."""
    baked = getattr(transform_node, '_forward', None)
    if baked is not None:
        return np.asarray(baked, dtype='d')
    m = np.asarray(transformmatrix.transformMatrix(
        translation=transform_node.translation,
        rotation=transform_node.rotation,
        scale=transform_node.scale,
    ), dtype='d')
    return m if m.shape == (4, 4) else np.eye(4)


def compute_world_matrices(roots: Iterable[int], children: dict,
                           node_transforms: dict) -> dict:
    """Row-vector world matrix per node, from the current Transform field values.

    A top-down pass composing ``world = local @ parent`` (row-vector, matching how
    the renderer builds its modelview), so skin joint matrices use exactly the same
    world space as the mesh's modelview. Recomputed each frame because animated
    joint transforms change.
    """
    worlds: dict = {}

    def walk(idx: int, parent_world: np.ndarray) -> None:
        xform = node_transforms.get(idx)
        local = _node_local_rv(xform) if xform is not None else np.eye(4)
        w = local @ parent_world
        worlds[idx] = w
        for c in children.get(idx, ()):
            walk(c, w)

    for r in roots:
        walk(r, np.eye(4))
    return worlds


class Skin(object):
    """Linear-blend skin: assembles per-joint matrices and drives its meshes.

    ``inverse_bind`` is the (J,4,4) row-vector inverse-bind stack (glTF's
    column-major MAT4 reshaped without transpose). ``apply(worlds)`` computes, for
    each joint j, ``inverseBind[j] @ world[joint_j] @ inverse(world[meshNode])`` --
    the row-vector form of the Khronos joint matrix, whose ``inverse(meshNode)``
    term cancels the mesh node's own modelview so the skin lives in world space --
    and pushes the stack into each bound mesh.
    """

    def __init__(self, joints: Iterable[int], inverse_bind: np.ndarray,
                 mesh_node: int, meshes: Iterable) -> None:
        self.joints = list(joints)
        self.inverse_bind = np.asarray(inverse_bind, dtype='d')
        self.mesh_node = mesh_node
        self.meshes = list(meshes)

    def apply(self, worlds: dict) -> None:
        node_world = worlds.get(self.mesh_node)
        node_inv = np.linalg.inv(node_world) if node_world is not None else np.eye(4)
        mats = np.empty((len(self.joints), 4, 4), dtype='d')
        for k, j in enumerate(self.joints):
            jw = worlds.get(j, np.eye(4))
            ib = self.inverse_bind[k] if k < len(self.inverse_bind) else np.eye(4)
            mats[k] = ib @ jw @ node_inv
        for mesh in self.meshes:
            mesh.set_skin_matrices(mats)


class Player(object):
    """Applies an :class:`Animation` onto bound scenegraph nodes each frame.

    ``node_transforms`` maps a glTF node index to the ``Transform`` the loader
    built for it; ``node_morph`` maps a node index to a list of morph-weight
    setters (one per primitive of the node's mesh). ``loop`` wraps ``t`` by the
    animation duration so playback repeats.
    """

    def __init__(self, animation: "Animation", node_transforms: Optional[dict],
                 node_morph: Optional[dict] = None, loop: bool = True,
                 skins: Optional[Iterable] = None,
                 compute_worlds: Optional[Callable[[], dict]] = None) -> None:
        self.animation = animation
        self.node_transforms = node_transforms or {}
        self.node_morph = node_morph or {}
        self.loop = loop
        # skins re-evaluate after the joint transforms are written; compute_worlds
        # is a no-arg callable returning the current node world-matrix dict.
        self.skins: list = list(skins) if skins else []
        self.compute_worlds = compute_worlds

    @property
    def duration(self) -> float:
        return self.animation.duration

    def time(self, t: float) -> float:
        d = self.duration
        if self.loop and d > 0:
            return float(t) % d
        return float(t)

    def evaluate(self, t: float) -> None:
        """Sample at ``t`` (looped), write bound nodes, then re-skin."""
        tt = self.time(t)
        sampled = self.animation.evaluate(tt)
        for node_index, paths in sampled.items():
            xform = self.node_transforms.get(node_index)
            for path, value in paths.items():
                if path == 'weights':
                    self._apply_weights(node_index, value)
                elif xform is not None:
                    self._apply_trs(xform, path, value)
        # KHR_animation_pointer: drive arbitrary properties through resolved setters.
        for pc in self.animation.pointer_channels:
            try:
                pc.setter(pc.sampler.evaluate(tt))
            except Exception:
                pass
        self.update_skins()

    def update_skins(self) -> None:
        """Recompute joint matrices from the current joint transforms and apply."""
        if not self.skins or self.compute_worlds is None:
            return
        worlds = self.compute_worlds()
        for skin in self.skins:
            skin.apply(worlds)

    def _apply_trs(self, xform: Any, path: str, value: np.ndarray) -> None:
        if path == 'translation':
            xform.translation = (float(value[0]), float(value[1]), float(value[2]))
        elif path == 'scale':
            xform.scale = (float(value[0]), float(value[1]), float(value[2]))
        elif path == 'rotation':
            xform.rotation = quat_xyzw_to_vrml(value)

    def _apply_weights(self, node_index: int, value: np.ndarray) -> None:
        for setter in self.node_morph.get(node_index, ()):
            setter(np.asarray(value, dtype='f'))


# ======================================================================
# Parsing: read g.animations / skins / morph targets into the objects above
# ======================================================================

_TRS_PATHS = ('translation', 'rotation', 'scale')


def _trs_animated_nodes(g: "pygltflib.GLTF2") -> set:
    """Set of node indices targeted by a translation/rotation/scale channel."""
    out = set()
    for anim in (getattr(g, 'animations', None) or []):
        for ch in (getattr(anim, 'channels', None) or []):
            tgt = getattr(ch, 'target', None)
            if tgt is not None and getattr(tgt, 'node', None) is not None \
                    and getattr(tgt, 'path', None) in _TRS_PATHS:
                out.add(tgt.node)
    return out


def _sampler_values(g: "pygltflib.GLTF2", samp: "pygltflib.AnimationSampler",
                    times_len: int, interp: str, resolver: Resolver) -> np.ndarray:
    """Read a sampler's output accessor as ``(keys, per_key)`` float64.

    One row per keyframe (or three per keyframe for CUBICSPLINE: in-tangent,
    value, out-tangent). ``per_key`` is 3 for translation/scale, 4 for rotation,
    or the morph-target count for a ``weights`` channel -- all recovered from the
    total component count so a single reshape handles every path uniformly.
    """
    raw = _read_normalized(g, samp.output, resolver)
    total = int(np.asarray(raw).size)
    divisor = (3 * times_len) if interp == 'CUBICSPLINE' else times_len
    if divisor <= 0 or total % divisor:
        raise ValueError(
            "glTF animation sampler output (%d values) is not divisible into %d "
            "keyframe rows" % (total, divisor))
    return np.ascontiguousarray(raw, dtype='d').reshape(divisor, total // divisor)


def _pointer_setter(g: "pygltflib.GLTF2", pointer: str, node_transforms: dict,
                    node_light: dict, mat_cache: dict) -> Optional[Callable[..., None]]:
    """Resolve a KHR_animation_pointer JSON-pointer to a ``setter(value)`` that
    mutates the live scenegraph, or None if the target is unsupported. Covers node
    visibility (of a light), material factors, emissive strength and per-texture
    KHR_texture_transform components."""
    toks = [t for t in pointer.split('/') if t]

    def _bump(m: Any) -> None:
        m._ubo_version = int(getattr(m, '_ubo_version', 0)) + 1

    def _v(value: Any) -> np.ndarray:
        return np.ravel(np.asarray(value, dtype='d'))

    try:
        if toks[0] == 'nodes':
            ni = int(toks[1])
            if toks[2:] == ['extensions', 'KHR_node_visibility', 'visible']:
                light = node_light.get(ni)
                if light is not None:
                    base_i = float(getattr(light, 'intensity', 1.0)) or 1.0
                    def set_light_vis(value: Any, light: Any = light,
                                      base_i: float = base_i) -> None:
                        light.intensity = base_i if _v(value)[0] > 0.5 else 0.0
                    return set_light_vis
            return None
        if toks[0] == 'materials':
            m = mat_cache.get(int(toks[1]))
            if m is None:
                return None
            rest = toks[2:]
            if len(rest) >= 2 and rest[-2] == 'KHR_texture_transform':
                comp = rest[-1]                     # rotation | offset | scale
                def set_uvt(value: Any, m: Any = m, comp: str = comp) -> None:
                    p = getattr(m, '_uv_params', None)
                    if p is None:
                        p = {'offset': [0, 0], 'rotation': 0.0, 'scale': [1, 1]}
                        m._uv_params = p
                    val = _v(value)
                    if comp == 'rotation':
                        p['rotation'] = float(val[0])
                    elif comp == 'offset':
                        p['offset'] = [float(val[0]), float(val[1])]
                    elif comp == 'scale':
                        p['scale'] = [float(val[0]), float(val[1])]
                    m.uv_transform = uv_transform_matrix(
                        offset=tuple(p['offset']), rotation=p['rotation'],
                        scale=tuple(p['scale']))
                    _bump(m)
                return set_uvt
            _SCALAR = {
                ('pbrMetallicRoughness', 'metallicFactor'): 'metallic',
                ('pbrMetallicRoughness', 'roughnessFactor'): 'roughness',
            }
            _COLOR3 = {
                ('pbrMetallicRoughness', 'baseColorFactor'): 'baseColor',
                ('emissiveFactor',): 'emissiveColor',
            }
            key = tuple(rest)
            if key in _SCALAR:
                attr = _SCALAR[key]
                def set_scalar(value: Any, m: Any = m, attr: str = attr) -> None:
                    setattr(m, attr, float(_v(value)[0]))
                    _bump(m)
                return set_scalar
            if key in _COLOR3:
                attr = _COLOR3[key]
                def set_color(value: Any, m: Any = m, attr: str = attr) -> None:
                    val = _v(value)
                    setattr(m, attr, tuple(float(x) for x in val[:3]))
                    _bump(m)
                return set_color
            if key == ('extensions', 'KHR_materials_emissive_strength', 'emissiveStrength'):
                def set_es(value: Any, m: Any = m) -> None:
                    m.emissiveStrength = float(_v(value)[0])
                    _bump(m)
                return set_es
        return None
    except (ValueError, IndexError, KeyError, TypeError):
        return None


def _build_animations(g: "pygltflib.GLTF2", resolver: Resolver,
                      node_transforms: Optional[dict] = None, node_light: Optional[dict] = None,
                      mat_cache: Optional[dict] = None) -> list:
    """Parse ``g.animations`` into :class:`Animation` objects (TRS/weights
    channels plus resolved KHR_animation_pointer channels)."""
    node_light = node_light or {}
    mat_cache = mat_cache or {}
    out: list = []
    for anim in (getattr(g, 'animations', None) or []):
        channels: list = []
        pointer_channels: list = []
        samplers = getattr(anim, 'samplers', None) or []
        for ch in (getattr(anim, 'channels', None) or []):
            tgt = getattr(ch, 'target', None)
            if tgt is None:
                continue
            path = getattr(tgt, 'path', None)
            si = getattr(ch, 'sampler', None)
            if si is None or not (0 <= si < len(samplers)):
                continue
            samp = samplers[si]
            interp = getattr(samp, 'interpolation', None) or 'LINEAR'
            try:
                times = _read_floats(g, samp.input, resolver).ravel()
                values = _sampler_values(g, samp, len(times), interp, resolver)
            except (ValueError, KeyError, IndexError) as err:
                log.warning("glTF: skipping animation channel: %s", err)
                continue
            if path == 'pointer':
                ptr = ((getattr(tgt, 'extensions', None) or {})
                       .get('KHR_animation_pointer', {}) or {}).get('pointer')
                setter = _pointer_setter(g, ptr, node_transforms or {},
                                         node_light, mat_cache) if ptr else None
                if setter is not None:
                    pointer_channels.append(PointerChannel(
                        Sampler(times, values, interp), setter, ptr))
                continue
            if path not in ('translation', 'rotation', 'scale', 'weights'):
                continue
            if getattr(tgt, 'node', None) is None:
                continue
            channels.append(Channel(
                tgt.node, path,
                Sampler(times, values, interp, is_rotation=(path == 'rotation'))))
        if channels or pointer_channels:
            out.append(Animation(getattr(anim, 'name', None), channels,
                                  pointer_channels))
    return out


def _resolve_json_pointer(g: "pygltflib.GLTF2",
                          tokens: list) -> Optional[Tuple[Any, str, str]]:
    """Resolve a JSON pointer against a parsed glTF document.

    Walk ``g`` (a pygltflib object tree mixing attributes, lists and extension
    dicts) down ``tokens`` and return (parent, last_token, container_kind), or None
    if any step is missing. ``container_kind`` is 'dict' | 'list' | 'attr'.
    """
    cur = g
    for tok in tokens[:-1]:
        try:
            if isinstance(cur, dict):
                cur = cur[tok]
            elif isinstance(cur, (list, tuple)):
                cur = cur[int(tok)]
            else:
                cur = getattr(cur, tok)
        except (KeyError, IndexError, AttributeError, ValueError, TypeError):
            return None
        if cur is None:
            return None
    last = tokens[-1]
    if isinstance(cur, dict):
        return cur, last, 'dict'
    if isinstance(cur, (list, tuple)):
        return cur, last, 'list'
    return cur, last, 'attr'


def _register_morph(node: Any, node_index: int, shapes: list, g: "pygltflib.GLTF2",
                    node_morph: dict) -> None:
    """Register a node's morph-weight setters and apply its default weights.

    A node's ``weights`` override its mesh's ``weights`` (glTF spec); either
    supplies the initial morph pose. The setters (one per morphable primitive)
    are stored so the animation Player's ``weights`` channel can drive them.
    """
    setters = [s.geometry.set_morph_weights for s, _ in shapes
               if getattr(s.geometry, 'morph_targets', None)]
    if not setters:
        return
    node_morph[node_index] = setters
    weights = getattr(node, 'weights', None)
    if weights is None:
        weights = getattr(g.meshes[node.mesh], 'weights', None)
    if weights:
        for setter in setters:
            setter(weights)


def _read_inverse_bind(g: "pygltflib.GLTF2", skin_def: "pygltflib.Skin", njoints: int,
                       resolver: Resolver) -> np.ndarray:
    """(J,4,4) row-vector inverse-bind stack for a skin (identity if unspecified).

    glTF stores each inverse-bind as a column-major MAT4; ``reshape(-1,4,4)`` of
    the flat column-major floats yields the row-vector matrix directly (the same
    no-transpose convention as node ``matrix``).
    """
    ibm_idx = getattr(skin_def, 'inverseBindMatrices', None)
    if ibm_idx is None:
        return np.stack([np.eye(4)] * max(njoints, 1))
    flat = _read_floats(g, ibm_idx, resolver)
    return np.ascontiguousarray(flat, dtype='d').reshape(-1, 4, 4)


def _register_skin(node: Any, node_index: int, shapes: list, g: "pygltflib.GLTF2",
                   resolver: Resolver, skins: list) -> None:
    """Build a Skin for a node that references one (its meshes + joint matrices)."""
    if getattr(node, 'skin', None) is None or not getattr(g, 'skins', None):
        return
    if not (0 <= node.skin < len(g.skins)):
        return
    skin_meshes = [s.geometry for s, _ in shapes
                   if getattr(s.geometry, 'skin_joints', None) is not None]
    if not skin_meshes:
        return
    sd = g.skins[node.skin]
    joints = list(getattr(sd, 'joints', None) or [])
    inv_bind = _read_inverse_bind(g, sd, len(joints), resolver)
    skins.append(Skin(joints=joints, inverse_bind=inv_bind,
                      mesh_node=node_index, meshes=skin_meshes))
