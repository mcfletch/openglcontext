"""Where each reflection is kept, and which reflections a frame draws; no GL.

Every reflection a frame shows is a tile of one texture, the reflection atlas
(:class:`~OpenGLContext.passes.reflectionatlas.ReflectionAtlas`).
:class:`TilePacker` decides where each tile goes: shelves of power-of-two
heights, with a shorter tile beside taller ones where its own class has no
room, a gutter round every tile so filtering and the mip levels a rough
mirror reads stay inside it, and a tile that is not drawn this frame keeping
its place, so a reflection drawn a frame or two ago is still there to read.

:class:`ReflectionSchedule` decides which mirror views are drawn this frame and
at what size, within a :class:`Budget` of views, of views that also draw the
shapes a shared draw refuses, and of texels. Its rules, in order:

1. A mirror with no tile it can use -- none yet, or one drawn for another
   view, plane or size, or moved by a repack -- must be drawn.
2. A mirror whose tile has reached its reflector's ``interval`` must be drawn.
3. A mirror whose camera has moved far enough that its reprojected tile is
   wrong by more than :data:`DRIFT_TEXELS` must be drawn.
4. Every other mirror is optional, scored by screen area times priority times
   age plus one, and drawn while the budget has room.

Where the must-draw mirrors do not fit, those with no reflection they can use
go first, then the rest, each by the same score. One that does not fit at full
scale is drawn at half scale in its turn, and one that does not fit at half at
the largest scale the texels left allow, down to
:attr:`ReflectionSchedule.SMALLEST_SCALE`. A mirror the whole texel budget
cannot draw at that scale is unaffordable (:attr:`Chosen.unaffordable`), and
reflects what it has, or the probe. Age raises an optional mirror's score every
frame it is passed over, so it is drawn once the budget has room.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, Hashable, Iterable, List, Mapping, NamedTuple, Optional, Set, Tuple

__all__ = [
    'GUTTER', 'DRIFT_TEXELS', 'Tile', 'Packed', 'TilePacker', 'Candidate',
    'Budget', 'Decision', 'Chosen', 'ReflectionSchedule',
]

#: Texels of empty atlas kept round every tile.
GUTTER = 4

#: How far, in texels of its tile, a reused reflection may be off before it
#: must be drawn again.
DRIFT_TEXELS = 1.0

#: The smallest shelf, in texels.
_SHELF_FLOOR = 16


@dataclass(frozen=True)
class Tile:
    """A reflection's rectangle in the atlas, in texels, without its gutter."""

    x: int
    y: int
    width: int
    height: int

    @property
    def rect(self) -> Tuple[int, int, int, int]:
        """``(x, y, width, height)``, as ``glViewport`` takes it."""
        return self.x, self.y, self.width, self.height


@dataclass
class Packed:
    """What :meth:`TilePacker.place` did.

    ``tiles`` holds every tile placed, ``moved`` the keys a repack put
    somewhere other than where they were, and ``unplaced`` the keys there was
    no room for.
    """

    tiles: Dict[Hashable, Tile]
    moved: Set[Hashable] = field(default_factory=set)
    unplaced: Set[Hashable] = field(default_factory=set)


def _shelf_height(height: int) -> int:
    """The power of two a slot this tall is shelved at."""
    shelf = _SHELF_FLOOR
    while shelf < height:
        shelf *= 2
    return shelf


class _Slot(NamedTuple):
    """A tile and its gutter on a shelf: where it starts, how wide, and whose."""

    x: int
    width: int
    key: Hashable


@dataclass
class _Shelf:
    y: int
    height: int
    #: Each slot, in order along the shelf.
    slots: List[_Slot] = field(default_factory=list)

    def fit(self, width: int, limit: int) -> Optional[int]:
        """The first x a slot ``width`` wide fits at, or None."""
        x = 0
        for start, used, _key in self.slots:
            if start - x >= width:
                return x
            x = start + used
        return x if limit - x >= width else None


