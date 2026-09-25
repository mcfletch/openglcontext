"""What the zones in a scene say about one draw, one camera or one listener.

The PBR pass asks three kinds of question of the scene's zones, and the
answers are worked out here, with no GL, from the zones
:func:`~OpenGLContext.scenegraph.zone.placed_zones` placed for the frame:

* For a draw, which zones' environments reach the object and how
  (:func:`environment_layers`). An object wholly inside a zone takes it as a
  constant; one crossing a zone's surface, or its blend band, has the zone
  weighted per fragment by ``_zone_inc.glsl``. The answer is packed into the
  arrays that shader reads (:class:`ZonePack`).
* For a draw, which of the lights zones control are off (:func:`lights_off`).
* For a camera or a listener, how much of each thing a zone switches on is on
  (:func:`camera_shares`), and what reverb it hears (:func:`reverb_at`).

A draw's answers are what the pass caches per object: they change only when
the object or a zone moves.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import (Any, Callable, Dict, Hashable, Iterable, List, Optional,
                    Sequence, Tuple)

import numpy as np

from OpenGLContext.scenegraph import zones
from OpenGLContext.scenegraph.zone import (
    ENVIRONMENT, LIGHTS, REVERB, PlacedZone, ZoneEnvironment,
)

log = logging.getLogger(__name__)

__all__ = [
    'MAX_ZONE_LAYERS', 'SCENE_PROBE', 'NO_ENVIRONMENT', 'ZonePack', 'ZoneTable',
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
    for two packs that would upload the same values.
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
        key.append((id(placed), inside, intensity, probe))
    return ZonePack(len(stack), kinds, to_local, shape, light, tuple(key), limited)


class ZoneTable:
    """A frame's zones stacked for testing against many of them at once.

    Classifying an object against each zone one at a time costs several numpy
    calls a zone, which a world of fifty zones along a road pays for every
    object that spans them. :meth:`classify` answers for all of them in one
    pass: the conservative clear-of-it test
    :meth:`~OpenGLContext.scenegraph.zones.PlacedShape.classify` makes first,
    and for boxes -- what a world's zones mostly are -- the exact inside test
    too. :meth:`distances` gives every box's distance from a point the same
    way. Other shapes are measured one at a time, as before.
    """

    #: How far from a sphere :meth:`sphere_slack` looks for zones, in metres.
    #: A zone further away than this leaves the sphere at least this much
    #: room, less its radius, so the slack answered is never more than that.
    slack_reach = 60.0

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
        if count:
            to_world = np.linalg.inv(self.to_local)
            middle = to_world[:, 3, :3]
            spread = (np.abs(to_world[:, :3, :3]) * self.reach[:, :, None]).sum(axis=1)
            self.world_low, self.world_high = middle - spread, middle + spread
        else:
            self.world_low = self.world_high = np.zeros((0, 3))
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

    def _local(self, points: np.ndarray) -> np.ndarray:
        """``(N, 3)`` world points in every zone's frame, as ``(Z, N, 3)``."""
        return self._local_to(slice(None), points)

    def reaching(self, minimum: Any, maximum: Any) -> List[PlacedZone]:
        """The zones whose shape, or blend band, the box may reach."""
        return [zone for zone, _inside in self.classify(minimum, maximum)]

    def classify(self, minimum: Any, maximum: Any) -> List[Tuple[PlacedZone, bool]]:
        """Each zone the box reaches, with whether the box is wholly inside it."""
        return self.classify_many([minimum], [maximum])[0]

    def classify_many(self, minimums: Any, maximums: Any
                      ) -> List[List[Tuple[PlacedZone, bool]]]:
        """:meth:`classify` for many boxes at once: ``(M, 3)`` corners each.

        One pass for every box against every zone, which is how the objects
        that moved since the last frame are classified together rather than
        one numpy call apiece.
        """
        low_in = np.asarray(minimums, dtype='d').reshape(-1, 3)
        high_in = np.asarray(maximums, dtype='d').reshape(-1, 3)
        if not self.placed or not len(low_in):
            return [[] for _ in range(len(low_in))]
        # Only the zones whose reach overlaps the boxes together are carried
        # through; a world's zones are strung out along its roads, and an
        # object is near few of them.
        which = self.near(low_in.min(axis=0), high_in.max(axis=0))
        if not len(which):
            return [[] for _ in range(len(low_in))]
        corners = np.where(zones._CORNER_ENDS[None, :, :], high_in[:, None, :],
                           low_in[:, None, :])                         # (M, 8, 3)
        count = len(low_in)
        local = self._local_to(which, corners.reshape(-1, 3))          # (W, M*8, 3)
        # Corners leading, since numpy reduces a short trailing axis slowly.
        local = local.reshape(len(which), count, 8, 3).transpose(2, 1, 0, 3)
        low, high = local.min(axis=0), local.max(axis=0)               # (M, W, 3)
        reach = self.reach[which][None]
        clear = np.any(low > reach, axis=2) | np.any(high < -reach, axis=2)
        half = self.half[which][None]
        inside_box = (np.all(low >= -half, axis=2) & np.all(high <= half, axis=2))
        found: List[List[Tuple[PlacedZone, bool]]] = []
        for row in range(count):
            mine = []
            for at in np.flatnonzero(~clear[row]):
                index = which[at]
                zone = self.placed[index]
                if self.box[index]:
                    inside = bool(inside_box[row, at])
                else:
                    inside = bool(np.all(zones._distance(
                        zone.shape.kind, zone.shape.params, local[:, row, at]) <= 0.0))
                mine.append((zone, inside))
            found.append(mine)
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

    def nearness(self, point: Any) -> Dict[int, float]:
        """Every zone's signed distance from ``point``, by ``id``, in one pass."""
        found = self.signed_distances(np.asarray(point, dtype='d')[:3])[0]
        if '_ids' not in self.__dict__:
            self._ids = [id(zone) for zone in self.placed]
        return dict(zip(self._ids, found.tolist(), strict=True))

    def distances(self, point: Any) -> Dict[int, float]:
        """Every zone's signed distance from ``point``, by ``id`` of the zone."""
        if not self.placed:
            return {}
        local = self._local(np.asarray(point, dtype='d')[:3][None, :])[:, 0, :]
        q = np.abs(local) - self.half
        boxed = (np.linalg.norm(np.maximum(q, 0.0), axis=1)
                 + np.minimum(q.max(axis=1), 0.0))
        found = {}
        for index, zone in enumerate(self.placed):
            found[id(zone)] = (float(boxed[index]) if self.box[index]
                               else float(zone.shape.distance(point)))
        return found


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
        reaching = table.classify(minimum, maximum)
    else:
        reaching = []
        for zone in placed:
            if zone.setting(ENVIRONMENT) is None:
                continue
            where = zone.shape.classify(minimum, maximum, zone.blend)
            if where != zones.OUTSIDE:
                reaching.append((zone, where == zones.INSIDE))
    return stacked(reaching)


