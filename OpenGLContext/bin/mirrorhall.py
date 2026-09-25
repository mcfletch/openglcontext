"""The room ``oglc-mirrors`` hangs its mirrors in; no GL, and no mirrors of its own.

A hall 16.2 metres wide, 24 long and 4.4 high, made from
:mod:`OpenGLContext.scenegraph.surfaces`:

* brick walls, the bricks 10 cm long, broken into bays by half columns and
  run round by a skirting, a dado rail and a stepped cornice;
* two tall windows in the right wall, in stone surrounds with bronze glazing
  bars, onto a sky;
* a dais of three marble steps at the far end, each edged with a brass nosing;
* four chamfered metal columns, each under a lamp that lights the room;
* a floor slot for 30 cm marble tiles inside a border of black marble tiles,
  and a basin for a pool, tiled at the bottom.

It is lit as a room: a low sun (:data:`SUN`) shines in through the windows
and lays their shape on the floor and the dais, the lamps light it from the
columns, and a zone round the whole hall takes its environment light from a
capture made inside it, so what is not in the sun is lit by the room rather
than by the open sky. The lamps' housings cast no shadow of their own light.

It is scenery. The demo says what is a mirror and where it goes::

    hall = Hall()
    scene = hall.room() + hall.floor(polished_field, polished_border)
    scene += hall.hang(surfaces.panel(6.0, 3.0), silver, 'far', along=0.0,
                       height=2.3, frame=hall.finish.gilt)

The floor's materials are the caller's, since a polished floor is one of the
mirrors. :data:`BAYS` are the places between the half columns to hang things
in. Coordinates are metres, y up, the room centred on the origin with the
floor at y = 0; the ``far`` wall is at -z.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, NamedTuple, Optional

import numpy as np

from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

__all__ = ['WIDTH', 'LENGTH', 'HEIGHT', 'TILE', 'BRICK', 'WALLS', 'BAYS', 'PILASTERS',
           'WINDOWS', 'WINDOW_WIDTH', 'STEPS', 'SUN', 'Finishes', 'Part', 'Hall']

#: The room's size in metres: across x, along z, and up. The width and length
#: are whole numbers of floor tiles, border included.
WIDTH, LENGTH, HEIGHT = 16.2, 24.0, 4.4

#: A floor tile's side, and a brick's length with its joint, in metres.
TILE, BRICK = 0.30, 0.10

#: Each wall by name: the axis it lies across, where, and the rotation that
#: turns a surface facing +z to face into the room from it.
WALLS: dict[str, tuple[int, float, tuple[float, float, float, float]]] = {
    'far': (2, -LENGTH / 2, (0.0, 1.0, 0.0, 0.0)),
    'near': (2, LENGTH / 2, (0.0, 1.0, 0.0, math.pi)),
    'left': (0, -WIDTH / 2, (0.0, 1.0, 0.0, math.pi / 2)),
    'right': (0, WIDTH / 2, (0.0, 1.0, 0.0, -math.pi / 2)),
}

#: Where each wall's half columns stand, along it: x on the far and near
#: walls, z on the left and right.
PILASTERS: dict[str, tuple[float, ...]] = {
    'left': tuple(float(z) for z in range(-10, 11, 2)),
    'right': (-9.0, -2.0, 2.0, 9.0),
    'far': (-4.6, 4.6),
    'near': (-4.6, 4.6),
}

#: The middle of each bay between them, where something may be hung.
BAYS: dict[str, tuple[float, ...]] = {
    'left': tuple(float(z) for z in range(-9, 10, 2)),
    'right': (-5.5, 0.0, 5.5),
    'far': (0.0,),
    'near': (0.0,),
}

#: The windows in the right wall: (z of the middle, sill, head), in metres.
WINDOWS: tuple[tuple[float, float, float], ...] = ((-5.5, 1.1, 3.5), (5.5, 1.1, 3.5))
WINDOW_WIDTH = 2.2

#: The dais's steps, lowest first: (height of the tread, z of its front edge).
STEPS: tuple[tuple[float, float], ...] = ((0.15, -9.9), (0.3, -10.25), (0.45, -10.6))

#: The sunlight's direction: low, from beyond the right wall, so each window
#: lays a patch of light several metres across the floor.
SUN = (-0.6, -0.45, -0.66)

#: How far in front of its wall a hung surface stands, and its frame's depth.
STANDOFF = 0.1
FRAME_DEPTH = 0.1

#: The heights of the moldings, in metres.
SKIRTING, DADO, CORNICE = 0.18, 0.9, 4.18


class Finishes:
    """The hall's materials, made once.

    ``floor`` and ``border`` are maps rather than materials, for the demo to
    make its polished floor from: checkered marble and black marble, two
    30 cm tiles to a repeat.
    """

    def __init__(self) -> None:
        self.floor = surfaces.checkered_marble(512, tiles=2)
        self.border = surfaces.marble_tiles(512, tiles=2)
        self.brick = surfaces.pbr_material(surfaces.brick(256))
        self.plaster = surfaces.pbr_material(surfaces.plaster(256), relief=0.5)
        self.molding = surfaces.pbr_material(
            surfaces.plaster(256, colour=(0.86, 0.82, 0.74), seed=21), relief=0.3)
        self.pilaster = surfaces.pbr_material(
            surfaces.marble(256, base=(0.84, 0.80, 0.72), vein=(0.55, 0.50, 0.44),
                            polish=0.18, seed=22))
        self.sandstone = surfaces.pbr_material(surfaces.sandstone(256))
        self.treads = surfaces.pbr_material(surfaces.marble(256, polish=0.08, seed=23))
        self.pool = surfaces.pbr_material(surfaces.tiles(256, count=8, colour=(0.30, 0.62, 0.66)))
        self.nosing = surfaces.pbr_material(
            surfaces.brushed_metal(128, (0.91, 0.78, 0.42), 0.25, seed=24))
        self.gilt = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.GOLD, 0.22))
        self.bronze = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.BRONZE, 0.35))
        self.columns = [surfaces.pbr_material(surfaces.brushed_metal(128, colour, rough))
                        for colour, rough in ((surfaces.GOLD, 0.25), (surfaces.COPPER, 0.3),
                                              (surfaces.STEEL, 0.2), (surfaces.BRONZE, 0.32))]
        self.lamp = PBRMaterial(baseColor=(1.0, 0.95, 0.85), metallic=0.0, roughness=0.4,
                                emissiveColor=(1.0, 0.9, 0.7), emissiveStrength=3.0)


class Part(NamedTuple):
    """One piece of the hall: which group of it, what it wears, and its mesh,
    already in the room's space."""

    group: str
    material: Any
    geometry: surfaces.Geometry


