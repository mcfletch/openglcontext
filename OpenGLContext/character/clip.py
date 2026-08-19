"""Sampling one clip for a whole skeleton at once.

:class:`~OpenGLContext.loaders.gltf.animation.Sampler` answers for one channel,
which is the right shape for a document that animates a lamp and the wrong one
for a body: an exported character clip carries a channel per joint per path --
a hundred and seventy of them for a fifty-seven-bone rig -- and a search and a
blend apiece is most of what a figure costs per frame.

:class:`ClipSampler` regroups a clip once, at load, into the arrays that
arithmetic wants:

* channels that share a **time grid, an interpolation and a path** become one
  block, so one search over the keyframe times serves the whole block and the
  blend runs over every channel in it together;
* a channel that holds **one value for the clip's whole length** -- which most
  of an exported clip's channels do, since an exporter writes every joint
  whether it moves or not -- is answered from that value, with nothing to
  search and nothing to blend.

A sampler belongs to a *document*, so one is built per clip per loaded build
and shared by every figure of it; it holds no clock. What comes back from
:meth:`sample` is the sampler's own storage in the constant case, so a caller
reads it and does not write to it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from OpenGLContext.character.rig import Rig
from OpenGLContext.loaders.gltf.animation import Animation, quat_slerp_rows

__all__ = ['ClipSampler']

#: The paths a skeleton's pose is made of, and how wide each one is.
_PATHS: Tuple[Tuple[str, int], ...] = (
    ('translation', 3), ('rotation', 4), ('scale', 3),
)


class _Block:
    """Channels of one path that share a time grid and an interpolation.

    ``values`` is ``(C, K, W)``, or ``(C, 3K, W)`` for CUBICSPLINE, where the
    three rows of a key are its in-tangent, its value and its out-tangent.
    """

    __slots__ = ('times', 'values', 'rows', 'interpolation', 'is_rotation')

    def __init__(self, times: np.ndarray, values: np.ndarray, rows: np.ndarray,
                 interpolation: str, is_rotation: bool) -> None:
        self.times = times
        self.values = values
        self.rows = rows                    # index into the path's slot array
        self.interpolation = interpolation
        self.is_rotation = is_rotation

    def _segment(self, t: float) -> Tuple[int, float]:
        """The segment start index and the [0, 1] fraction along it."""
        times = self.times
        n = len(times)
        if t <= times[0]:
            return 0, 0.0
        if t >= times[-1]:
            return n - 1, 0.0
        i = int(np.searchsorted(times, t, side='right')) - 1
        i = max(0, min(i, n - 2))
        dt = times[i + 1] - times[i]
        return i, ((t - times[i]) / dt if dt > 0 else 0.0)

    def _key(self, i: int) -> np.ndarray:
        if self.interpolation == 'CUBICSPLINE':
            key: np.ndarray = self.values[:, 3 * i + 1]
        else:
            key = self.values[:, i]
        return key

    def evaluate(self, t: float) -> np.ndarray:
        """``(C, W)``: every channel of this block at time ``t``."""
        n = len(self.times)
        if n == 0:
            return np.zeros((len(self.rows), self.values.shape[2]))
        i, u = self._segment(t)
        if self.interpolation == 'CUBICSPLINE':
            return self._evaluate_cubic(i, u, t)
        if n == 1 or u == 0.0 or self.interpolation == 'STEP':
            return self._key(i)
        a, b = self._key(i), self._key(i + 1)
        if self.is_rotation:
            return quat_slerp_rows(a, b, u)
        blended: np.ndarray = a + (b - a) * u
        return blended

    def evaluate_many(self, times: np.ndarray) -> np.ndarray:
        """``(F, C, W)``: every channel of this block at each of ``F`` times.

        A crowd is many bodies playing a handful of clips, each at its own point
        in one. Answering for every body at once turns what a figure costs from
        a numpy call per block into a share of one -- and on the few dozen rows
        a skeleton has, a numpy call is nearly all set-up.
        """
        count = len(self.rows)
        width = self.values.shape[2]
        if len(self.times) == 0:
            return np.zeros((len(times), count, width))
        first, fraction = self._segments(times)
        if self.interpolation == 'CUBICSPLINE':
            return self._evaluate_cubic_many(first, fraction, times)
        if len(self.times) == 1 or self.interpolation == 'STEP':
            return self._keys(first)
        a, b = self._keys(first), self._keys(np.minimum(first + 1,
                                                        len(self.times) - 1))
        if self.is_rotation:
            spread = np.repeat(fraction, count)
            turned: np.ndarray = quat_slerp_rows(
                a.reshape(-1, width), b.reshape(-1, width),
                spread).reshape(-1, count, width)
            return turned
        blended: np.ndarray = a + (b - a) * fraction[:, None, None]
        return blended

    def _segments(self, times: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Segment index and [0, 1] fraction for each of ``times`` at once."""
        grid = self.times
        n = len(grid)
        first = np.clip(np.searchsorted(grid, times, side='right') - 1, 0, max(n - 2, 0))
        spans = grid[np.minimum(first + 1, n - 1)] - grid[first]
        fraction = np.divide(times - grid[first], spans,
                             out=np.zeros(len(times)), where=spans > 0)
        # Outside the clip the value is held, which is what the one-at-a-time
        # segment returns as a zero fraction at either end.
        fraction = np.where(times <= grid[0], 0.0, fraction)
        past = times >= grid[-1]
        first = np.where(past, n - 1, first)
        return first, np.where(past, 0.0, fraction)

    def _keys(self, first: np.ndarray) -> np.ndarray:
        """``(F, C, W)`` values of the keyframes named by ``first``."""
        index = 3 * first + 1 if self.interpolation == 'CUBICSPLINE' else first
        keys: np.ndarray = np.take(self.values, index, axis=1).transpose(1, 0, 2)
        return keys

    def _evaluate_cubic_many(self, first: np.ndarray, fraction: np.ndarray,
                             times: np.ndarray) -> np.ndarray:
        n = len(self.times)
        width = self.values.shape[2]
        if n == 1:
            return np.repeat(self.values[:, 1][None], len(times), axis=0)
        following = np.minimum(first + 1, n - 1)
        spans = (self.times[following] - self.times[first])[:, None, None]
        v0 = np.take(self.values, 3 * first + 1, axis=1).transpose(1, 0, 2)
        b0 = np.take(self.values, 3 * first + 2, axis=1).transpose(1, 0, 2)
        v1 = np.take(self.values, 3 * following + 1, axis=1).transpose(1, 0, 2)
        a1 = np.take(self.values, 3 * following, axis=1).transpose(1, 0, 2)
        u = fraction[:, None, None]
        u2, u3 = u * u, u * u * u
        out = ((2 * u3 - 3 * u2 + 1) * v0 + (u3 - 2 * u2 + u) * spans * b0
               + (-2 * u3 + 3 * u2) * v1 + (u3 - u2) * spans * a1)
        # Held at either end, as the one-at-a-time evaluation holds it.
        before, after = times <= self.times[0], times >= self.times[-1]
        if before.any():
            out[before] = self.values[:, 1]
        if after.any():
            out[after] = self.values[:, 3 * (n - 1) + 1]
        if self.is_rotation:
            lengths = np.linalg.norm(out, axis=2, keepdims=True)
            out = np.divide(out, lengths, out=np.zeros_like(out), where=lengths > 0)
        shaped: np.ndarray = out.reshape(-1, len(self.rows), width)
        return shaped

    def _evaluate_cubic(self, i: int, u: float, t: float) -> np.ndarray:
        n = len(self.times)
        if n == 1 or t <= self.times[0]:
            return self.values[:, 1]
        if t >= self.times[-1]:
            return self.values[:, 3 * (n - 1) + 1]
        dt = self.times[i + 1] - self.times[i]
        v0 = self.values[:, 3 * i + 1]
        b0 = self.values[:, 3 * i + 2]
        v1 = self.values[:, 3 * (i + 1) + 1]
        a1 = self.values[:, 3 * (i + 1)]
        u2 = u * u
        u3 = u2 * u
        out: np.ndarray = ((2 * u3 - 3 * u2 + 1) * v0 + (u3 - 2 * u2 + u) * dt * b0
                           + (-2 * u3 + 3 * u2) * v1 + (u3 - u2) * dt * a1)
        if self.is_rotation:
            lengths = np.linalg.norm(out, axis=1, keepdims=True)
            out = np.divide(out, lengths, out=np.zeros_like(out), where=lengths > 0)
        return out


