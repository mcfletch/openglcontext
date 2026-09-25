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
``m``
    How deep mirrors seen in mirrors are followed (``reflectionBounces``):
    2, 3, then 1, where a mirror seen in another reflects the probe.
``i``
    The corridor's interval: 1, 3 or 6 frames between redraws.
``o``
    The window between showing only its reflection and being shaded as glass.

Walk with the arrow keys; the developer overlay shows each frame's mirror
views, their draws, texels and GPU time.

The room is :mod:`OpenGLContext.bin.mirrorhall`, which has no mirrors of its
own; everything here is about the mirrors.
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Dict, List, Tuple

from OpenGLContext.bin.mirrorhall import Hall
from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.reflector import PlanarReflector
from OpenGLContext.scenegraph.water import STILL, water_surface

log = logging.getLogger(__name__)

__all__ = ['BOUNCES', 'BUDGETS', 'INTERVALS', 'MirrorHall', 'main']

#: The ``reflectionViews`` the ``b`` key steps through; 0 is the strategy's own.
BUDGETS: Tuple[int, ...] = (0, 1, 2, 4)

#: The ``reflectionBounces`` the ``m`` key steps through.
BOUNCES: Tuple[int, ...] = (2, 3, 1)

#: The corridor intervals the ``i`` key steps through.
INTERVALS: Tuple[int, ...] = (3, 1, 6)


class MirrorHall:
    """The hall, and what each key does to it; no GL.

    :attr:`children` is the scene. :meth:`press` applies a key to the hall and
    to the context's definition and answers what it now is, as one line.
    """

    #: The keys :meth:`press` answers, and what each does.
    KEYS: Dict[str, str] = {
        'r': 'reflections on and off',
        'b': 'mirror views a frame may draw',
        'm': 'how deep mirrors seen in mirrors are followed',
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

    # -- the mirrors -------------------------------------------------------
    def _build(self) -> List[Any]:
        hall = Hall()
        # A mirror is a material carrying a reflector: silvered metal, polished
        # marble, or glass that shows only what it reflects.
        silver = PBRMaterial(baseColor=surfaces.SILVER, metallic=1.0, roughness=0.02,
                             reflector=self.mirror)
        corridor = PBRMaterial(baseColor=surfaces.SILVER, metallic=1.0, roughness=0.03,
                               reflector=self.corridor)
        marble = surfaces.pbr_material(hall.finish.floor, reflector=self.floor)
        window = PBRMaterial(baseColor=(0.6, 0.8, 0.9), metallic=0.0, roughness=0.05,
                             reflector=self.window)
        # Water is a mirror whatever it is made of.
        pool = water_surface(1.5, 5.5, -6.0, -2.0, level=0.25, resolution=9,
                             style=STILL, on_gpu=True)
        scene = hall.room() + [hall.floor(marble)]
        scene += hall.hang(surfaces.panel(6.0, 3.0), silver, 'far', along=0.0, height=2.0,
                           frame=hall.finish.gilt, border=0.2)
        scene += hall.hang(surfaces.polygon(1.5), window, 'right', along=0.0, height=2.0)
        for index in range(10):
            scene += hall.hang(surfaces.panel(1.0, 1.4), corridor, 'left',
                               along=-9.0 + 2.0 * index, height=1.8,
                               frame=hall.finish.bronze)
        scene.append(basenodes.Shape(geometry=pool,
                                     appearance=basenodes.Appearance(material=pool.material)))
        scene += hall.basin(1.5, 5.5, -6.0, -2.0)
        return scene

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
        if key == 'm':
            now = int(getattr(definition, 'reflectionBounces', 2) or 2)
            following = BOUNCES[(BOUNCES.index(now) + 1) % len(BOUNCES)
                                if now in BOUNCES else 0]
            definition.reflectionBounces = following
            return 'mirrors followed %d reflection%s deep' % (
                following, '' if following == 1 else 's')
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

    class MirrorContext(base):
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
