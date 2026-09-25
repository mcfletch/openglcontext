"""What the zones in a scene say about one draw, one camera or one listener.

The PBR pass asks three kinds of question of the scene's zones, and the
answers are worked out here, with no GL, from the zones
:func:`~OpenGLContext.scenegraph.zone.placed_zones` placed for the frame:

* For a draw, which zones' environments reach the object and how. An object
  wholly inside a zone takes it as a constant; one crossing a zone's
  surface, or its blend band, has the zone weighted per fragment by
  ``_zone_inc.glsl``. The answer is packed into the arrays that shader reads
  (:class:`ZonePack`). The pass asks this of many objects at once through a
  :class:`ZoneTable` (:meth:`ZoneTable.classify_many`, then :func:`stacked`,
  :func:`chosen` and :func:`pack_reach`); :func:`environment_layers` is the
  same for one object.
* For a draw, which of the lights zones control are off: :func:`light_decision`
  from what the table answers, then :func:`light_mask`; :func:`lights_off`
  is the same for one object.
* For a camera or a listener, how much of each thing a zone switches on is on
  (:func:`camera_shares`), and what reverb it hears (:func:`reverb_at`).

A draw's answers are what the pass caches per object: they change only when
the object or a zone moves.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import (Any, Callable, Dict, FrozenSet, Hashable, Iterable, List,
                    Mapping, Optional, Sequence, Set, Tuple)

import numpy as np

from OpenGLContext.scenegraph import zones
from OpenGLContext.scenegraph.zone import (
    ENVIRONMENT, LIGHTS, REVERB, PlacedZone, ZoneEnvironment,
)

log = logging.getLogger(__name__)

__all__ = [
    'MAX_ZONE_LAYERS', 'SCENE_PROBE', 'NO_ENVIRONMENT', 'ZonePack', 'ZoneTable',
    'ObjectBoxes', 'world_reach',
    'Reach', 'reach', 'classified', 'stacked', 'chosen', 'probe_layers', 'pack_reach',
    'environment_layers', 'lights_off', 'light_decision', 'light_mask',
    'controlled_lights', 'point_weights', 'camera_shares',
    'reverb_at', 'Reverb',
]

#: How many zones one draw can be reached by, which is the length of the
#: arrays in ``_zone_inc.glsl``. One is the zone the object is wholly inside,
#: and the rest are zones it crosses; a draw crossing more than that keeps the
#: ones nearest the camera.
MAX_ZONE_LAYERS = 4

#: A layer's probe index where it reads the scene's environment.
SCENE_PROBE = -1.0
#: A layer's probe index where it has no environment at all: a zone whose
#: probe is being captured for the first time, inside that capture.
NO_ENVIRONMENT = -2.0


@dataclass(frozen=True)
class ZonePack:
    """The zone arrays ``_zone_inc.glsl`` reads, for one draw.

    ``kinds`` holds each layer's shape (0 where the object is wholly inside,
    so the layer is a constant), ``to_local`` the world-to-shape matrices,
    row-vector as the engine's are, ``shape`` the dimensions, and ``light``
    each layer's intensity, blend and probe layer. ``key`` compares equal
    for two packs that would upload the same values; it holds each layer's
    :class:`~OpenGLContext.scenegraph.zone.PlacedZone`, which stands for one
    placement of one zone.
    """

    count: int
    kinds: np.ndarray
    to_local: np.ndarray
    shape: np.ndarray
    light: np.ndarray
    key: Tuple[Any, ...]
    #: Whether more zones crossed the object than there are layers, so which
    #: were kept depends on where the camera is.
    limited: bool = False


def _params(placed: zones.PlacedShape) -> Tuple[float, float, float, float]:
    values = tuple(placed.params) + (0.0, 0.0, 0.0)
    if placed.kind == zones.SPHERE:
        return (values[0], 0.0, 0.0, 0.0)
    return (float(values[0]), float(values[1]), float(values[2]), 0.0)


def _pack(stack: Sequence[Tuple[PlacedZone, bool, float, float]],
          limited: bool = False) -> ZonePack:
    """``stack`` is bottom first: (zone, wholly inside, intensity, probe layer)."""
    kinds = np.zeros(MAX_ZONE_LAYERS, dtype=np.int32)
    to_local = np.zeros((MAX_ZONE_LAYERS, 4, 4), dtype=np.float32)
    shape = np.zeros((MAX_ZONE_LAYERS, 4), dtype=np.float32)
    light = np.zeros((MAX_ZONE_LAYERS, 4), dtype=np.float32)
    key = []
    for index, (placed, inside, intensity, probe) in enumerate(stack):
        kinds[index] = 0 if inside else zones.shader_kind(placed.shape.kind)
        to_local[index] = placed.shape.to_local
        shape[index] = _params(placed.shape)
        light[index] = (intensity, placed.blend, probe, 0.0)
        key.append((placed, inside, intensity, probe))
    return ZonePack(len(stack), kinds, to_local, shape, light, tuple(key), limited)


def world_reach(placed: PlacedZone) -> Tuple[np.ndarray, np.ndarray]:
    """The world box round ``placed``'s shape and its blend band, as ``(low, high)``."""
    low, high = _world_boxes(placed.shape.to_local[None],
                             (np.asarray(placed.shape.reach, 'd') + placed.blend)[None])
    return low[0], high[0]