class TilePacker:
    """Each reflection's place in an atlas of ``width`` by ``height`` texels."""

    def __init__(self, width: int, height: int, gutter: int = GUTTER) -> None:
        self.gutter = int(gutter)
        self.width = self.height = 0
        self._shelves: List[_Shelf] = []
        self._sizes: Dict[Hashable, Tuple[int, int]] = {}
        self._tiles: Dict[Hashable, Tile] = {}
        self.resize(width, height)

    @property
    def tiles(self) -> Dict[Hashable, Tile]:
        """Every tile placed, by key."""
        return dict(self._tiles)

    def resize(self, width: int, height: int) -> None:
        """Hold an atlas of this size, empty."""
        self.width, self.height = int(width), int(height)
        self._shelves = []
        self._sizes = {}
        self._tiles = {}

    # -- placing ----------------------------------------------------------
    def _slot(self, size: Tuple[int, int]) -> Tuple[int, int]:
        return size[0] + 2 * self.gutter, size[1] + 2 * self.gutter

    def _insert(self, key: Hashable, size: Tuple[int, int]) -> bool:
        """Place one slot: on a shelf of its class, on a new shelf, or beside
        taller slots on a taller shelf, the first of those with room."""
        width, height = self._slot(size)
        if width > self.width:
            return False
        shelf_height = _shelf_height(height)
        if self._on_shelf(key, size, width,
                          (shelf for shelf in self._shelves if shelf.height == shelf_height)):
            return True
        top = max((shelf.y + shelf.height for shelf in self._shelves), default=0)
        if top + shelf_height > self.height:
            # The last shelf may be shorter than its class, to use the top of
            # the atlas; it then takes nothing taller than it is.
            shelf_height = self.height - top
        if shelf_height >= height:
            shelf = _Shelf(top, shelf_height)
            self._shelves.append(shelf)
            self._occupy(shelf, 0, width, key, size)
            return True
        taller = sorted((shelf for shelf in self._shelves if shelf.height > height),
                        key=lambda shelf: shelf.height)
        return self._on_shelf(key, size, width, taller)

    def _on_shelf(self, key: Hashable, size: Tuple[int, int], width: int,
                  shelves: Iterable[_Shelf]) -> bool:
        for shelf in shelves:
            x = shelf.fit(width, self.width)
            if x is not None:
                self._occupy(shelf, x, width, key, size)
                return True
        return False

    def _occupy(self, shelf: _Shelf, x: int, width: int, key: Hashable,
                size: Tuple[int, int]) -> None:
        shelf.slots.append(_Slot(x, width, key))
        shelf.slots.sort(key=lambda slot: slot.x)
        self._sizes[key] = size
        self._tiles[key] = Tile(x + self.gutter, shelf.y + self.gutter, *size)

    def _release(self, key: Hashable) -> None:
        for shelf in self._shelves:
            shelf.slots = [slot for slot in shelf.slots if slot.key != key]
        # An empty shelf at the top gives its height back; one lower down is
        # kept for the next tile of its class.
        while self._shelves and not self._shelves[-1].slots:
            self._shelves.pop()
        self._sizes.pop(key, None)
        self._tiles.pop(key, None)

    def place(self, sizes: Mapping[Hashable, Tuple[int, int]]) -> Packed:
        """Hold a tile of each size by key, releasing every key not named.

        A key whose size is unchanged keeps its place. Where a new or resized
        tile finds no room, everything is packed again, tallest first, and
        the keys that moved are reported: what they held is gone.
        """
        wanted = {key: (int(size[0]), int(size[1])) for key, size in sizes.items()}
        for key in list(self._sizes):
            if wanted.get(key) != self._sizes[key]:
                self._release(key)
        before = dict(self._tiles)
        pending = [key for key in wanted if key not in self._tiles]
        if all(self._insert(key, wanted[key]) for key in pending):
            return Packed(dict(self._tiles))
        return self._repack(wanted, before)

    def _repack(self, wanted: Mapping[Hashable, Tuple[int, int]],
                before: Mapping[Hashable, Tile]) -> Packed:
        self._shelves, self._sizes, self._tiles = [], {}, {}
        unplaced = set()
        order = sorted(wanted, key=lambda key: (-wanted[key][1], -wanted[key][0]))
        for key in order:
            if not self._insert(key, wanted[key]):
                unplaced.add(key)
        moved = {key for key, tile in before.items()
                 if key in self._tiles and self._tiles[key] != tile}
        return Packed(dict(self._tiles), moved, unplaced)


# --- the schedule -------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    """One mirror seen from one view, as the schedule weighs it.

    ``area`` is the screen pixels it covers and ``texels`` its tile's at full
    scale. ``age`` is frames since its tile was drawn, None where it has none;
    ``valid`` whether that tile still serves this view, plane and size.
    ``drift`` is how far, in texels, reusing the tile would put a reflection
    off. ``separate`` marks a view that also draws what a shared draw refuses.
    """

    key: Hashable
    area: float
    priority: float
    interval: int
    texels: int
    age: Optional[int]
    valid: bool
    drift: float = 0.0
    separate: bool = False

    @property
    def must(self) -> bool:
        """Whether rules 1-3 say it is drawn this frame."""
        return (not self.valid or self.age is None
                or self.age >= max(1, int(self.interval))
                or self.drift > DRIFT_TEXELS)

    @property
    def score(self) -> float:
        """Screen area times priority times age plus one."""
        age = self.interval if self.age is None else self.age
        return float(self.area) * max(float(self.priority), 0.0) * (age + 1)


@dataclass(frozen=True)
class Budget:
    """The most a frame's reflections may cost.

    ``views`` mirror views in all, ``separate_views`` of them drawing the
    shapes a shared draw refuses, and ``texels`` of atlas drawn.
    """

    views: int
    separate_views: int
    texels: int


@dataclass(frozen=True)
class Decision:
    """A mirror view to draw, at ``scale`` of its tile's size each way."""

    key: Hashable
    scale: float


