"""oglc-mirrors: a hall of mirrors, built with the engine's reflection API.

A hall with a polished floor, a large mirror on the far wall, a corridor of
small mirrors down one side, a pool of still water, and a window on the other
side that shows only what it reflects. Each is one of the ways a surface is
made a mirror (see docs/reflections.rst):

* the far mirror is a silvered material carrying a ``PlanarReflector``;
* the floor is a polished dielectric, which reflects faintly looking down and
  strongly at a glance, with a low priority and a two-frame interval;
* the corridor's ten mirrors share one reflector, so they are tuned together;
* the pool is water, which is a mirror whatever it is made of;
* the window is a reflector that replaces its surface's shading.

Keys:

``r``
    Reflections on and off (``ContextDefinition.planarReflections``).
``b``
    The mirror views a frame may draw (``reflectionViews``): the strategy's
    own, then 1, 2 and 4, to watch the schedule share them out.
``i``
    The corridor's interval: 1, 3 or 6 frames between redraws.
``o``
    The window between showing only its reflection and being shaded as glass.

Walk with the arrow keys; the developer overlay shows each frame's mirror
views, their draws, texels and GPU time.
"""
from __future__ import annotations

import logging
import math
import sys
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.reflector import PlanarReflector
from OpenGLContext.scenegraph.water import STILL, water_surface

log = logging.getLogger(__name__)

__all__ = ['BUDGETS', 'INTERVALS', 'Finishes', 'MirrorHall', 'main']

#: The ``reflectionViews`` the ``b`` key steps through; 0 is the strategy's own.
BUDGETS: Tuple[int, ...] = (0, 1, 2, 4)

#: The corridor intervals the ``i`` key steps through.
INTERVALS: Tuple[int, ...] = (3, 1, 6)


def _panel(width: float, height: float, texture: float = 1.0) -> Tuple[np.ndarray, ...]:
    """A flat rectangle in its own xy plane, facing +z.

    Its texture coordinates are in units of ``texture`` metres, so a surface
    repeats at the size it was drawn for however large the panel is.
    """
    half_w, half_h = width / 2.0, height / 2.0
    positions = np.array([(-half_w, -half_h, 0), (half_w, -half_h, 0),
                          (half_w, half_h, 0), (-half_w, half_h, 0)], 'f')
    normals = np.array([(0, 0, 1)] * 4, 'f')
    texcoords = ((positions[:, :2] + (half_w, half_h)) / texture).astype('f')
    return positions, normals, texcoords, np.array([0, 1, 2, 0, 2, 3], np.uint32)


def _octagon(radius: float) -> Tuple[np.ndarray, ...]:
    """A flat octagon in its own xy plane, facing +z: a round window."""
    angles = [math.pi / 8 + index * math.pi / 4 for index in range(8)]
    rim = [(radius * math.cos(a), radius * math.sin(a), 0.0) for a in angles]
    positions = np.array([(0.0, 0.0, 0.0)] + rim, 'f')
    normals = np.array([(0, 0, 1)] * 9, 'f')
    texcoords = (positions[:, :2] / (2 * radius) + 0.5).astype('f')
    indices = np.array([index for side in range(8)
                        for index in (0, 1 + side, 1 + (side + 1) % 8)], np.uint32)
    return positions, normals, texcoords, indices


def _surface(arrays: Tuple[np.ndarray, ...], material: PBRMaterial,
             translation: Sequence[float], rotation: Sequence[float] = (0, 1, 0, 0)) -> Any:
    positions, normals, texcoords, indices = arrays
    # The panels lie in their own xy plane, so +x is the tangent a normal map
    # is read along.
    tangents = np.tile(np.array([1.0, 0.0, 0.0, 1.0], 'f'), (len(positions), 1))
    mesh = PBRMesh(positions=positions, normals=normals, texcoords=texcoords,
                   tangents=tangents, indices=indices, material=material)
    return basenodes.Transform(translation=tuple(translation), rotation=tuple(rotation),
                               children=[basenodes.Shape(
                                   geometry=mesh,
                                   appearance=basenodes.Appearance(material=material))])