def chosen(kept: Sequence[Tuple[PlacedZone, bool]], camera: Optional[Any] = None,
           warn: Optional[Callable[[str], None]] = None,
           table: Optional[ZoneTable] = None,
           near: Optional[Dict[int, float]] = None) -> Optional[Reach]:
    """The layers the shader is given from :func:`classified`'s answer.

    All of them where they fit. Where more zones cross the object than the
    shader has room for, the one it is inside stays, the others nearest
    ``camera`` are kept, and ``warn`` is told. ``near`` is the table's
    :meth:`ZoneTable.nearness` for ``camera`` where the caller already has
    it -- one answer serves every object drawn from that camera. None where
    no zone reaches the object.
    """
    if not kept:
        return None
    if len(kept) <= MAX_ZONE_LAYERS:
        return Reach(tuple(kept), False)
    if warn is not None:
        warn('an object crosses %d zones; the %d nearest the camera are kept'
             % (len(kept) - 1, MAX_ZONE_LAYERS - 1))
    head, rest = list(kept[:1]), list(kept[1:])
    if camera is not None:
        point = np.asarray(camera, dtype='d')[:3]
        if near is None and table is not None:
            near = table.nearness(point)
        if near is not None:
            rest.sort(key=lambda item: near.get(id(item[0]), 0.0))
        else:
            rest.sort(key=lambda item: float(item[0].shape.distance(point)))
    rest = rest[:MAX_ZONE_LAYERS - 1]
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
        intensity = max(float(setting.intensity), 0.0) if _lit(zone) else 0.0
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


def controlled_lights(placed: Iterable[PlacedZone]) -> Dict[int, List[PlacedZone]]:
    """Each light a zone names, by ``id``, with the zones that name it."""
    found: Dict[int, List[PlacedZone]] = {}
    for zone in placed:
        setting = zone.setting(LIGHTS)
        if setting is None or not bool(setting.enabled):
            continue
        for light in getattr(setting, 'lights', None) or ():
            found.setdefault(id(light), []).append(zone)
    return found


