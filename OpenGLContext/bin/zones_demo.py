#! /usr/bin/env python
"""Zones: a courtyard under the sky and two roofed rooms off it, each lit as a room.

Walk around with the arrow keys and press the keys it prints:

    oglc-zones

    z      the rooms' zones off and on, to see what they do
    t      the east room's statue: shown only while you stand in that room

The west room's zone scales the sky's light down to what a roofed room gets
and names the warm lamp hanging in it, which lights what is inside that room
and nothing in the courtyard. The east room's zone captures a probe from
inside the room, so it is lit by what can be seen from there -- its own
walls, and the courtyard through the door -- and names a cool lamp of its
own. With the zones off, the sky lights both rooms as brightly as the
courtyard and each lamp lights everything it reaches. docs/zones.rst
describes each setting, and this file is the working code for them.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any, Optional

from OpenGLContext.scenegraph import basenodes, surfaces

__all__ = ['ZoneCourt', 'main']

#: A room's inside, (x, y, z) in metres, and its walls' thickness.
ROOM = (6.0, 3.2, 6.0)
WALL = 0.3
#: The door in each room's front wall, (width, height).
DOOR = (3.0, 2.6)
#: The rooms' centres across the courtyard, and how far back they stand.
ROOM_X = {'west': -3.8, 'east': 3.8}
ROOM_Z = -4.0
#: How much of the sky's light a roofed room gets.
ROOF_SHADE = 0.15
#: The lamps: colour and intensity.
LAMPS = {'west': ((1.0, 0.72, 0.42), 3.0), 'east': ((0.55, 0.72, 1.0), 3.0)}
#: Metres beyond each room over which its zone fades out.
BLEND = 0.4


class Finishes:
    """The court's materials, made once: marble, brick, plaster, wood, metals."""

    def __init__(self) -> None:
        self.court = surfaces.pbr_material(surfaces.checkered_marble(512, tiles=8))
        self.wall = surfaces.pbr_material(surfaces.brick(256))
        self.inside = surfaces.pbr_material(surfaces.plaster(256), relief=0.5)
        self.floor = surfaces.pbr_material(surfaces.marble_tiles(512, tiles=4))
        self.stone = surfaces.pbr_material(surfaces.sandstone(256))
        self.bronze = surfaces.pbr_material(
            surfaces.brushed_metal(128, surfaces.BRONZE, 0.25))
        self.gold = surfaces.pbr_material(
            surfaces.brushed_metal(128, surfaces.GOLD, 0.2))
        self.steel = surfaces.pbr_material(
            surfaces.brushed_metal(128, surfaces.STEEL, 0.3))