def _block(size: Sequence[float], translation: Sequence[float], material: Any) -> Any:
    return basenodes.Transform(translation=tuple(translation), children=[basenodes.Shape(
        geometry=basenodes.Box(size=tuple(size)),
        appearance=basenodes.Appearance(material=material))])


class Finishes:
    """The hall's materials, made once: stone, brick, plaster and four metals."""

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


class MirrorHall:
    """The hall, and what each key does to it; no GL.

    :attr:`children` is the scene. :meth:`press` applies a key to the hall and
    to the context's definition and answers what it now is, as one line.
    """

    #: The keys :meth:`press` answers, and what each does.
    KEYS: Dict[str, str] = {
        'r': 'reflections on and off',
        'b': 'mirror views a frame may draw',
        'i': "the corridor's interval",
        'o': 'the window: only its reflection, or shaded glass',
    }

    def __init__(self) -> None:
        #: The far wall's mirror: silvered, redrawn every other frame.
        self.mirror = PlanarReflector(interval=2, priority=2.0)
        #: One reflector the corridor's ten mirrors share.
        self.corridor = PlanarReflector(interval=INTERVALS[0], scale=0.35)
        #: The floor: large on screen, so a low priority keeps it from
        #: crowding the mirrors out of a short budget.
        self.floor = PlanarReflector(interval=2, priority=0.5)
        #: The window, which shows nothing of its own material.
        self.window = PlanarReflector(replace=True, interval=1)
        self.children: List[Any] = self._build()

    # -- the hall ----------------------------------------------------------
    def _build(self) -> List[Any]:
        finish = Finishes()
        silver = PBRMaterial(baseColor=surfaces.SILVER, metallic=1.0, roughness=0.02,
                             reflector=self.mirror)
        corridor = PBRMaterial(baseColor=surfaces.SILVER, metallic=1.0, roughness=0.03,
                               reflector=self.corridor)
        marble = surfaces.pbr_material(finish.floor, reflector=self.floor)
        window = PBRMaterial(baseColor=(0.6, 0.8, 0.9), metallic=0.0, roughness=0.05,
                             reflector=self.window)
        children: List[Any] = [
            basenodes.Viewpoint(position=(0.0, 1.7, 9.0), description='Hall'),
            basenodes.NavigationInfo(headlight=False, type=['WALK']),
            basenodes.DirectionalLight(direction=(-0.3, -1.0, -0.4), intensity=0.3),
            # The floor's texture is two tiles of a metre each way.
            _surface(_panel(16.0, 24.0, texture=2.0), marble, (0.0, 0.0, 0.0),
                     (1, 0, 0, -math.pi / 2)),
            _surface(_panel(6.0, 3.0), silver, (0.0, 2.0, -11.9)),
            _block((6.4, 3.4, 0.1), (0.0, 2.0, -11.97), finish.gilt),
            _surface(_octagon(1.5), window, (7.9, 2.0, 0.0), (0, 1, 0, -math.pi / 2)),
        ]
        for index in range(10):
            z = -9.0 + 2.0 * index
            children.append(_surface(_panel(1.0, 1.4), corridor, (-7.9, 1.8, z),
                                     (0, 1, 0, math.pi / 2)))
            children.append(_block((0.08, 1.6, 1.2), (-7.96, 1.8, z), finish.bronze))
        children += self._walls(finish) + self._pool(finish) + self._props(finish)
        return children

    @staticmethod
    def _walls(finish: Finishes) -> List[Any]:
        """Four brick walls and a plaster ceiling, faced into the room."""
        brick, plaster = finish.brick, finish.plaster
        half_pi = math.pi / 2
        return [
            _surface(_panel(16.0, 4.4), brick, (0.0, 2.2, -12.0)),
            _surface(_panel(16.0, 4.4), brick, (0.0, 2.2, 12.0), (0, 1, 0, math.pi)),
            _surface(_panel(24.0, 4.4), brick, (-8.0, 2.2, 0.0), (0, 1, 0, half_pi)),
            _surface(_panel(24.0, 4.4), brick, (8.0, 2.2, 0.0), (0, 1, 0, -half_pi)),
            _surface(_panel(16.0, 24.0, texture=3.0), plaster, (0.0, 4.4, 0.0),
                     (1, 0, 0, half_pi)),
        ]

    @staticmethod
    def _pool(finish: Finishes) -> List[Any]:
        water = water_surface(1.5, 5.5, -6.0, -2.0, level=0.25, resolution=9,
                              style=STILL, on_gpu=True)
        rim = finish.sandstone
        return [basenodes.Shape(geometry=water,
                                appearance=basenodes.Appearance(material=water.material)),
                _block((4.4, 0.3, 0.2), (3.5, 0.15, -6.1), rim),
                _block((4.4, 0.3, 0.2), (3.5, 0.15, -1.9), rim),
                _block((0.2, 0.3, 4.0), (1.4, 0.15, -4.0), rim),
                _block((0.2, 0.3, 4.0), (5.6, 0.15, -4.0), rim)]

    @staticmethod
    def _props(finish: Finishes) -> List[Any]:
        """Four columns of brushed metal, each with a lamp over it that lights the room."""
        found: List[Any] = []
        for index, metal in enumerate(finish.columns):
            x, z = -4.5 + 3.0 * index, -7.0 + 5.0 * (index % 2)
            found.append(_block((0.6, 3.0, 0.6), (x, 1.5, z), metal))
            found.append(_block((0.3, 0.3, 0.3), (x, 3.3, z), finish.lamp))
            found.append(basenodes.PointLight(location=(x, 3.7, z), intensity=0.6,
                                              color=(1.0, 0.95, 0.85),
                                              attenuation=(1.0, 0.0, 0.02),
                                              radius=30.0))
        return found

    # -- the keys ----------------------------------------------------------
    def press(self, key: str, definition: Any) -> str:
        """Apply ``key`` to the hall and ``definition``; what it now is.

        An empty answer for a key the hall does not use.
        """
        if key == 'r':
            definition.planarReflections = not bool(definition.planarReflections)
            return 'reflections %s' % ('on' if definition.planarReflections else 'off')
        if key == 'b':
            now = int(getattr(definition, 'reflectionViews', 0) or 0)
            following = BUDGETS[(BUDGETS.index(now) + 1) % len(BUDGETS)
                                if now in BUDGETS else 0]
            definition.reflectionViews = following
            return 'mirror views a frame: %s' % (following or "the strategy's own")
        if key == 'i':
            now = int(self.corridor.interval)
            following = INTERVALS[(INTERVALS.index(now) + 1) % len(INTERVALS)
                                  if now in INTERVALS else 0]
            self.corridor.interval = following
            return 'corridor redrawn every %d frame%s' % (following, '' if following == 1 else 's')
        if key == 'o':
            self.window.replace = not bool(self.window.replace)
            return 'window: %s' % ('only its reflection' if self.window.replace
                                   else 'shaded glass')
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line."""
        return '\n'.join('  %s -- %s' % item for item in cls.KEYS.items())


def main() -> int:
    """Open the hall in a window."""
    import os
    # The mirrors are metallic/roughness materials, which the PBR pass draws.
    os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')
    from OpenGLContext import testingcontext
    from OpenGLContext.contextdefinition import ContextDefinition

    base: Any = testingcontext.getInteractive()

    class MirrorContext(base):  # type: ignore[misc, valid-type]
        def OnInit(self) -> None:
            self.hall = MirrorHall()
            self.sg = basenodes.sceneGraph(children=self.hall.children)
            for key in MirrorHall.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print('oglc-mirrors\n' + MirrorHall.help())

        def OnKey(self, event: Any) -> None:
            said = self.hall.press(event.name, self.contextDefinition)
            if said:
                print(said)
                self.triggerRedraw(True)

    logging.basicConfig(level=logging.INFO)
    MirrorContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext mirrors', size=(1280, 720)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