class _PathChannels:
    """Every channel of one path, as the slots they drive and how to fill them."""

    def __init__(self, width: int) -> None:
        self.width = width
        self.slots = np.zeros(0, dtype=np.int32)
        self.blocks: List[_Block] = []
        #: Values for the channels that never move, laid straight into ``sample``.
        self.constant = np.zeros((0, width), dtype='d')
        self.constant_rows = np.zeros(0, dtype=np.int32)

    @property
    def moving(self) -> bool:
        return bool(self.blocks)

    def sample_many(self, times: np.ndarray) -> np.ndarray:
        """``(F, C, W)`` for this path, one row of channels per time."""
        if not self.blocks:
            return np.repeat(self.constant[None], len(times), axis=0)
        out = np.empty((len(times), len(self.slots), self.width), dtype='d')
        if len(self.constant_rows):
            out[:, self.constant_rows] = self.constant
        for block in self.blocks:
            out[:, block.rows] = block.evaluate_many(times)
        return out

    def sample(self, t: float) -> np.ndarray:
        """``(C, W)`` for this path, in the order of :attr:`slots`.

        Where nothing in the path moves, that is the stored block of constant
        values itself -- already in slot order, since the rows were filled in
        that order -- so a still clip costs no work at all per frame.
        """
        if not self.blocks:
            return self.constant
        out = np.empty((len(self.slots), self.width), dtype='d')
        if len(self.constant_rows):
            out[self.constant_rows] = self.constant
        for block in self.blocks:
            out[block.rows] = block.evaluate(t)
        return out