@dataclass
class Chosen:
    """What :meth:`ReflectionSchedule.choose` decided, and what the budget has left.

    ``decisions`` are the mirror views to draw, highest score first.
    ``views``, ``separate_views`` and ``texels`` are what is left of the
    budget after them, which :meth:`afford` spends. ``unaffordable`` holds the
    must-draw mirrors the whole texel budget cannot draw at
    :attr:`ReflectionSchedule.SMALLEST_SCALE`.
    """

    views: int
    separate_views: int
    texels: float
    decisions: List[Decision] = field(default_factory=list)
    unaffordable: Set[Hashable] = field(default_factory=set)

    def room(self, candidate: Candidate) -> bool:
        """Whether a view is left for ``candidate``, and a separate one where it needs one."""
        return self.views > 0 and (not candidate.separate or self.separate_views > 0)

    def take(self, candidate: Candidate, scale: float) -> None:
        """Draw ``candidate`` at ``scale``, spending its view and texels."""
        self.views -= 1
        if candidate.separate:
            self.separate_views -= 1
        self.texels -= candidate.texels * scale * scale
        self.decisions.append(Decision(candidate.key, scale))

    def afford(self, candidate: Candidate, scale: float) -> bool:
        """Draw ``candidate`` at ``scale`` if what is left allows it; whether it did."""
        if not self.room(candidate) or candidate.texels * scale * scale > self.texels:
            return False
        self.take(candidate, scale)
        return True


class ReflectionSchedule:
    """Which mirror views each frame draws; see the module for the rules.

    ``time_scale`` shrinks the texel budget where a GPU time target is set
    and the reflections are over it (:meth:`measured`).
    """

    #: The least share of the texel budget a time target leaves.
    FLOOR = 0.25
    #: How far one measurement moves the time scale toward what it asks for.
    SMOOTHING = 0.2
    #: The smallest scale, each way, a mirror that must be drawn is drawn at.
    SMALLEST_SCALE = 0.125

    def __init__(self) -> None:
        self.time_scale = 1.0
        self._reading: Optional[Hashable] = None

    def measured(self, milliseconds: float, target: float,
                 scale: Optional[float] = None,
                 reading: Optional[Hashable] = None) -> None:
        """Move the time scale toward what keeps the reflections under ``target``.

        ``milliseconds`` is what the reflections of a frame drawn at time scale
        ``scale`` cost; the current time scale where not given. ``reading``
        names the measurement: one already applied is not applied again, since
        a timer answers its newest reading until another arrives.
        """
        if reading is not None:
            if reading == self._reading:
                return
            self._reading = reading
        if milliseconds <= 0.0 or target <= 0.0:
            return
        drawn_at = self.time_scale if scale is None else float(scale)
        wanted = drawn_at * float(target) / float(milliseconds)
        moved = self.time_scale + self.SMOOTHING * (wanted - self.time_scale)
        self.time_scale = min(1.0, max(self.FLOOR, moved))

    def _scale(self, candidate: Candidate, texels: float) -> Optional[float]:
        """The largest scale ``candidate`` fits ``texels`` at, or None: full,
        half, or anything down to :attr:`SMALLEST_SCALE`."""
        for scale in (1.0, 0.5):
            if candidate.texels * scale * scale <= texels:
                return scale
        if candidate.texels <= 0:
            return None
        scale = math.sqrt(max(texels, 0.0) / candidate.texels)
        return scale if scale >= self.SMALLEST_SCALE else None

    def choose(self, candidates: List[Candidate], budget: Budget) -> Chosen:
        """The mirror views to draw this frame, and what the budget has left."""
        total = float(budget.texels) * self.time_scale
        chosen = Chosen(int(budget.views), int(budget.separate_views), total)
        ranked = sorted(candidates, key=lambda c: -c.score)
        # A mirror with no reflection it can use goes before one that has an
        # older one: showing nothing is the larger error.
        must = sorted((c for c in ranked if c.must), key=lambda c: c.valid)
        optional = [c for c in ranked if not c.must]
        for candidate in must:
            if not chosen.room(candidate):
                continue
            scale = self._scale(candidate, chosen.texels)
            if scale is not None:
                chosen.take(candidate, scale)
            elif self._scale(candidate, total) is None:
                chosen.unaffordable.add(candidate.key)
        for candidate in optional:
            chosen.afford(candidate, 1.0)
        return chosen
