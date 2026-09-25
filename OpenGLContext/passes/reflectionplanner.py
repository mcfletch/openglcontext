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

import itertools
from dataclasses import dataclass, field
from typing import (
    Any, Callable, Dict, FrozenSet, Hashable, Iterable, List, Mapping, NamedTuple,
    Optional, Sequence, Set, Tuple, Union, cast,
)

import numpy as np

from OpenGLContext.passes import reflection
from OpenGLContext.passes.reflection import MirrorView
from OpenGLContext.passes.reflectiontiles import (
    DRIFT_TEXELS, Budget, Candidate, Packed, ReflectionSchedule, Tile, TilePacker,
)
from OpenGLContext.scenegraph.reflector import PlanarReflector

__all__ = ['ROUGH', 'SETTLE_FRAMES', 'Lookup', 'MirrorDraw', 'ReflectedView',
           'ReflectionPlan', 'ReflectionPlanner', 'key_for', 'view_key']

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
    from. ``rough`` is the material's roughness, which picks the mip level,
    and ``reflectance`` the share of the light the mirror reflects.
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
    reflectance: float = 1.0


_SERIALS = itertools.count(1)


class ReflectedView:
    """A view of the scene through one mirror, from one view of it.

    What a mirror view is drawn as, so that the mirrors seen in it are keyed
    by it: kept by the planner for as long as its mirror stays in view, so
    the reflections drawn for it one frame are read in it the next. Every
    other attribute is the view it is seen from. ``viewer`` is where the
    camera at the start of the chain of mirrors stands, in the world.
    """

    def __init__(self, source: Any, key: Hashable, viewer: np.ndarray) -> None:
        self.source = source
        self.key = key
        self.viewer = viewer
        #: What reflections seen in it are keyed by, never reused: a view made
        #: later can be given a dropped one's address, and would then read the
        #: reflections kept for it.
        self.serial = next(_SERIALS)

    @property
    def depth(self) -> int:
        """The mirrors between this view and the camera: 1 for a mirror in view."""
        return int(getattr(self.source, 'depth', 0)) + 1

    def __getattr__(self, name: str) -> Any:
        return getattr(self.source, name)


@dataclass
class MirrorDraw:
    """One mirror view to draw: whose view, which mirror, into which tile.

    ``view`` is the :class:`ReflectedView` it is drawn as; its ``depth`` is
    the reflections its camera has been through, and an even count turns the
    winding back.
    """

    key: Hashable
    frame: Any
    record: Any
    mirror: MirrorView
    tile: Tile
    reflector: PlanarReflector
    view: Optional[ReflectedView] = None
    #: ``id`` of the path of every mirror this view is the reflection of: one,
    #: or each of a set in one plane sharing one reflector.
    paths: FrozenSet[int] = frozenset()

    @property
    def depth(self) -> int:
        """The reflections this mirror view's camera has been through."""
        return self.view.depth if self.view is not None else 1


@dataclass
class ReflectionPlan:
    """What a frame draws and reads; see :class:`ReflectionPlanner`."""

    frames: Sequence[Any]
    draws: List[MirrorDraw] = field(default_factory=list)
    lookups: Dict[Hashable, Lookup] = field(default_factory=dict)
    candidates: List[Candidate] = field(default_factory=list)
    #: Each mirror's key to its group's, for a mirror that shares a
    #: reflection with others in its plane; a mirror of its own is absent.
    aliases: Dict[Hashable, Hashable] = field(default_factory=dict)
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

    def canonical(self, key: Hashable) -> Hashable:
        """The key ``key``'s reflection is planned and drawn under."""
        return self.aliases.get(key, key)


def view_key(view: Any) -> Hashable:
    """What the mirrors seen in ``view`` are keyed by.

    A mirror's own view is short-lived, so it is keyed by a serial number no
    later view shares; the views of a context live as long as it does.
    """
    return ('reflected', view.serial) if isinstance(view, ReflectedView) else id(view)


def key_for(frame: Any, record: Any) -> Tuple[Hashable, int]:
    """The key one mirror in one view is held by."""
    return view_key(frame.view), id(record[4])


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
    #: The reflections of mirrors in its view it was drawn without, which
    #: those mirrors showed the probe in place of; drawn again once one is.
    missing: FrozenSet[Hashable] = frozenset()


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
    #: Every mirror sharing this reflection, the first being ``record``.
    members: List['_Surface'] = field(default_factory=list)


