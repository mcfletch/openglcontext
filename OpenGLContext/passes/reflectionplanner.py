"""A frame's mirrors: which reflections to draw, where, and what each mirror reads.

:class:`ReflectionPlanner` is the whole of the reflection pass's decision, with
no GL in it. Each frame it is handed the frame's views; it finds the mirrors in
each view's draw list, plans each mirror's view
(:func:`~OpenGLContext.passes.reflection.plan_mirror`), asks the
:class:`~OpenGLContext.passes.reflectiontiles.ReflectionSchedule` which to draw
within the :class:`~OpenGLContext.passes.reflectiontiles.Budget`, places the
tiles with the :class:`~OpenGLContext.passes.reflectiontiles.TilePacker`, and
answers a :class:`ReflectionPlan`: the mirror views to draw and the
:class:`Lookup` every mirror in every view reads its reflection through.

A reflection belongs to one mirror seen from one view, since two views see a
mirror from two places. Its tile keeps the matrix it was drawn with, so a
reflection drawn a frame or two ago is still read in the right place, and it is
kept until its mirror leaves the view.

The pass that draws the plan is
:meth:`~OpenGLContext.passes.flateffects._FlatEffectsMixin.renderReflections`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Any, Callable, Dict, Hashable, Iterable, List, Mapping, NamedTuple, Optional,
    Sequence, Set, Tuple, Union,
)

import numpy as np

from OpenGLContext.passes import reflection
from OpenGLContext.passes.reflection import MirrorView
from OpenGLContext.passes.reflectiontiles import (
    DRIFT_TEXELS, Budget, Candidate, Packed, ReflectionSchedule, Tile, TilePacker,
)
from OpenGLContext.scenegraph.reflector import PlanarReflector

__all__ = ['ROUGH', 'SETTLE_FRAMES', 'Lookup', 'MirrorDraw', 'ReflectionPlan',
           'ReflectionPlanner']

#: Above this roughness a reflector reads blurred mip levels of its tile.
ROUGH = 0.05

#: The frames a pass takes to settle: its programs compile, its textures
#: upload and its environment probe builds, and what a mirror view draws in
#: them is not a picture to keep. A reflection drawn then is drawn again.
SETTLE_FRAMES = 2


class Lookup(NamedTuple):
    """What one mirror in one view reads its reflection through.

    ``matrix`` is world to the mirrored camera's clip space before its crop,
    sixteen floats row by row; ``transform`` takes that camera's normalised
    device coordinates into the atlas (scale x, y, offset x, y) and ``bounds``
    is the tile in atlas coordinates, half a texel in. ``normal`` is the
    mirror's plane normal in the world, which the distortion is measured
    from. ``rough`` is the material's roughness, which picks the mip level.
    ``provisional`` marks a reflection drawn while the pass settled, which a
    mirror view drawing this mirror does not read.
    """

    matrix: Tuple[float, ...]
    transform: Tuple[float, float, float, float]
    bounds: Tuple[float, float, float, float]
    normal: Tuple[float, float, float]
    distortion: float
    replace: bool
    rough: float
    provisional: bool = False


@dataclass
class MirrorDraw:
    """One mirror view to draw: whose view, which mirror, into which tile."""

    key: Hashable
    frame: Any
    record: Any
    mirror: MirrorView
    tile: Tile
    reflector: PlanarReflector


@dataclass
class ReflectionPlan:
    """What a frame draws and reads; see :class:`ReflectionPlanner`."""

    frames: Sequence[Any]
    draws: List[MirrorDraw] = field(default_factory=list)
    lookups: Dict[Hashable, Lookup] = field(default_factory=dict)
    candidates: List[Candidate] = field(default_factory=list)
    #: Whether a mirror in view shows something it should not go on showing
    #: in a still scene: a reflection drawn while the pass settled, none at
    #: all, or one its camera has moved too far from. The pass asks for
    #: another frame while this is so.
    unfinished: bool = False

    @property
    def rough(self) -> bool:
        """Whether any mirror read this frame wants the blurred mip levels."""
        return any(lookup.rough > ROUGH and not lookup.replace
                   for lookup in self.lookups.values())

    @property
    def texels(self) -> int:
        """The atlas texels this frame draws."""
        return sum(draw.tile.width * draw.tile.height for draw in self.draws)

    def lookup(self, frame: Any, record: Any) -> Optional[Lookup]:
        """What ``record``'s mirror reads in ``frame``'s view, or None."""
        return self.lookups.get(key_for(frame, record))


def key_for(frame: Any, record: Any) -> Tuple[int, int]:
    """The key one mirror in one view is held by."""
    return id(frame.view), id(record[4])


@dataclass
class _Held:
    """A tile in the atlas, and what it was drawn for."""

    view: Any
    path: Any
    mirror: MirrorView
    tile: Tile
    scale: float
    eye: np.ndarray
    drawn: int
    #: Drawn while the pass was settling, so drawn again before it is kept.
    provisional: bool = False
    #: Drawn with a mirror left out of it, so drawn again.
    redo: bool = False


@dataclass
class _Seen:
    """A mirror found in a view this frame."""

    key: Hashable
    frame: Any
    record: Any
    reflector: PlanarReflector
    mirror: MirrorView
    eye: np.ndarray
    rough: float
    held: Optional[_Held]
    valid: bool


def _material(record: Any) -> Any:
    appearance = getattr(record[5], 'appearance', None)
    return getattr(appearance, 'material', None)


def _scaled(size: Tuple[int, int], scale: float) -> Tuple[int, int]:
    return (reflection._texels(size[0] * scale), reflection._texels(size[1] * scale))


class ReflectionPlanner:
    """Each frame's mirrors, from the views' draw lists to a :class:`ReflectionPlan`."""

    def __init__(self) -> None:
        self.packer = TilePacker(0, 0)
        self.schedule = ReflectionSchedule()
        self.frame = 0
        self._held: Dict[Hashable, _Held] = {}
        #: Whether a mirror's reflection may be drawn for a camera at ``eye``:
        #: ``allowed(record, eye)``, or None where every mirror may. The pass
        #: sets it from the scene's zones; see
        #: :meth:`~OpenGLContext.passes.zonepass.ZonesMixin.mirrorAllowed`.
        self.allowed: Optional[Callable[[Any, np.ndarray], bool]] = None
        self._crowded: Set[Hashable] = set()

    def reset(self) -> None:
        """Forget every tile: the atlas they were in is gone."""
        self._held.clear()
        self.packer.resize(self.packer.width, self.packer.height)

    def redo(self, keys: Iterable[Hashable]) -> None:
        """Draw these mirrors' reflections again next frame.

        For a reflection whose view had another mirror in it with nothing yet
        to show: the next frame will have it. The reflection is still passed
        on meanwhile, since what it does show is right.
        """
        for key in keys:
            held = self._held.get(key)
            if held is not None:
                held.redo = True

    # -- finding the mirrors ----------------------------------------------
    def _seen(self, frames: Sequence[Any]) -> List[_Seen]:
        found = []
        for frame in frames:
            view = frame.view
            if getattr(getattr(view, 'style', None), 'wireframe', False):
                continue
            modelview = np.asarray(frame.modelView, 'd')
            eye = np.linalg.inv(modelview)[3, :3]
            for record in frame.toRender:
                seen = self._mirror(frame, record, eye)
                if seen is not None:
                    found.append(seen)
        return found

    def _mirror(self, frame: Any, record: Any, eye: np.ndarray) -> Optional[_Seen]:
        reflector = reflection.reflector_for(record)
        if reflector is None:
            return None
        if self.allowed is not None and not self.allowed(record, eye):
            return None
        rough = reflection.surface_roughness(_material(record))
        if rough > reflection.ROUGHEST and not reflector.replace:
            return None
        local = reflection.local_plane(record)
        if local is None:
            return None
        plane = reflection.place_plane(local, record[2])
        if plane is None:
            return None
        corners = reflection.world_corners(local, record[2])
        key = key_for(frame, record)
        held = self._held.get(key)
        if held is not None and (held.view is not frame.view or held.path is not record[4]):
            held = None
        crop = None
        if held is not None and np.allclose(held.mirror.point, plane[0], atol=1e-6) \
                and np.allclose(held.mirror.normal, plane[1], atol=1e-6):
            crop = held.mirror.crop
        else:
            held = None
        mirror = reflection.plan_mirror(plane, corners, frame.modelView,
                                        frame.projection, frame.rect,
                                        float(reflector.scale), crop=crop)
        if mirror is None:
            return None
        valid = (held is not None and not held.provisional and not held.redo
                 and mirror.crop == held.mirror.crop
                 and _scaled(mirror.size, held.scale)
                 == (held.tile.width, held.tile.height))
        return _Seen(key, frame, record, reflector, mirror, eye, rough, held, valid)

    # -- weighing them ----------------------------------------------------
    def _drift(self, seen: _Seen) -> float:
        """How far, in texels, the held tile's reflection is off for this camera."""
        held = seen.held
        if held is None:
            return 0.0
        travel = float(np.linalg.norm(seen.eye - held.eye))
        if travel == 0.0:
            return 0.0
        distance = max(float(np.linalg.norm(seen.eye - seen.mirror.point)), 1e-3)
        crop = held.mirror.crop
        texel = reflection.fov(seen.frame.projection) * (crop[3] - crop[1]) / 2.0 / held.tile.height
        return (travel / distance) / max(texel, 1e-9)

    def _candidate(self, seen: _Seen, separate: bool) -> Candidate:
        x0, y0, x1, y1 = seen.mirror.rect
        rect = seen.frame.rect
        area = (x1 - x0) * (y1 - y0) / 4.0 * float(rect[2]) * float(rect[3])
        age = None if seen.held is None else self.frame - seen.held.drawn
        return Candidate(
            key=seen.key, area=area, priority=float(seen.reflector.priority),
            interval=int(seen.reflector.interval),
            texels=seen.mirror.size[0] * seen.mirror.size[1],
            age=age, valid=seen.valid, drift=self._drift(seen) if seen.valid else 0.0,
            separate=separate)

    # -- the frame --------------------------------------------------------
    def plan(self, frames: Sequence[Any], atlas: Tuple[int, int],
             budget: Union[Budget, Callable[[], Budget]],
             separate: Callable[[Any], bool] = lambda frame: False) -> ReflectionPlan:
        """This frame's mirror views and lookups.

        ``atlas`` is the atlas's size in texels; ``budget`` is the frame's
        :class:`~OpenGLContext.passes.reflectiontiles.Budget`, or what makes
        one, asked only where a view has a mirror in it. ``separate(frame)``
        says whether a view's mirrors would also draw shapes a shared draw
        refuses.
        """
        self.frame += 1
        if (self.packer.width, self.packer.height) != tuple(atlas):
            self.packer.resize(*atlas)
            self._held.clear()
        seen = {entry.key: entry for entry in self._seen(frames)}
        if not seen:
            self._held.clear()
            self.packer.place({})
            return ReflectionPlan(frames)
        if callable(budget):
            budget = budget()
        mirrored = {id(entry.frame) for entry in seen.values()}
        separates = {id(frame): bool(separate(frame)) for frame in frames
                     if id(frame) in mirrored}
        candidates = [self._candidate(entry, separates[id(entry.frame)])
                      for entry in seen.values()]
        decisions = {decision.key: decision.scale
                     for decision in self.schedule.choose(candidates, budget)}
        weights = {c.key: c.area * max(c.priority, 0.0) for c in candidates}
        packed = self._pack(seen, decisions, weights)
        spare = max(0, int(budget.views) - len(decisions))
        for key in packed.moved:
            held_before = seen[key].held
            if key in decisions or held_before is None or spare <= 0:
                continue
            decisions[key] = held_before.scale
            spare -= 1
        plan = ReflectionPlan(frames, candidates=candidates)
        settling = self.frame <= SETTLE_FRAMES
        held: Dict[Hashable, _Held] = {}
        for key, entry in seen.items():
            tile = packed.tiles.get(key)
            if tile is None:
                continue
            if key in decisions:
                held[key] = _Held(entry.frame.view, entry.record[4], entry.mirror,
                                  tile, decisions[key], entry.eye, self.frame,
                                  provisional=settling)
                plan.draws.append(MirrorDraw(key, entry.frame, entry.record,
                                             entry.mirror, tile, entry.reflector))
            elif key not in packed.moved and entry.held is not None:
                held[key] = entry.held
            else:
                continue
            plan.lookups[key] = self._lookup(held[key], entry, atlas)
        self._held = held
        self.packer.place({key: (h.tile.width, h.tile.height) for key, h in held.items()})
        # A mirror crowded out of the atlas finds no more room next frame.
        plan.unfinished = settling and bool(plan.draws) or any(
            candidate.key not in decisions and candidate.key not in self._crowded
            and (not candidate.valid or candidate.drift > DRIFT_TEXELS)
            for candidate in candidates)
        return plan

    def _pack(self, seen: Dict[Hashable, _Seen], decisions: Dict[Hashable, float],
              weights: Mapping[Hashable, float]) -> Packed:
        """Place this frame's tiles, and settle the scale of each drawn one.

        Where the tiles being drawn and the tiles being kept do not all fit,
        they are placed one at a time by weight, screen area times priority,
        heaviest first: a drawn tile without room is tried at half scale, and
        one still without room is left out, drawn or kept. Weighing by what a
        mirror shows, and not by how long it has gone without, lets a scene
        with more mirrors than room settle on the ones it keeps. ``decisions``
        is updated with the scale each drawn tile ends up at, and loses any
        that found no room; those are recorded in ``_crowded``.
        """
        self._crowded = set()
        drawn = {key: _scaled(seen[key].mirror.size, scale)
                 for key, scale in decisions.items()}
        kept = {key: (entry.held.tile.width, entry.held.tile.height)
                for key, entry in seen.items()
                if key not in decisions and entry.valid and entry.held is not None}
        before = self.packer.tiles
        packed = self.packer.place({**kept, **drawn})
        if not packed.unplaced:
            return packed
        placed: Dict[Hashable, Tuple[int, int]] = {}

        def fits(key: Hashable, size: Tuple[int, int]) -> bool:
            return not self.packer.place({**placed, key: size}).unplaced

        for key in sorted({**kept, **drawn}, key=lambda key: -weights[key]):
            size = drawn.get(key) or kept[key]
            if not fits(key, size) and key in drawn:
                decisions[key] *= 0.5
                size = _scaled(seen[key].mirror.size, decisions[key])
            if fits(key, size):
                placed[key] = size
        packed = self.packer.place(placed)
        for key in drawn.keys() - packed.tiles.keys():
            del decisions[key]
            self._crowded.add(key)
        packed.moved = {key for key, tile in before.items()
                        if key in packed.tiles and packed.tiles[key] != tile}
        return packed

    def _lookup(self, held: _Held, seen: _Seen, atlas: Tuple[int, int]) -> Lookup:
        mirror = held.mirror
        return Lookup(
            matrix=tuple(float(value) for value in np.asarray(mirror.lookup, 'd').ravel()),
            transform=reflection.tile_transform(mirror.crop, held.tile.rect, atlas),
            bounds=reflection.tile_bounds(held.tile.rect, atlas),
            normal=(float(mirror.normal[0]), float(mirror.normal[1]),
                    float(mirror.normal[2])),
            distortion=float(seen.reflector.distortion),
            replace=bool(seen.reflector.replace),
            rough=seen.rough,
            provisional=held.provisional)
