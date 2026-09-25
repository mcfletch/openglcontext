"""The room ``oglc-mirrors`` hangs its mirrors in; no GL, and no mirrors of its own.

A hall 16 metres wide, 24 long and 4.4 high: brick walls, a plaster ceiling,
four brushed-metal columns each under a lamp that lights the room, all made
from :mod:`OpenGLContext.scenegraph.surfaces`. It is scenery. The demo says
what is a mirror and where it goes::

    hall = Hall()
    scene = hall.room() + [hall.floor(polished_floor)]
    scene += hall.hang(surfaces.panel(6.0, 3.0), silver, 'far', along=0.0,
                       height=2.0, frame=hall.finish.gilt)

The floor's material is the caller's, since a polished floor is one of the
mirrors. Coordinates are metres, y up, the room centred on the origin with
the floor at y = 0; the ``far`` wall is at -z.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

__all__ = ['WIDTH', 'LENGTH', 'HEIGHT', 'WALLS', 'Finishes', 'Hall']

#: The room's size in metres: across x, along z, and up.
WIDTH, LENGTH, HEIGHT = 16.0, 24.0, 4.4

#: Each wall by name: the axis it lies across, where, and the rotation that
#: turns a surface facing +z to face into the room from it.
WALLS: Dict[str, Tuple[int, float, Tuple[float, float, float, float]]] = {
    'far': (2, -LENGTH / 2, (0.0, 1.0, 0.0, 0.0)),
    'near': (2, LENGTH / 2, (0.0, 1.0, 0.0, math.pi)),
    'left': (0, -WIDTH / 2, (0.0, 1.0, 0.0, math.pi / 2)),
    'right': (0, WIDTH / 2, (0.0, 1.0, 0.0, -math.pi / 2)),
}

#: How far in front of its wall a hung surface stands, and its frame.
STANDOFF = 0.1
FRAME_DEPTH = 0.1


class Finishes:
    """The hall's materials, made once: stone, brick, plaster and four metals.

    ``floor`` is the checkered marble's maps rather than a material, for the
    demo to make its polished floor from.
    """

    def __init__(self) -> None:
        self.floor = surfaces.checkered_marble(512, tiles=2)
        self.brick = surfaces.pbr_material(surfaces.brick(256))
        self.plaster = surfaces.pbr_material(surfaces.plaster(256), relief=0.5)
        self.sandstone = surfaces.pbr_material(surfaces.sandstone(256))
        self.gilt = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.GOLD, 0.22))
        self.bronze = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.BRONZE, 0.35))
        self.columns = [surfaces.pbr_material(surfaces.brushed_metal(128, colour, rough))
                        for colour, rough in ((surfaces.GOLD, 0.25), (surfaces.COPPER, 0.3),
                                              (surfaces.STEEL, 0.2), (surfaces.BRONZE, 0.32))]
        self.lamp = PBRMaterial(baseColor=(1.0, 0.95, 0.85), metallic=0.0, roughness=0.4,
                                emissiveColor=(1.0, 0.9, 0.7), emissiveStrength=3.0)


def _block(size: Tuple[float, float, float], translation: Tuple[float, float, float],
           material: Any, rotation: Tuple[float, float, float, float] = (0.0, 1.0, 0.0, 0.0)
           ) -> Any:
    return surfaces.shape(surfaces.block(size), material, translation, rotation)


class Hall:
    """The room, and the places in it a demo puts its own surfaces."""

    def __init__(self) -> None:
        self.finish = Finishes()

    def room(self) -> List[Any]:
        """The viewpoint, the light, the walls, the ceiling and the lit columns."""
        return ([basenodes.Viewpoint(position=(0.0, 1.7, 9.0), description='Hall'),
                 basenodes.NavigationInfo(headlight=False, type=['WALK']),
                 basenodes.DirectionalLight(direction=(-0.3, -1.0, -0.4), intensity=0.3)]
                + self._walls() + self._columns())

    def floor(self, material: Any) -> Any:
        """The floor, wearing ``material``; its surface repeats every 2 metres."""
        return surfaces.shape(surfaces.panel(WIDTH, LENGTH, repeat=2.0), material,
                              rotation=(1.0, 0.0, 0.0, -math.pi / 2))

    def hang(self, geometry: surfaces.Geometry, material: Any, wall: str, along: float,
             height: float, frame: Optional[Any] = None, border: float = 0.1) -> List[Any]:
        """``geometry`` wearing ``material``, flat on ``wall`` and facing into the room.

        ``geometry`` lies in its own xy plane facing +z, as
        :func:`~OpenGLContext.scenegraph.surfaces.panel` makes it. ``wall`` is
        one of :data:`WALLS`; ``along`` is the position along it -- x on the
        far and near walls, z on the left and right -- and ``height`` that of
        the surface's centre. ``frame`` is a material for a frame behind it,
        ``border`` metres wider on every side.
        """
        if wall not in WALLS:
            raise ValueError('the hall has no %r wall; it has %s' % (wall, ', '.join(WALLS)))
        axis, at, rotation = WALLS[wall]
        inward = -math.copysign(1.0, at)

        def placed(offset: float) -> Tuple[float, float, float]:
            point = [0.0, height, 0.0]
            point[axis] = at + inward * offset
            point[2 if axis == 0 else 0] = along
            return (point[0], point[1], point[2])

        hung = [surfaces.shape(geometry, material, placed(STANDOFF), rotation)]
        if frame is not None:
            width, tall = np.ptp(geometry.positions[:, :2], axis=0)
            hung.append(_block((float(width) + 2 * border, float(tall) + 2 * border,
                                FRAME_DEPTH), placed(STANDOFF - FRAME_DEPTH / 2 - 0.01),
                               frame, rotation))
        return hung

    def basin(self, x0: float, x1: float, z0: float, z1: float,
              rim: float = 0.3) -> List[Any]:
        """A sandstone rim ``rim`` metres high round a pool from ``x0``-``x1``, ``z0``-``z1``."""
        stone, thick = self.finish.sandstone, 0.2
        middle_x, middle_z = (x0 + x1) / 2.0, (z0 + z1) / 2.0
        across, deep = x1 - x0 + 2 * thick, z1 - z0
        return [_block((across, rim, thick), (middle_x, rim / 2, z0 - thick / 2), stone),
                _block((across, rim, thick), (middle_x, rim / 2, z1 + thick / 2), stone),
                _block((thick, rim, deep), (x0 - thick / 2, rim / 2, middle_z), stone),
                _block((thick, rim, deep), (x1 + thick / 2, rim / 2, middle_z), stone)]

    # -- the room --------------------------------------------------------------
    def _walls(self) -> List[Any]:
        """Four brick walls and a plaster ceiling, faced into the room."""
        brick = self.finish.brick
        walls = []
        for axis, at, rotation in WALLS.values():
            span = WIDTH if axis == 2 else LENGTH
            centre = [0.0, HEIGHT / 2, 0.0]
            centre[axis] = at
            walls.append(surfaces.shape(surfaces.panel(span, HEIGHT), brick,
                                        tuple(centre), rotation))
        walls.append(surfaces.shape(surfaces.panel(WIDTH, LENGTH, repeat=3.0),
                                    self.finish.plaster, (0.0, HEIGHT, 0.0),
                                    (1.0, 0.0, 0.0, math.pi / 2)))
        return walls

    def _columns(self) -> List[Any]:
        """Four columns of brushed metal, each with a lamp over it that lights the room."""
        found: List[Any] = []
        for index, metal in enumerate(self.finish.columns):
            x, z = -4.5 + 3.0 * index, -7.0 + 5.0 * (index % 2)
            found.append(_block((0.6, 3.0, 0.6), (x, 1.5, z), metal))
            found.append(_block((0.3, 0.3, 0.3), (x, 3.3, z), self.finish.lamp))
            found.append(basenodes.PointLight(location=(x, 3.7, z), intensity=0.6,
                                              color=(1.0, 0.95, 0.85),
                                              attenuation=(1.0, 0.0, 0.02),
                                              radius=30.0))
        return found