def _block(size: Sequence[float], translation: Sequence[float], material: Any,
           rotation: Sequence[float] = (0.0, 1.0, 0.0, 0.0), chamfer: float = 0.0) -> Any:
    return surfaces.shape(surfaces.block(size, chamfer=chamfer), material, translation,
                          rotation)


def _part(group: str, material: Any, geometry: surfaces.Geometry,
          translation: Sequence[float], rotation: Sequence[float] = (0.0, 1.0, 0.0, 0.0)
          ) -> Part:
    return Part(group, material, surfaces.placed(geometry, translation, rotation))


def _on_wall(wall: str, along: float, height: float, offset: float
             ) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    """A point ``offset`` metres out from ``wall``, and the rotation that faces it in."""
    if wall not in WALLS:
        raise ValueError('the hall has no %r wall; it has %s' % (wall, ', '.join(WALLS)))
    axis, at, rotation = WALLS[wall]
    point = [0.0, height, 0.0]
    point[axis] = at - math.copysign(offset, at)
    point[2 if axis == 0 else 0] = along
    return (point[0], point[1], point[2]), rotation


def _across(wall: str, along: float) -> float:
    """Where ``along`` falls across a surface facing into the room from ``wall``."""
    axis, at, _rotation = WALLS[wall]
    # A surface's own x runs to the right as it is seen from inside the room.
    return along if (axis == 2) == (at < 0) else -along