def light_decision(placed: Sequence[PlacedZone], minimum: Any, maximum: Any
                   ) -> Tuple[frozenset, bool]:
    """Which lights the zones switch on for an object, and whether they darken it.

    The first is the ``id`` of every light a zone reaching the object names,
    among the zones at or above the topmost one it is wholly inside (that one
    covers the whole object); the second whether the object is wholly inside
    a zone that switches the lights off. Neither depends on which slot a light
    is bound to, so it holds until the object or a zone moves.
    """
    reaching: List[Tuple[PlacedZone, bool]] = []
    for zone in placed:
        if zone.setting(LIGHTS) is None:
            continue
        where = zone.shape.classify(minimum, maximum, zone.blend)
        if where != zones.OUTSIDE:
            reaching.append((zone, where == zones.INSIDE))
    on: set = set()
    dark = False
    for zone, inside in stacked(reaching):
        setting = zone.setting(LIGHTS)
        if not bool(setting.enabled):
            dark = dark or inside
            continue
        on.update(id(light) for light in getattr(setting, 'lights', None) or ())
    return frozenset(on), dark


def light_mask(decision: Tuple[frozenset, bool], slots: Sequence[Any],
               controlled: Dict[int, List[PlacedZone]]) -> int:
    """The ``lightsOff`` mask from :func:`light_decision`, for the lights in ``slots``."""
    on, dark = decision
    mask = 0
    for slot, light in enumerate(slots):
        key = id(light)
        if key in controlled:
            if key not in on:
                mask |= 1 << slot
        elif dark:
            mask |= 1 << slot
    return mask


def lights_off(placed: Sequence[PlacedZone], minimum: Any, maximum: Any,
               slots: Sequence[Any], controlled: Dict[int, List[PlacedZone]]) -> int:
    """The ``lightsOff`` mask for an object: one bit per light slot that does not light it.

    ``slots`` is the light node bound to each slot, in slot order. A light a
    zone names lights the object where the object reaches one of those zones
    and is not wholly inside a higher zone that decides the lights otherwise.
    Where the object is wholly inside a zone that switches the lights off,
    every light no zone names is off too.
    """
    return light_mask(light_decision(placed, minimum, maximum), slots, controlled)


def point_weights(table: ZoneTable, point: Any) -> Dict[int, float]:
    """Every zone's weight at ``point``, by ``id`` of the zone, in one pass."""
    if not table.placed:
        return {}
    d = table.signed_distances(np.asarray(point, dtype='d')[:3])[0]
    blend = np.array([zone.blend for zone in table.placed])
    t = np.clip(np.where(blend > 0.0, d / np.maximum(blend, 1e-12), np.where(d > 0.0, 1.0, 0.0)),
                0.0, 1.0)
    w = np.where(d <= 0.0, 1.0, 1.0 - t * t * (3.0 - 2.0 * t))
    return {id(zone): float(value) for zone, value in zip(table.placed, w, strict=True)}


def camera_shares(placed: Sequence[PlacedZone], point: Any, key: str,
                  names: Callable[[Any], Iterable[Hashable]],
                  weights: Optional[Dict[int, float]] = None) -> Dict[Hashable, float]:
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
        weight = weights[id(zone)] if weights is not None else zone.weight(point)
        candidate = zone.candidate(key, weight)
        candidates.append(candidate)
        if candidate[1] is not None:
            mapping[candidate[0]] = list(names(setting))
    return zones.named_shares(zones.layers(candidates), mapping)


@dataclass(frozen=True)
class Reverb:
    """The reverb a listener hears: level 0 to 1, decay in seconds, damping 0 to 1."""

    level: float = 0.0
    decay: float = 1.2
    damping: float = 0.4


def reverb_at(placed: Sequence[PlacedZone], point: Any,
              weights: Optional[Dict[int, float]] = None) -> Reverb:
    """The reverb heard at ``point``, mixed from the zones it is in by their shares.

    The level is each zone's level times its share, so it fades in over a
    zone's blend; the decay and damping are the shares' weighted mean, so two
    places meet without a jump. Outside every zone there is none.
    """
    candidates = [zone.candidate(REVERB, weights[id(zone)] if weights is not None
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
    if weight <= 0.0:
        return Reverb()
    return Reverb(level, decay / weight, damping / weight)