class ClipSampler:
    """One clip of one rig, regrouped so sampling it moves every joint at once."""

    def __init__(self, animation: Animation, rig: Rig) -> None:
        self.clip = animation
        self.rig = rig
        self.name = animation.name
        self.duration = animation.duration
        self._paths: Dict[str, _PathChannels] = {
            path: _PathChannels(width) for path, width in _PATHS
        }
        self._weights: List[Tuple[int, Any]] = []
        self._group(animation, rig)

    # -- what the clip drives ---------------------------------------------
    @property
    def slots_translation(self) -> np.ndarray:
        return self._paths['translation'].slots

    @property
    def slots_rotation(self) -> np.ndarray:
        return self._paths['rotation'].slots

    @property
    def slots_scale(self) -> np.ndarray:
        return self._paths['scale'].slots

    @property
    def constant_channels(self) -> int:
        """How many of the clip's channels hold one value throughout."""
        return sum(len(p.constant_rows) for p in self._paths.values())

    @property
    def moves(self) -> bool:
        """Whether anything in the clip changes with time."""
        return any(p.moving for p in self._paths.values()) or bool(self._weights)

    # -- construction ------------------------------------------------------
    def _group(self, animation: Animation, rig: Rig) -> None:
        """Sort the clip's channels into blocks that can be sampled together.

        A channel aimed at a node this rig has not got is dropped, so a clip
        authored against a fuller skeleton plays what it can. Where two
        channels drive one path of one node -- which is malformed -- the later
        one wins, as it does when the values are collected into a dict.
        """
        by_path: Dict[str, Dict[int, Any]] = {path: {} for path, _ in _PATHS}
        for channel in animation.channels:
            if channel.path == 'weights':
                self._weights.append((channel.node_index, channel.sampler))
                continue
            slot = rig.slot_of.get(channel.node_index)
            if slot is None or channel.path not in by_path:
                continue
            by_path[channel.path][slot] = channel.sampler
        for path, width in _PATHS:
            self._build_path(self._paths[path], by_path[path], width,
                             is_rotation=(path == 'rotation'))

    @staticmethod
    def _build_path(store: _PathChannels, samplers: Dict[int, Any], width: int,
                    is_rotation: bool) -> None:
        if not samplers:
            return
        slots = sorted(samplers)
        store.slots = np.asarray(slots, dtype=np.int32)
        constant_rows: List[int] = []
        constant_values: List[np.ndarray] = []
        blocks: Dict[Any, List[Tuple[int, Any]]] = {}
        for row, slot in enumerate(slots):
            sampler = samplers[slot]
            fixed = _constant_value(sampler)
            if fixed is not None:
                constant_rows.append(row)
                constant_values.append(_widen(fixed.reshape(1, -1), width)[0])
                continue
            key = (sampler.interpolation, sampler.times.tobytes())
            blocks.setdefault(key, []).append((row, sampler))
        store.constant_rows = np.asarray(constant_rows, dtype=np.int32)
        store.constant = (np.stack(constant_values) if constant_values
                          else np.zeros((0, width), dtype='d'))
        for (interpolation, _), members in blocks.items():
            rows = np.asarray([row for row, _ in members], dtype=np.int32)
            values = np.stack([_widen(s.values, width) for _, s in members])
            store.blocks.append(_Block(
                members[0][1].times, values, rows, interpolation,
                is_rotation and members[0][1].is_rotation))

    # -- sampling ----------------------------------------------------------
    def sample(self, t: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Translation, rotation and scale at ``t``, one row per driven slot.

        Each array lines up with the matching ``slots_*``. The rows are the
        sampler's own storage where a channel never moves, so a caller reads
        them and copies before writing.
        """
        return (self._paths['translation'].sample(t),
                self._paths['rotation'].sample(t),
                self._paths['scale'].sample(t))

    def sample_many(self, times: Any) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Translation, rotation and scale at each of ``times``.

        Each array is ``(F, C, W)``: one row of driven slots per time, in the
        order of the matching ``slots_*``. This is what a crowd asks -- many
        bodies playing this clip, each at its own point in it.
        """
        times = np.asarray(times, dtype='d').ravel()
        return (self._paths['translation'].sample_many(times),
                self._paths['rotation'].sample_many(times),
                self._paths['scale'].sample_many(times))

    def sample_weights(self, t: float) -> Dict[int, np.ndarray]:
        """Morph weights at ``t``, by glTF node index.

        Morph weights are per mesh and of no fixed width, so they are answered
        beside the skeleton's arrays rather than in them.
        """
        return {node: sampler.evaluate(t) for node, sampler in self._weights}


def _widen(values: np.ndarray, width: int) -> np.ndarray:
    """Values as ``(keys, width)``, padding a narrow row rather than failing.

    Content is not always well formed, and a translation channel written three
    wide where the reader wants four should cost the missing component, not
    the clip.
    """
    array = np.ascontiguousarray(values, dtype='d')
    if array.ndim == 1:
        array = array.reshape(1, -1)
    if array.shape[-1] == width:
        return array
    out = np.zeros(array.shape[:-1] + (width,), dtype='d')
    keep = min(width, array.shape[-1])
    out[..., :keep] = array[..., :keep]
    return out


def _constant_value(sampler: Any) -> Optional[np.ndarray]:
    """The one value a channel holds for its whole length, or None.

    A cubic channel is never constant even where its key values are equal: its
    tangents carry the curve between them.
    """
    if sampler.interpolation == 'CUBICSPLINE':
        return None
    values = sampler.values
    if len(values) == 0:
        return None
    if len(values) == 1 or np.array_equal(values, np.repeat(values[:1], len(values), 0)):
        return np.asarray(values[0], dtype='d')
    return None