def _world_boxes(to_local: np.ndarray, reach: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """``(Z, 3)`` world boxes of oriented boxes of half extents ``reach``."""
    if not len(to_local):
        return np.zeros((0, 3)), np.zeros((0, 3))
    to_world = np.linalg.inv(to_local)
    middle = to_world[:, 3, :3]
    spread = (np.abs(to_world[:, :3, :3]) * reach[:, :, None]).sum(axis=1)
    return middle - spread, middle + spread


class ZoneTable:
    """A frame's zones stacked for testing against many of them at once.

    Classifying an object against each zone one at a time costs several numpy
    calls a zone, which a world of fifty zones along a road pays for every
    object that spans them. :meth:`classify_many` answers for many objects
    and zones in one pass: the conservative clear-of-it test
    :meth:`~OpenGLContext.scenegraph.zones.PlacedShape.classify` makes first,
    and for boxes -- what a world's zones mostly are -- the exact inside test
    too. :meth:`signed_distances` gives every zone's distance from points the
    same way. Other shapes are measured one at a time.
    """

    #: How far from a sphere :meth:`sphere_slack` looks for zones, in metres.
    #: A zone further away than this leaves the sphere at least this much
    #: room, less its radius, so the slack answered is never more than that.
    slack_reach = 60.0

    #: How many boxes :meth:`classify_many` carries through at once, which
    #: bounds the memory one call takes whatever it is asked.
    chunk = 512

    def __init__(self, placed: Sequence[PlacedZone]) -> None:
        self.placed = list(placed)
        count = len(self.placed)
        self.to_local = np.zeros((count, 4, 4), dtype='d')
        self.reach = np.zeros((count, 3), dtype='d')
        self.half = np.zeros((count, 3), dtype='d')
        self.box = np.zeros(count, dtype=bool)
        self.blend = np.array([zone.blend for zone in self.placed], dtype='d')
        for index, zone in enumerate(self.placed):
            self.to_local[index] = zone.shape.to_local
            self.reach[index] = np.asarray(zone.shape.reach, 'd') + zone.blend
            if zone.shape.kind == zones.BOX:
                self.box[index] = True
                self.half[index] = zone.shape.params
        # Each zone's reach -- its shape and its blend band -- as a box in the
        # world, so the zones a query could touch are found before any point
        # is carried into a zone's frame.
        self.world_low, self.world_high = _world_boxes(self.to_local, self.reach)
        # The physics engine's broad phase: a query costs the depth of the
        # tree rather than a comparison with every zone.
        from omi_physics.broadphase import DynamicAABBTree
        self._tree = DynamicAABBTree(fatten=0.0)
        for index in range(count):
            self._tree.insert(index, self.world_low[index], self.world_high[index])

    def near(self, minimum: Any, maximum: Any) -> np.ndarray:
        """The indices of the zones whose reach overlaps the world box given, in order."""
        found = self._tree.query(np.asarray(minimum, dtype='d'),
                                 np.asarray(maximum, dtype='d'))
        return np.array(sorted(found), dtype=np.intp)

    def _local_to(self, which: Any, points: np.ndarray) -> np.ndarray:
        """``(N, 3)`` world points in the frames of the zones ``which``, as ``(W, N, 3)``.

        A broadcast matrix product, which numpy hands to BLAS, rather than an
        ``einsum``, which it does not.
        """
        matrices = self.to_local[which]
        found: np.ndarray = (
            np.matmul(np.asarray(points, dtype='d')[None, :, :], matrices[:, :3, :3])
            + matrices[:, None, 3, :3])
        return found

    def classify(self, minimum: Any, maximum: Any) -> List[Tuple[PlacedZone, bool]]:
        """Each zone the box reaches, with whether the box is wholly inside it."""
        return self.classify_many([minimum], [maximum])[0]

    def classify_many(self, minimums: Any, maximums: Any
                      ) -> List[List[Tuple[PlacedZone, bool]]]:
        """:meth:`classify` for many boxes at once: ``(M, 3)`` corners each.

        The boxes are taken :attr:`chunk` at a time, and each chunk is
        carried into the frames of only the zones whose world reach overlaps
        one of its boxes, so what one call holds is bounded by the chunk and
        the zones near it rather than by every box against every zone.
        """
        low_in = np.asarray(minimums, dtype='d').reshape(-1, 3)
        high_in = np.asarray(maximums, dtype='d').reshape(-1, 3)
        if not self.placed:
            return [[] for _ in range(len(low_in))]
        found: List[List[Tuple[PlacedZone, bool]]] = []
        for start in range(0, len(low_in), self.chunk):
            found.extend(self._classify_chunk(low_in[start:start + self.chunk],
                                              high_in[start:start + self.chunk]))
        return found

    def _classify_chunk(self, low_in: np.ndarray, high_in: np.ndarray
                        ) -> List[List[Tuple[PlacedZone, bool]]]:
        count = len(low_in)
        # Which world reach each box overlaps, as (M, Z): what is carried
        # through is only the zones some box of the chunk is near.
        overlaps = (np.all(low_in[:, None, :] <= self.world_high[None], axis=2)
                    & np.all(high_in[:, None, :] >= self.world_low[None], axis=2))
        which = np.flatnonzero(overlaps.any(axis=0))
        if not len(which):
            return [[] for _ in range(count)]
        corners = np.where(zones._CORNER_ENDS[None, :, :], high_in[:, None, :],
                           low_in[:, None, :])                         # (M, 8, 3)
        local = self._local_to(which, corners.reshape(-1, 3))          # (W, M*8, 3)
        # Corners leading, since numpy reduces a short trailing axis slowly.
        local = local.reshape(len(which), count, 8, 3).transpose(2, 1, 0, 3)
        low, high = local.min(axis=0), local.max(axis=0)               # (M, W, 3)
        reach = self.reach[which][None]
        near = (overlaps[:, which]
                & ~(np.any(low > reach, axis=2) | np.any(high < -reach, axis=2)))
        half = self.half[which][None]
        inside = np.all(low >= -half, axis=2) & np.all(high <= half, axis=2)
        found: List[List[Tuple[PlacedZone, bool]]] = [[] for _ in range(count)]
        rows, columns = np.nonzero(near)
        for row, at in zip(rows.tolist(), columns.tolist(), strict=True):
            index = which[at]
            zone = self.placed[index]
            if self.box[index]:
                within = bool(inside[row, at])
            else:
                within = bool(np.all(zones._distance(
                    zone.shape.kind, zone.shape.params, local[:, row, at]) <= 0.0))
            found[row].append((zone, within))
        return found

    def signed_distances(self, points: Any) -> np.ndarray:
        """Every zone's signed distance from each of ``(M, 3)`` points, as ``(M, Z)``."""
        points = np.asarray(points, dtype='d').reshape(-1, 3)
        if not self.placed:
            return np.zeros((len(points), 0))
        return self._signed(np.arange(len(self.placed)), points)

    def _signed(self, which: np.ndarray, points: np.ndarray) -> np.ndarray:
        """The zones ``which``'s signed distances from ``points``, as ``(M, W)``."""
        local = self._local_to(which, points)                        # (W, M, 3)
        q = np.abs(local) - self.half[which][:, None, :]
        found: np.ndarray = (np.linalg.norm(np.maximum(q, 0.0), axis=2)
                             + np.minimum(q.max(axis=2), 0.0)).T     # (M, W)
        for at in np.flatnonzero(~self.box[which]):
            zone = self.placed[which[at]]
            found[:, at] = zones._distance(zone.shape.kind, zone.shape.params,
                                           local[at])
        return found

    def sphere_slack(self, centres: Any, radii: Any) -> np.ndarray:
        """How far each sphere may move before its classification could change.

        For a sphere outside a zone, the room between it and the zone's blend
        band; for one inside, the room between it and the zone's surface; the
        least over every zone, and nought for a sphere already across one.
        An object that has moved less than this since it was classified,
        turned however it likes within its bounding sphere, is where it was as
        far as every zone can tell.

        Only the zones within :attr:`slack_reach` of the spheres are measured;
        the rest leave at least that much room, so the answer is never more
        than :attr:`slack_reach` less the radius.
        """
        centres = np.asarray(centres, dtype='d').reshape(-1, 3)
        radii = np.asarray(radii, dtype='d').reshape(-1)
        reach = float(self.slack_reach)
        if not self.placed:
            return np.full(len(centres), np.inf)
        limit: np.ndarray
        if np.isfinite(reach):
            which = self.near(centres.min(axis=0) - reach, centres.max(axis=0) + reach)
            limit = np.maximum(reach - radii, 0.0)
        else:
            which = np.arange(len(self.placed))
            limit = np.full(len(centres), np.inf)
        if not len(which):
            return limit
        d = self._signed(which, centres)
        blend = self.blend[which][None, :]
        # What decides a classification is which side of two lines a sphere
        # is: the shape's surface and the outer edge of its blend band. Its
        # room is the distance to the nearer of them, less its radius.
        room = np.where(d > blend, d - blend,
                        np.where(d > 0.0, np.minimum(d, blend - d), -d)) - radii[:, None]
        slack: np.ndarray = np.minimum(np.maximum(room.min(axis=1), 0.0), limit)
        return slack

    def nearness(self, point: Any) -> Dict[PlacedZone, float]:
        """Every zone's signed distance from ``point``, by zone, in one pass."""
        found = self.signed_distances(np.asarray(point, dtype='d')[:3])[0]
        return dict(zip(self.placed, found.tolist(), strict=True))


class ObjectBoxes:
    """Where each object's classification holds, for finding those a change reaches.

    Each object the pass has classified is given a row: the world box within
    which its answer stays true -- its own box, grown to the sphere its slack
    lets it move in. When a zone moves, or anything about it changes,
    :meth:`overlapping` answers the objects whose row overlaps the zone's
    reach before and after, which are the only ones whose answer can have
    changed. No GL.
    """

    def __init__(self, capacity: int = 256) -> None:
        self.low = np.full((capacity, 3), np.inf)
        self.high = np.full((capacity, 3), -np.inf)
        self.owners: List[Any] = [None] * capacity
        self._free: List[int] = []
        self._used = 0

    def __len__(self) -> int:
        return self._used - len(self._free)

    def place(self, row: Optional[int], owner: Any, low: Any, high: Any) -> int:
        """Put ``owner``'s box in ``row``, or in a new row; return the row."""
        if row is None:
            row = self._free.pop() if self._free else self._grow()
        self.low[row] = low
        self.high[row] = high
        self.owners[row] = owner
        return row

    def _grow(self) -> int:
        row = self._used
        if row == len(self.owners):
            capacity = 2 * len(self.owners)
            self.low = np.concatenate([self.low, np.full((capacity - row, 3), np.inf)])
            self.high = np.concatenate([self.high, np.full((capacity - row, 3), -np.inf)])
            self.owners.extend([None] * (capacity - row))
        self._used += 1
        return row

    def drop(self, row: int) -> None:
        """Let ``row`` go, for another object to take."""
        self.low[row] = np.inf
        self.high[row] = -np.inf
        self.owners[row] = None
        self._free.append(row)

    def clear(self) -> None:
        """Let every row go."""
        self.low[:] = np.inf
        self.high[:] = -np.inf
        self.owners = [None] * len(self.owners)
        self._free = []
        self._used = 0

    def overlapping(self, low: Any, high: Any) -> List[Any]:
        """The owner of every row whose box overlaps the world box ``[low, high]``."""
        used = self._used
        hit = (np.all(self.low[:used] <= np.asarray(high, 'd'), axis=1)
               & np.all(self.high[:used] >= np.asarray(low, 'd'), axis=1))
        return [self.owners[row] for row in np.flatnonzero(hit).tolist()]


@dataclass(frozen=True)
class Reach:
    """Which environment zones reach one object, bottom first, and how.

    ``stack`` pairs each zone with whether the object is wholly inside it.
    ``limited`` is set where more zones crossed the object than the shader
    has layers for, so which were kept depends on where the camera is.
    What an object's zones are does not change until it or a zone moves; what
    each zone's probe is may change every frame a capture finishes, so the two
    are worked out apart (:func:`reach`, then :func:`pack_reach`).
    """

    stack: Tuple[Tuple[PlacedZone, bool], ...]
    limited: bool = False


def stacked(reaching: List[Tuple[PlacedZone, bool]]) -> List[Tuple[PlacedZone, bool]]:
    """``reaching`` stacked bottom first, with nothing under a zone it fills."""
    reaching = sorted(reaching, key=lambda item: (item[0].priority, -item[0].volume))
    base = 0
    for index, (_zone, inside) in enumerate(reaching):
        if inside:
            base = index
    return reaching[base:]


def classified(placed: Sequence[PlacedZone], minimum: Any, maximum: Any,
               table: Optional[ZoneTable] = None) -> List[Tuple[PlacedZone, bool]]:
    """Every environment zone reaching the box, bottom first, none under one it fills.

    Each zone reaching the box is paired with whether the box is wholly
    inside it. They are stacked by priority and size, and everything below
    the topmost zone the box is wholly inside is dropped, since that zone
    covers the whole object. Nothing here depends on the camera, so the answer
    holds until the object or a zone moves. ``table`` is a :class:`ZoneTable`
    of the same zones, which answers for all of them in one pass.
    """
    if table is not None:
        return stacked(table.classify(minimum, maximum))
    return stacked(_reaching(placed, ENVIRONMENT, minimum, maximum))


def _reaching(placed: Sequence[PlacedZone], key: str, minimum: Any, maximum: Any
              ) -> List[Tuple[PlacedZone, bool]]:
    """Each zone with a ``key`` setting the box reaches, with whether it is inside."""
    found = []
    for zone in placed:
        if zone.setting(key) is None:
            continue
        where = zone.shape.classify(minimum, maximum, zone.blend)
        if where != zones.OUTSIDE:
            found.append((zone, where == zones.INSIDE))
    return found


def chosen(kept: Sequence[Tuple[PlacedZone, bool]], camera: Optional[Any] = None,
           warn: Optional[Callable[[str], None]] = None,
           table: Optional[ZoneTable] = None,
           near: Optional[Dict[PlacedZone, float]] = None) -> Optional[Reach]:
    """The layers the shader is given from :func:`classified`'s answer.

    All of them where they fit. Where more zones reach the object than the
    shader has room for, the one it is wholly inside stays where there is
    one, the rest of the room goes to the zones nearest ``camera``, and
    ``warn`` is told. ``near`` is the table's
    :meth:`ZoneTable.nearness` for ``camera`` where the caller already has
    it -- one answer serves every object drawn from that camera. None where
    no zone reaches the object.
    """
    if not kept:
        return None
    if len(kept) <= MAX_ZONE_LAYERS:
        return Reach(tuple(kept), False)
    # stacked() leaves a zone the object is wholly inside at the bottom.
    head = list(kept[:1]) if kept[0][1] else []
    rest = list(kept[len(head):])
    room = MAX_ZONE_LAYERS - len(head)
    if warn is not None:
        warn('an object crosses %d zones; the %d nearest the camera are kept'
             % (len(rest), room))
    if camera is not None:
        point = np.asarray(camera, dtype='d')[:3]
        if near is None and table is not None:
            near = table.nearness(point)
        if near is not None:
            rest.sort(key=lambda item: near.get(item[0], 0.0))
        else:
            rest.sort(key=lambda item: float(item[0].shape.distance(point)))
    rest = rest[:room]
    rest.sort(key=lambda item: (item[0].priority, -item[0].volume))
    return Reach(tuple(head + rest), True)


def reach(placed: Sequence[PlacedZone], minimum: Any, maximum: Any,
          camera: Optional[Any] = None,
          warn: Optional[Callable[[str], None]] = None,
          table: Optional[ZoneTable] = None) -> Optional[Reach]:
    """The environment zones reaching an object: :func:`classified`, then :func:`chosen`.

    Returns None where no zone reaches the object, which is every object in a
    scene with no zones.
    """
    return chosen(classified(placed, minimum, maximum, table), camera, warn, table)


def probe_layers(found: Reach, probe_layer: Callable[[PlacedZone], float]
                 ) -> Tuple[float, ...]:
    """Each reaching zone's probe layer, as ``probe_layer`` answers it now."""
    return tuple(float(probe_layer(zone)) if _lit(zone) else NO_ENVIRONMENT
                 for zone, _inside in found.stack)


def pack_reach(found: Reach, layers: Sequence[float]) -> ZonePack:
    """The shader's arrays for ``found``, with each zone's probe from ``layers``."""
    stack = []
    for (zone, inside), layer in zip(found.stack, layers, strict=True):
        setting = zone.setting(ENVIRONMENT)
        intensity = (max(float(setting.intensity), 0.0)
                     if isinstance(setting, ZoneEnvironment) and bool(setting.enabled)
                     else 0.0)
        stack.append((zone, inside, intensity, float(layer)))
    return _pack(stack, found.limited)


def _lit(zone: PlacedZone) -> bool:
    setting = zone.setting(ENVIRONMENT)
    return isinstance(setting, ZoneEnvironment) and bool(setting.enabled)


def environment_layers(placed: Sequence[PlacedZone], minimum: Any, maximum: Any,
                       probe_layer: Callable[[PlacedZone], float],
                       camera: Optional[Any] = None,
                       warn: Optional[Callable[[str], None]] = None,
                       table: Optional[ZoneTable] = None,
                       ) -> Optional[ZonePack]:
    """The environment layers reaching an object, packed for the shader.

    :func:`reach` and :func:`pack_reach` together. ``probe_layer`` says which
    probe layer a zone reads: :data:`SCENE_PROBE` for the scene's own
    environment, :data:`NO_ENVIRONMENT`, or an array layer. A zone whose
    setting is not enabled keeps its place in the stack with no environment
    at all. Returns None where no zone reaches the object.
    """
    found = reach(placed, minimum, maximum, camera, warn, table)
    if found is None:
        return None
    return pack_reach(found, probe_layers(found, probe_layer))


def controlled_lights(placed: Iterable[PlacedZone]) -> Dict[Any, List[PlacedZone]]:
    """Each light node a zone names, with the zones that name it."""
    found: Dict[Any, List[PlacedZone]] = {}
    for zone in placed:
        setting = zone.setting(LIGHTS)
        if setting is None or not bool(setting.enabled):
            continue
        for light in getattr(setting, 'lights', None) or ():
            found.setdefault(light, []).append(zone)
    return found


def light_decision(reaching: Sequence[Tuple[PlacedZone, bool]]
                   ) -> Tuple[FrozenSet[Any], bool]:
    """Which lights the zones switch on for an object, and whether they darken it.

    ``reaching`` is each zone with a lights setting that reaches the object,
    with whether the object is wholly inside it, as
    :meth:`ZoneTable.classify` answers for a table of those zones. The first
    part of the answer is every light node a zone reaching the object
    names, among the zones at or above the topmost one it is wholly
    inside (that one covers the whole object); the second is whether the
    object is wholly inside a zone that switches the lights off. A zone the
    object only crosses switches no light off for it. Neither depends on
    which slot a light is bound to, so it holds until the object or a zone
    moves.
    """
    on: Set[Any] = set()
    dark = False
    for zone, inside in stacked(list(reaching)):
        setting = zone.setting(LIGHTS)
        if setting is None or not bool(setting.enabled):
            dark = dark or inside
            continue
        on.update(getattr(setting, 'lights', None) or ())
    return frozenset(on), dark


def light_mask(decision: Tuple[FrozenSet[Any], bool], slots: Sequence[Any],
               controlled: Mapping[Any, List[PlacedZone]]) -> int:
    """The ``lightsOff`` mask from :func:`light_decision`, for the lights in ``slots``."""
    on, dark = decision
    mask = 0
    for slot, light in enumerate(slots):
        if light in controlled:
            if light not in on:
                mask |= 1 << slot
        elif dark:
            mask |= 1 << slot
    return mask


def lights_off(placed: Sequence[PlacedZone], minimum: Any, maximum: Any,
               slots: Sequence[Any], controlled: Mapping[Any, List[PlacedZone]]) -> int:
    """The ``lightsOff`` mask for an object: one bit per light slot that does not light it.

    ``slots`` is the light node bound to each slot, in slot order. A light a
    zone names lights the object where the object reaches one of those zones
    and is not wholly inside a higher zone that decides the lights otherwise.
    Where the object is wholly inside a zone that switches the lights off,
    every light no zone names is off too.
    """
    return light_mask(light_decision(_reaching(placed, LIGHTS, minimum, maximum)),
                      slots, controlled)


def point_weights(table: ZoneTable, point: Any) -> Dict[PlacedZone, float]:
    """Every zone's weight at ``point``, by zone, in one pass."""
    if not table.placed:
        return {}
    d = table.signed_distances(np.asarray(point, dtype='d')[:3])[0]
    w = zones.weight(d, table.blend)
    return dict(zip(table.placed, w.tolist(), strict=True))


def camera_shares(placed: Sequence[PlacedZone], point: Any, key: str,
                  names: Callable[[Any], Iterable[Hashable]],
                  weights: Optional[Dict[PlacedZone, float]] = None) -> Dict[Hashable, float]:
    """How much each thing zones switch on for ``key`` is on, at ``point``.

    ``names`` gives the things a setting names -- emitters, nodes, mirrors.
    Something no zone at ``point`` names is at nought, so the answer holds
    only what some zone names; the caller treats anything a zone names
    anywhere as off when it is missing here. ``weights`` is
    :func:`point_weights` for ``point`` where the caller has it.
    """
    candidates = []
    mapping: Dict[Hashable, List[Hashable]] = {}
    for zone in placed:
        setting = zone.setting(key)
        if setting is None:
            continue
        weight = weights[zone] if weights is not None else zone.weight(point)
        candidate = zone.candidate(key, weight)
        candidates.append(candidate)
        if candidate[1] is not None:
            mapping[candidate[0]] = list(names(setting))
    return zones.named_shares(zones.layers(candidates), mapping)


@dataclass(frozen=True)
class Reverb:
    """The reverb a listener hears: level 0 to 1, decay in seconds, damping 0 to 1.

    ``Reverb()`` is none at all, with a ``ZoneReverb``'s own decay and
    damping.
    """

    level: float = 0.0
    decay: float = 1.5
    damping: float = 0.4


def reverb_at(placed: Sequence[PlacedZone], point: Any,
              weights: Optional[Dict[PlacedZone, float]] = None,
              base: Optional[Reverb] = None) -> Reverb:
    """The reverb heard at ``point``, the zones it is in laid over ``base``.

    ``base`` is what is heard outside every zone: none where it is not
    given. The level is each zone's level times its share, and ``base``'s
    times what the zones leave, so it fades over a zone's blend. The decay
    and damping are the weighted mean of the zones' -- and of ``base``'s
    where it has a level -- so two places meet without a jump.
    """
    outside = Reverb() if base is None else base
    candidates = [zone.candidate(REVERB, weights[zone] if weights is not None
                                 else zone.weight(point))
                  for zone in placed if zone.setting(REVERB) is not None]
    stack = zones.layers(candidates)
    level = decay = damping = weight = 0.0
    for layer in stack:
        setting = layer.block
        if setting is None:
            continue
        level += layer.share * max(0.0, min(1.0, float(setting.level)))
        decay += layer.share * max(0.0, float(setting.decay))
        damping += layer.share * max(0.0, min(1.0, float(setting.damping)))
        weight += layer.share
    rest = max(0.0, 1.0 - weight)
    if outside.level > 0.0 and rest > 0.0:
        level += rest * outside.level
        decay += rest * outside.decay
        damping += rest * outside.damping
        weight += rest
    if weight <= 0.0:
        return outside
    return Reverb(level, decay / weight, damping / weight)