class Hall:
    """The room, and the places in it a demo puts its own surfaces."""

    def __init__(self) -> None:
        self.finish = Finishes()

    def room(self) -> list[Any]:
        """Everything in the hall but its floor and what the demo hangs in it.

        The scenery is :meth:`parts` merged into one shape for each group and
        material -- a wall's brick, a wall's moldings, the dais's treads -- so
        a view draws a few dozen shapes, not a few hundred small ones, and
        still leaves out the groups it cannot see.
        """
        merged: dict[tuple[str, int], list[Part]] = {}
        for part in self.parts():
            merged.setdefault((part.group, id(part.material)), []).append(part)
        scenery = []
        for parts in merged.values():
            placed = surfaces.shape(surfaces.merge([part.geometry for part in parts]),
                                    parts[0].material)
            # A lamp's housing stands between its light and the room.
            placed.children[0].castsShadow = parts[0].material is not self.finish.lamp
            scenery.append(placed)
        # The room's environment light is what can be seen inside it: the
        # lamps, the sunlit floor and the sky through the windows.
        inside = basenodes.Transform(translation=(0.0, HEIGHT / 2, 0.0), children=[
            basenodes.Zone(size=(WIDTH + 0.4, HEIGHT + 0.4, LENGTH + 0.4), blend=0.2,
                           settings=[basenodes.ZoneEnvironment(capture=True, intensity=0.4)])])
        return ([basenodes.Viewpoint(position=(0.0, 1.7, 9.0), description='Hall'),
                 basenodes.NavigationInfo(headlight=False, type=['WALK']),
                 basenodes.DirectionalLight(direction=SUN, intensity=6.0), inside,
                 basenodes.Background(
                     skyColor=[(0.30, 0.46, 0.72), (0.55, 0.68, 0.86), (0.82, 0.85, 0.87)],
                     skyAngle=[1.1, 1.52],
                     groundColor=[(0.25, 0.30, 0.20), (0.38, 0.42, 0.30)],
                     groundAngle=[1.35])]
                + scenery + self._lamps())

    def parts(self) -> list[Part]:
        """Every piece of the hall's scenery, each on its own, in the room's space."""
        return (self._walls() + self._moldings() + self._pilasters() + self._windows()
                + self._dais() + self._columns())

    def floor(self, field: Any, border: Any) -> list[Any]:
        """The floor: ``field`` inside a border one tile wide of ``border``.

        Each wears two :data:`TILE` tiles to a repeat, and the two grids meet
        in line. The border is one mesh, so it is one mirror.
        """
        inner_w, inner_l = WIDTH - 2 * TILE, LENGTH - 2 * TILE
        repeat = 2 * TILE

        def piece(width: float, length: float, x: float, z: float) -> surfaces.Geometry:
            # The floor's own frame: x across, y towards the far wall.
            start = (x - width / 2 + WIDTH / 2, -z - length / 2 + LENGTH / 2)
            return surfaces.moved(surfaces.panel(width, length, repeat, start), (x, -z, 0.0))

        edge = (LENGTH - TILE) / 2
        side = (WIDTH - TILE) / 2
        ring = surfaces.merge([piece(WIDTH, TILE, 0.0, edge), piece(WIDTH, TILE, 0.0, -edge),
                               piece(TILE, inner_l, side, 0.0), piece(TILE, inner_l, -side, 0.0)])
        flat = (1.0, 0.0, 0.0, -math.pi / 2)
        return [surfaces.shape(piece(inner_w, inner_l, 0.0, 0.0), field, rotation=flat),
                surfaces.shape(ring, border, rotation=flat)]

    def hang(self, geometry: surfaces.Geometry, material: Any, wall: str, along: float,
             height: float, frame: Optional[Any] = None, border: float = 0.1) -> list[Any]:
        """``geometry`` wearing ``material``, flat on ``wall`` and facing into the room.

        ``geometry`` lies in its own xy plane facing +z, as
        :func:`~OpenGLContext.scenegraph.surfaces.panel` makes it. ``wall`` is
        one of :data:`WALLS`; ``along`` is the position along it -- x on the
        far and near walls, z on the left and right -- and ``height`` that of
        the surface's centre. ``frame`` is a material for a frame behind it,
        ``border`` metres wider on every side.
        """
        at, rotation = _on_wall(wall, along, height, STANDOFF)
        hung = [surfaces.shape(geometry, material, at, rotation)]
        if frame is not None:
            width, tall = np.ptp(geometry.positions[:, :2], axis=0)
            behind, _ = _on_wall(wall, along, height, STANDOFF - FRAME_DEPTH / 2 - 0.01)
            hung.append(_block((float(width) + 2 * border, float(tall) + 2 * border,
                                FRAME_DEPTH), behind, frame, rotation))
        return hung

    def basin(self, x0: float, x1: float, z0: float, z1: float,
              rim: float = 0.3) -> list[Any]:
        """A pool's basin from ``x0``-``x1``, ``z0``-``z1``: a sandstone rim ``rim``
        metres high, and a floor of glazed tiles 10 cm across."""
        thick = 0.2
        middle_x, middle_z = (x0 + x1) / 2.0, (z0 + z1) / 2.0
        across, deep = x1 - x0 + 2 * thick, z1 - z0
        sides = [surfaces.placed(surfaces.block(size), at) for size, at in (
            ((across, rim, thick), (middle_x, rim / 2, z0 - thick / 2)),
            ((across, rim, thick), (middle_x, rim / 2, z1 + thick / 2)),
            ((thick, rim, deep), (x0 - thick / 2, rim / 2, middle_z)),
            ((thick, rim, deep), (x1 + thick / 2, rim / 2, middle_z)))]
        bottom = surfaces.panel(x1 - x0, z1 - z0, repeat=0.8)
        return [surfaces.shape(surfaces.merge(sides), self.finish.sandstone),
                surfaces.shape(bottom, self.finish.pool, (middle_x, 0.01, middle_z),
                               (1.0, 0.0, 0.0, -math.pi / 2))]

    # -- the walls ---------------------------------------------------------------
    def _walls(self) -> list[Part]:
        """Four brick walls, the right one open at its windows, and a plaster ceiling."""
        walls = []
        for wall, (axis, _at, _rotation) in WALLS.items():
            span = WIDTH if axis == 2 else LENGTH
            openings = [(_across(wall, along), low, high) for along, low, high in WINDOWS
                        ] if wall == 'right' else []
            walls += self._brickwork(wall, span, openings)
        walls.append(_part('ceiling', self.finish.plaster,
                           surfaces.panel(WIDTH, LENGTH, repeat=3.0), (0.0, HEIGHT, 0.0),
                           (1.0, 0.0, 0.0, math.pi / 2)))
        return walls

    def _brickwork(self, wall: str, span: float,
                   openings: Sequence[tuple[float, float, float]]) -> list[Part]:
        """``wall`` in pieces round ``openings`` (across, sill, head), its courses in line.

        ``brick()`` has four bricks across a repeat, so the repeat is four
        :data:`BRICK` lengths.
        """
        edges = sorted({-span / 2, span / 2} | {middle + side * WINDOW_WIDTH / 2
                                                for middle, _low, _high in openings
                                                for side in (-1, 1)})
        pieces = []
        for left, right in zip(edges, edges[1:]):
            spans = [(0.0, HEIGHT)]
            for middle, low, high in openings:
                if left >= middle - WINDOW_WIDTH / 2 - 1e-6 and right <= middle + WINDOW_WIDTH / 2 + 1e-6:
                    spans = [(0.0, low), (high, HEIGHT)]
            for bottom, top in spans:
                width, tall = right - left, top - bottom
                geometry = surfaces.panel(width, tall, repeat=4 * BRICK,
                                          start=(left + span / 2, bottom))
                across = (left + right) / 2
                along = across if _across(wall, 1.0) > 0 else -across
                at, rotation = _on_wall(wall, along, (bottom + top) / 2, 0.0)
                pieces.append(_part(wall, self.finish.brick, geometry, at, rotation))
        return pieces

    def _moldings(self) -> list[Part]:
        """A skirting, a dado rail and a three-stepped cornice round every wall."""
        runs: list[tuple[float, float, float]] = [
            (SKIRTING / 2, SKIRTING, 0.025), (DADO, 0.06, 0.035),
            (CORNICE + 0.035, 0.07, 0.07), (CORNICE + 0.105, 0.07, 0.12),
            (CORNICE + 0.18, 0.08, 0.18)]
        found = []
        for wall, (axis, _at, _rotation) in WALLS.items():
            span = WIDTH if axis == 2 else LENGTH
            for height, tall, depth in runs:
                at, rotation = _on_wall(wall, 0.0, height, depth / 2)
                found.append(_part(wall, self.finish.molding,
                                   surfaces.block((span, tall, depth)), at, rotation))
        return found

    def _pilasters(self) -> list[Part]:
        """Half columns of pale marble, on a base and under a capital, between the bays."""
        shaft_bottom, shaft_top = 0.24, CORNICE - 0.16
        shaft = surfaces.cylinder(0.16, shaft_top - shaft_bottom, sides=16, arc=math.pi,
                                  repeat=0.5)
        base, capital = surfaces.block((0.44, shaft_bottom, 0.22)), surfaces.block((0.44, 0.16, 0.24))
        found = []
        for wall, places in PILASTERS.items():
            for along in places:
                at, rotation = _on_wall(wall, along, (shaft_bottom + shaft_top) / 2, 0.0)
                found.append(_part(wall, self.finish.pilaster, shaft, at, rotation))
                below, _ = _on_wall(wall, along, shaft_bottom / 2, 0.11)
                found.append(_part(wall, self.finish.molding, base, below, rotation))
                above, _ = _on_wall(wall, along, shaft_top + 0.08, 0.12)
                found.append(_part(wall, self.finish.molding, capital, above, rotation))
        return found

    def _windows(self) -> list[Part]:
        """Each window's stone surround, sill and bronze glazing bars."""
        stone, bars, found = self.finish.sandstone, self.finish.bronze, []
        for along, low, high in WINDOWS:
            tall = high - low
            for side in (-1, 1):
                at, rotation = _on_wall('right', along + side * (WINDOW_WIDTH / 2 + 0.075),
                                        (low + high) / 2 + 0.05, -0.05)
                found.append(_part('right', stone, surfaces.block((0.15, tall + 0.3, 0.4)),
                                   at, rotation))
            head, rotation = _on_wall('right', along, high + 0.1, -0.05)
            found.append(_part('right', stone, surfaces.block((WINDOW_WIDTH + 0.3, 0.2, 0.4)),
                               head, rotation))
            sill, _ = _on_wall('right', along, low - 0.04, 0.02)
            found.append(_part('right', stone, surfaces.block((WINDOW_WIDTH + 0.4, 0.08, 0.34)),
                               sill, rotation))
            mullion, _ = _on_wall('right', along, (low + high) / 2, -0.12)
            found.append(_part('right', bars, surfaces.block((0.05, tall, 0.05)),
                               mullion, rotation))
            transom, _ = _on_wall('right', along, low + 0.7 * tall, -0.12)
            found.append(_part('right', bars, surfaces.block((WINDOW_WIDTH, 0.05, 0.05)),
                               transom, rotation))
        return found

    def _dais(self) -> list[Part]:
        """Marble steps up to the far wall, each edged with a brass nosing."""
        wide, back, found = WIDTH - 0.02, -LENGTH / 2, []
        for rise, front in STEPS:
            found.append(_part('dais', self.finish.treads,
                               surfaces.block((wide, rise, front - back)),
                               (0.0, rise / 2, (front + back) / 2)))
            found.append(_part('dais', self.finish.nosing, surfaces.block((wide, 0.03, 0.05)),
                               (0.0, rise - 0.01, front + 0.005)))
        return found

    @staticmethod
    def _column_places() -> list[tuple[float, float]]:
        return [(-4.5 + 3.0 * index, -7.0 + 5.0 * (index % 2)) for index in range(4)]

    def _columns(self) -> list[Part]:
        """Four columns of brushed metal, their edges chamfered 5 mm, each under a lamp."""
        found = []
        for (x, z), metal in zip(self._column_places(), self.finish.columns):
            found.append(_part('columns', metal, surfaces.block((0.6, 3.0, 0.6), chamfer=0.005),
                               (x, 1.5, z)))
            found.append(_part('columns', self.finish.lamp, surfaces.block((0.3, 0.3, 0.3)),
                               (x, 3.3, z)))
        return found

    def _lamps(self) -> list[Any]:
        """The light each column's lamp gives the room."""
        return [basenodes.PointLight(location=(x, 3.7, z), intensity=2.0,
                                     color=(1.0, 0.95, 0.85), attenuation=(1.0, 0.0, 0.02),
                                     radius=30.0)
                for x, z in self._column_places()]