class ZoneCourt:
    """The scene and its zones, with no window: what the demo and its tests share.

    ``children`` is the scene; ``zones`` maps each room's name to its
    :class:`~OpenGLContext.scenegraph.zone.Zone`, and ``lamps`` to the light
    that zone names. :meth:`press` answers a key.
    """

    KEYS = {
        'z': 'the rooms\' zones off and on',
        't': 'the east room\'s statue shown only from inside, or always',
    }

    def __init__(self, finishes: Optional[Finishes] = None) -> None:
        self.finishes = finishes if finishes is not None else Finishes()
        self.lamps: dict[str, Any] = {}
        self.zones: dict[str, Any] = {}
        #: The transform each zone hangs under; emptied to take a zone away.
        self.holders: dict[str, Any] = {}
        self.sun = basenodes.DirectionalLight(
            direction=(-0.35, -1.0, -0.55), color=(1.0, 0.96, 0.9),
            intensity=2.2, castShadows=True)
        #: The statue only the east room's zone shows.
        self.statue = self._statue()
        self.statue_shown = basenodes.ZoneVisibility(nodes=[self.statue],
                                                     visible=True)
        self.children: list[Any] = [
            basenodes.SimpleBackground(color=(0.62, 0.72, 0.84)),
            self.sun,
            surfaces.shape(surfaces.block((24.0, 0.2, 24.0), repeat=2.0),
                           self.finishes.court, translation=(0.0, -0.1, 0.0)),
            self._fountain(),
            self._everywhere(),
        ]
        for name, x in ROOM_X.items():
            self.children.extend(self._room(name, x))

    # -- the court -------------------------------------------------------
    def _fountain(self) -> Any:
        """A steel basin in the courtyard: lit by the sun, never by a lamp."""
        return surfaces.shape(surfaces.cylinder(1.2, 0.6, sides=24),
                              self.finishes.steel, translation=(0.0, 0.0, 2.5))

    def _statue(self) -> Any:
        return surfaces.shape(surfaces.block((0.5, 1.4, 0.5), chamfer=0.08),
                              self.finishes.gold,
                              translation=(ROOM_X['east'], 1.3, ROOM_Z - 1.5))

    def _everywhere(self) -> Any:
        """The zone the whole court is in, hiding the statue outside the east room.

        A lower priority than the room's own zone, so inside that room the
        room's setting decides.
        """
        self.zones['court'] = basenodes.Zone(
            size=(40.0, 20.0, 40.0), priority=0,
            settings=[basenodes.ZoneVisibility(nodes=[self.statue],
                                               visible=False)])
        self.holders['court'] = basenodes.Transform(
            children=[self.zones['court']])
        return self.holders['court']

    # -- a room ------------------------------------------------------------
    def _room(self, name: str, x: float) -> list[Any]:
        """One room's walls, roof, floor, plinth, lamp and zone."""
        finishes = self.finishes
        width, height, depth = ROOM
        centre = (x, height / 2.0, ROOM_Z)
        front = ROOM_Z + depth / 2.0 + WALL / 2.0
        back = ROOM_Z - depth / 2.0 - WALL / 2.0
        side = width / 2.0 + WALL / 2.0
        jamb = (width + 2 * WALL - DOOR[0]) / 2.0
        parts = [
            surfaces.shape(surfaces.block((width + 2 * WALL, height, WALL)),
                           finishes.wall, translation=(x, height / 2.0, back)),
            surfaces.shape(surfaces.block((WALL, height, depth)),
                           finishes.wall, translation=(x - side, height / 2.0, ROOM_Z)),
            surfaces.shape(surfaces.block((WALL, height, depth)),
                           finishes.wall, translation=(x + side, height / 2.0, ROOM_Z)),
            surfaces.shape(surfaces.block((jamb, height, WALL)), finishes.wall,
                           translation=(x - (DOOR[0] + jamb) / 2.0, height / 2.0, front)),
            surfaces.shape(surfaces.block((jamb, height, WALL)), finishes.wall,
                           translation=(x + (DOOR[0] + jamb) / 2.0, height / 2.0, front)),
            surfaces.shape(surfaces.block((DOOR[0], height - DOOR[1], WALL)),
                           finishes.wall,
                           translation=(x, (height + DOOR[1]) / 2.0, front)),
            surfaces.shape(surfaces.block((width + 2 * WALL, WALL, depth + 2 * WALL)),
                           finishes.inside, translation=(x, height + WALL / 2.0, ROOM_Z)),
            surfaces.shape(surfaces.block((width, 0.05, depth)), finishes.floor,
                           translation=(x, 0.025, ROOM_Z)),
            surfaces.shape(surfaces.block((0.8, 0.9, 0.8), chamfer=0.05),
                           finishes.stone, translation=(x, 0.45, ROOM_Z)),
            surfaces.shape(surfaces.block((0.5, 0.5, 0.5), chamfer=0.1),
                           finishes.bronze, translation=(x, 1.15, ROOM_Z)),
        ]
        colour, intensity = LAMPS[name]
        lamp = basenodes.PointLight(location=(x, height - 0.4, ROOM_Z),
                                    color=colour, intensity=intensity,
                                    radius=8.0, castShadows=False)
        self.lamps[name] = lamp
        settings: list[Any] = [basenodes.ZoneLights(lights=[lamp])]
        if name == 'east':
            settings.append(basenodes.ZoneEnvironment(capture=True,
                                                      intensity=1.0))
            settings.append(self.statue_shown)
            parts.append(self.statue)
        else:
            settings.append(basenodes.ZoneEnvironment(intensity=ROOF_SHADE))
        zone = basenodes.Zone(size=ROOM, blend=BLEND, priority=1,
                              settings=settings)
        self.zones[name] = zone
        self.holders[name] = basenodes.Transform(translation=centre,
                                                 children=[zone])
        return parts + [lamp, self.holders[name]]

    # -- the keys ------------------------------------------------------------
    def placed(self, name: str) -> bool:
        """Whether the zone ``name`` (a room, or ``'court'``) is in the scene."""
        return bool(self.holders[name].children)

    def _place(self, name: str, present: bool) -> None:
        self.holders[name].children = [self.zones[name]] if present else []

    def press(self, key: str) -> str:
        """Answer a key; what changed, for the console, or ''.

        A zone is switched by taking it out of the scene and putting it back,
        which the render pass reads as a change of the scene's structure.
        """
        if key == 'z':
            on = not self.placed('west')
            for name in ROOM_X:
                self._place(name, on)
            return 'zones %s' % ('on' if on else 'off')
        if key == 't':
            hidden = not self.placed('court')
            self._place('court', hidden)
            return ('statue shown only inside the east room' if hidden
                    else 'statue shown everywhere')
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line."""
        return '\n'.join('  %s -- %s' % item for item in cls.KEYS.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the court in a window; ``--help`` prints the keys and exits."""
    argparse.ArgumentParser(
        prog='oglc-zones',
        description=(__doc__ or '').split('\n\n')[0],
        epilog='keys:\n' + ZoneCourt.help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args(argv)
    # The rooms are metallic/roughness materials and the zones are the PBR
    # pass's, so this is the renderer the demo needs.
    os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')
    from OpenGLContext import testingcontext
    from OpenGLContext.contextdefinition import ContextDefinition

    base: Any = testingcontext.getInteractive()

    class ZonesContext(base):                   # pragma: no cover - needs a window
        initialPosition = (0.0, 1.8, 8.0)

        def OnInit(self) -> None:
            self.court = ZoneCourt()
            self.sg = basenodes.sceneGraph(children=self.court.children)
            for key in ZoneCourt.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print('oglc-zones\n' + ZoneCourt.help())

        def OnKey(self, event: Any) -> None:
            said = self.court.press(event.name)
            if said:
                print(said)
                self.triggerRedraw(True)

    ZonesContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext zones', size=(1280, 720)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