class _Surface(NamedTuple):
    """One mirror surface in one view, before it is grouped with its plane."""

    record: Any
    reflector: PlanarReflector
    rough: float
    plane: Tuple[np.ndarray, np.ndarray]
    corners: np.ndarray


#: How near two mirrors' planes are to be one plane: a thousandth of their
#: normals' length, and a millimetre.
COPLANAR = 3


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
        self._crowded: Set[Hashable] = set()
        #: Whether a mirror's reflection may be drawn for a camera at ``eye``:
        #: ``allowed(record, eye)``, or None where every mirror may. The pass
        #: sets it from the scene's zones; see
        #: :meth:`~OpenGLContext.passes.zonepass.ZonesMixin.mirrorAllowed`.
        self.allowed: Optional[Callable[[Any, np.ndarray], bool]] = None
        self._views: Dict[Hashable, ReflectedView] = {}
        #: The reflections in the atlas that a mirror view may read.
        self._arrived: Set[Hashable] = set()
        #: The last plan's aliases, for what the pass says about a member.
        self._aliases: Dict[Hashable, Hashable] = {}

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

    def drawn_without(self, key: Hashable, missing: Iterable[Hashable]) -> None:
        """Say that ``key``'s reflection was drawn without the reflections of
        the mirrors in its view keyed ``missing``, which were not yet drawn.

        It is drawn again the frame after one of them is.
        """
        held = self._held.get(key)
        if held is not None:
            held.missing = frozenset(self._aliases.get(inner, inner) for inner in missing)

    # -- finding the mirrors ----------------------------------------------
    def _seen(self, frames: Sequence[Any]) -> List[_Seen]:
        """Each view's mirrors, those in one plane sharing a reflector as one."""
        found = []
        for frame in frames:
            view = frame.view
            if getattr(getattr(view, 'style', None), 'wireframe', False):
                continue
            modelview = np.asarray(frame.modelView, 'd')
            eye = np.linalg.inv(modelview)[3, :3]
            groups: Dict[Hashable, List[_Surface]] = {}
            for record in frame.toRender:
                surface = self._surface(frame, record, eye)
                if surface is not None:
                    point, normal = surface.plane
                    plane = (tuple(np.round(normal, COPLANAR)),
                             round(float(np.dot(normal, point)), COPLANAR))
                    groups.setdefault((id(surface.reflector), plane), []).append(surface)
            for members in groups.values():
                seen = self._mirror(frame, sorted(members, key=lambda m: id(m.record[4])),
                                    eye)
                if seen is not None:
                    found.append(seen)
        return found

    def _surface(self, frame: Any, record: Any, eye: np.ndarray) -> Optional[_Surface]:
        reflector = reflection.reflector_for(record)
        if reflector is None:
            return None
        # Zones decide by where the viewer stands, not a reflected camera.
        viewer = frame.view.viewer if isinstance(frame.view, ReflectedView) else eye
        if self.allowed is not None and not self.allowed(record, viewer):
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
        return _Surface(record, reflector, rough, plane,
                        np.asarray(reflection.world_corners(local, record[2]), 'd'))

    def _mirror(self, frame: Any, members: List[_Surface], eye: np.ndarray
                ) -> Optional[_Seen]:
        first = members[0]
        record, reflector, plane = first.record, first.reflector, first.plane
        corners = np.concatenate([member.corners.reshape(-1, 3) for member in members])
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
                                        reflector.bounded('scale'), crop=crop)
        if mirror is None:
            return None
        valid = (held is not None and not held.provisional and not held.redo
                 and not held.missing & self._arrived
                 and mirror.crop == held.mirror.crop
                 and _scaled(mirror.size, held.scale)
                 == (held.tile.width, held.tile.height))
        return _Seen(key, frame, record, reflector, mirror, eye, first.rough, held, valid,
                     members)

    def _view_for(self, entry: _Seen) -> ReflectedView:
        """The view ``entry``'s mirror shows, the same one while it stays in view."""
        view = self._views.get(entry.key)
        source = entry.frame.view
        viewer = source.viewer if isinstance(source, ReflectedView) else entry.eye
        if view is None or view.source is not source:
            view = self._views[entry.key] = ReflectedView(source, entry.key, viewer)
        # The camera moves while the mirror stays in view.
        view.viewer = viewer
        return view

    def _inside(self, entries: Sequence[_Seen],
                inside: Callable[[Any], Sequence[Any]]) -> List[_Seen]:
        """The mirrors seen in the views of ``entries``' mirrors.

        ``inside(frame)`` is what a mirror view's frame would draw. A mirror's
        own surface is left out of its own view. Each frame's ``modelproj`` is
        the mirror's clipped camera, which is what it culls through, and its
        ``projection`` the parent's own cropped to the mirror, which is what a
        mirror in it is planned from: a near plane moved onto one mirror and
        then onto another leaves a far plane that clips what the second shows.
        """
        from OpenGLContext.multiview.strategy import ViewFrame
        from OpenGLContext.multiview.views import View
        frames = []
        for entry in entries:
            mirror = entry.mirror
            plain = np.asarray(entry.frame.projection, 'd') @ reflection.crop_matrix(mirror.crop)
            # A ReflectedView answers every attribute as the View it is seen
            # from does, which is what a frame's view is read for.
            frame = ViewFrame(cast(View, self._view_for(entry)), entry.frame.camera,
                              (0, 0, mirror.size[0], mirror.size[1]),
                              mirror.modelView, plain, mirror.modelproj,
                              None, fitted=False)
            own = {id(member.record[4]) for member in entry.members}
            frame.toRender = [record for record in inside(frame)
                              if id(record[4]) not in own]
            frames.append(frame)
        return self._seen(frames)

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
            key=seen.key, area=area, priority=seen.reflector.bounded('priority'),
            interval=int(seen.reflector.bounded('interval')),
            texels=seen.mirror.size[0] * seen.mirror.size[1],
            age=age, valid=seen.valid, drift=self._drift(seen) if seen.valid else 0.0,
            separate=separate)

    # -- the frame --------------------------------------------------------
    def plan(self, frames: Sequence[Any], atlas: Tuple[int, int],
             budget: Union[Budget, Callable[[], Budget]],
             separate: Callable[[Any], bool] = lambda frame: False,
             inside: Optional[Callable[[Any], Sequence[Any]]] = None,
             bounces: int = 2) -> ReflectionPlan:
        """This frame's mirror views and lookups.

        ``atlas`` is the atlas's size in texels; ``budget`` is the frame's
        :class:`~OpenGLContext.passes.reflectiontiles.Budget`, or what makes
        one, asked only where a view has a mirror in it. ``separate(frame)``
        says whether a view's mirrors would also draw shapes a shared draw
        refuses. ``inside(frame)`` answers the mirrors a mirror view's frame
        can see; given it, each is planned from that mirror's camera, drawn as
        its :class:`ReflectedView`, and read there a frame later. Every chain
        of mirrors is followed with its own camera, up to ``bounces``
        reflections deep: 1 plans only the mirrors the views see.
        """
        self.frame += 1
        self._arrived = {key for key, held in self._held.items() if not held.provisional}
        if (self.packer.width, self.packer.height) != tuple(atlas):
            self.packer.resize(*atlas)
            self._held.clear()
        seen = {entry.key: entry for entry in self._seen(frames)}
        if inside is not None:
            level = list(seen.values())
            for _depth in range(1, int(bounces)):
                level = self._inside(level, inside)
                seen.update((entry.key, entry) for entry in level)
        self._views = {key: view for key, view in self._views.items() if key in seen}
        if not seen:
            self._held.clear()
            self.packer.place({})
            return ReflectionPlan(frames)
        if callable(budget):
            budget = budget()
        mirrored = {id(entry.frame): entry.frame for entry in seen.values()}
        separates = {key: bool(separate(frame)) for key, frame in mirrored.items()}
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
        # Every group's, drawn or not: the pass names a mirror by its own key.
        plan.aliases = {key_for(entry.frame, member.record): key
                        for key, entry in seen.items() for member in entry.members[1:]}
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
                plan.draws.append(MirrorDraw(
                    key, entry.frame, entry.record, entry.mirror, tile, entry.reflector,
                    self._view_for(entry),
                    frozenset(id(member.record[4]) for member in entry.members)))
            elif key not in packed.moved and entry.held is not None:
                held[key] = entry.held
            else:
                continue
            lookup = self._lookup(held[key], entry, atlas)
            for member in entry.members:
                plan.lookups[key_for(entry.frame, member.record)] = lookup._replace(
                    rough=member.rough)
        self._held = held
        self._aliases = plan.aliases
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
            distortion=seen.reflector.bounded('distortion'),
            replace=bool(seen.reflector.replace),
            rough=seen.rough,
            provisional=held.provisional,
            reflectance=seen.reflector.bounded('reflectance'))
