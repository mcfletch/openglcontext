#! /usr/bin/env python
"""Levels of detail: orbs on plinths down a marble hall, coarser as they recede.

Walk down the hall with the arrow keys and press the keys it prints:

    oglc-lod

    t      tint each level its own metal, to see where the levels change
    h      hysteresis off and on: off, a level changes exactly at its threshold

The left row is a ``ScreenCoverageLOD`` per orb, built in code: four spheres,
from 48 sides round to 6, each drawn while the orb covers at least its share
of the window's height. The right row is the same chain written to a glTF
file with ``MSFT_lod`` and read back, which is how a model brings its own
levels. Down the middle, VRML97's ``LOD`` chooses the columns' levels by
distance. docs/lod.rst describes each node, and this file is the working code
for them.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any, Optional

from OpenGLContext.scenegraph import basenodes, surfaces

__all__ = ['LODHall', 'main']

#: How many orbs stand down each side, and how far apart, in metres.
ROWS = 10
SPACING = 3.0
#: How far each row stands from the middle of the hall.
ACROSS = 2.0
#: An orb's radius, and how many sides each of its levels has round its equator.
RADIUS = 0.35
SIDES = (48, 24, 12, 6)
#: The share of the window's height at which each level takes over. The last is
#: 0, so the coarsest level stays on screen however far away it is.
COVERAGE = (0.25, 0.12, 0.05, 0.0)
#: A column's levels, by sides round, and the distances between them in metres.
COLUMN_SIDES = (32, 12, 6)
COLUMN_RANGE = (12.0, 24.0)
#: The height of a plinth and of a column.
PLINTH = 1.0
COLUMN = 2.4


class Finishes:
    """The hall's materials, made once: marble, sandstone, and a metal per level."""

    def __init__(self) -> None:
        self.floor = surfaces.pbr_material(surfaces.marble_tiles(512, tiles=4))
        self.plinth = surfaces.pbr_material(surfaces.sandstone(256))
        self.column = surfaces.pbr_material(surfaces.marble(256))
        self.orb = surfaces.pbr_material(
            surfaces.brushed_metal(128, surfaces.BRONZE, 0.25))
        #: What each level wears while the levels are tinted, finest first.
        self.tints = [surfaces.pbr_material(surfaces.brushed_metal(128, colour, rough))
                      for colour, rough in ((surfaces.GOLD, 0.2),
                                            (surfaces.COPPER, 0.3),
                                            (surfaces.STEEL, 0.3),
                                            (surfaces.SILVER, 0.5))]


class LODHall:
    """The scene and its levels of detail, with no window.

    ``children`` is the scene. ``chains`` are the orbs' ``ScreenCoverageLOD``
    nodes, the code-built row first and then the row read from the file, and
    ``columns`` the distance ``LOD`` nodes. :meth:`press` answers a key.
    """

    KEYS = {
        't': 'each level tinted its own metal, or all bronze',
        'h': 'hysteresis off, or back on at its default',
    }

    def __init__(self, finishes: Optional[Finishes] = None) -> None:
        self.finishes = finishes if finishes is not None else Finishes()
        self.tinted = False
        self.chains: list[Any] = []
        self.columns: list[Any] = []
        #: What each level's shapes wear untinted, by shape.
        self._worn: dict[Any, Any] = {}
        length = ROWS * SPACING
        self.children: list[Any] = [
            basenodes.SimpleBackground(color=(0.55, 0.62, 0.72)),
            basenodes.DirectionalLight(direction=(-0.3, -1.0, -0.45),
                                       color=(1.0, 0.96, 0.9), intensity=2.4),
            surfaces.shape(surfaces.block((10.0, 0.2, length + 6.0), repeat=2.0),
                           self.finishes.floor,
                           translation=(0.0, -0.1, -length / 2.0 + 3.0)),
        ]
        for row in range(ROWS):
            z = -row * SPACING
            for x in (-ACROSS, ACROSS):
                self.children.append(surfaces.shape(
                    surfaces.block((0.6, PLINTH, 0.6), chamfer=0.04),
                    self.finishes.plinth, translation=(x, PLINTH / 2.0, z)))
            self.children.append(self._orb((-ACROSS, PLINTH + RADIUS, z)))
            if row % 3 == 1:
                self.children.append(self._column((0.0, COLUMN / 2.0, z)))
        self.children.append(self._from_file())

    # -- the rows ------------------------------------------------------------
    def _orb(self, at: Sequence[float]) -> Any:
        """One orb as a ScreenCoverageLOD built in code."""
        levels = [surfaces.shape(surfaces.sphere(RADIUS, sides=sides, repeat=0.25),
                                 self.finishes.orb)
                  for sides in SIDES]
        chain = basenodes.ScreenCoverageLOD(level=levels,
                                            screenCoverage=list(COVERAGE))
        self.chains.append(chain)
        return basenodes.Transform(translation=tuple(at), children=[chain])

    def _column(self, at: Sequence[float]) -> Any:
        """One column as a VRML97 LOD, chosen by distance."""
        levels = [surfaces.shape(surfaces.cylinder(0.3, COLUMN, sides=sides,
                                                   repeat=0.5),
                                 self.finishes.column)
                  for sides in COLUMN_SIDES]
        column = basenodes.LOD(level=levels, range=list(COLUMN_RANGE))
        self.columns.append(column)
        return basenodes.Transform(translation=tuple(at), children=[column])

    def _from_file(self) -> Any:
        """The right-hand row, written as MSFT_lod chains and read back."""
        from OpenGLContext.loaders.gltf import load_gltf
        from OpenGLContext.loaders.gltf.writer import GLTFWriter, SceneNode
        from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh
        copper = PBRMaterial(baseColor=surfaces.COPPER, metallic=1.0,
                             roughness=0.3)
        writer = GLTFWriter()
        for row in range(ROWS):
            at = (ACROSS, PLINTH + RADIUS, -row * SPACING)
            levels = []
            for sides in SIDES:
                ball = surfaces.sphere(RADIUS, sides=sides, repeat=0.25)
                levels.append(SceneNode(
                    mesh=PBRMesh(positions=ball.positions, normals=ball.normals,
                                 texcoords=ball.texcoords, indices=ball.indices,
                                 material=copper),
                    translation=at))
            writer.add_lod(levels, coverage=COVERAGE)
        scene = load_gltf(writer.to_glb())
        self.chains.extend(_chains_under(scene.group))
        return scene.group

    # -- the keys ------------------------------------------------------------
    def levels(self) -> list[list[Any]]:
        """Every level-of-detail node's levels, the orbs' first, then the columns'."""
        return [list(node.level) for node in self.chains + self.columns]

    def _tint(self, on: bool) -> None:
        from OpenGLContext.loaders.assets import shapes
        for levels in self.levels():
            for index, level in enumerate(levels):
                tint = self.finishes.tints[min(index, len(self.finishes.tints) - 1)]
                for shape in shapes(level):
                    worn = self._worn.setdefault(shape, shape.appearance.material)
                    shape.appearance.material = tint if on else worn
        self.tinted = on

    def press(self, key: str) -> str:
        """Answer a key; what changed, for the console, or ''."""
        if key == 't':
            self._tint(not self.tinted)
            return ('each level tinted: gold, copper, steel, silver'
                    if self.tinted else 'the levels in their own materials')
        if key == 'h':
            on = not self.chains[0].hysteresis
            for node in self.chains + self.columns:
                node.hysteresis = 0.1 if on else 0.0
            return 'hysteresis %s' % ('on' if on else 'off')
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line."""
        return '\n'.join('  %s -- %s' % item for item in cls.KEYS.items())


def _chains_under(node: Any) -> list[Any]:
    """Every ScreenCoverageLOD below ``node``, in document order."""
    from OpenGLContext.scenegraph.lod import ScreenCoverageLOD
    found: list[Any] = []
    stack = [node]
    while stack:
        current = stack.pop(0)
        if isinstance(current, ScreenCoverageLOD):
            found.append(current)
        stack.extend(getattr(current, 'children', None) or ())
    return found


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the hall in a window; ``--help`` prints the keys and exits."""
    argparse.ArgumentParser(
        prog='oglc-lod',
        description=(__doc__ or '').split('\n\n')[0],
        epilog='keys:\n' + LODHall.help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args(argv)
    # The orbs and the hall are metallic/roughness materials.
    os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')
    from OpenGLContext import testingcontext
    from OpenGLContext.contextdefinition import ContextDefinition

    base: Any = testingcontext.getInteractive()

    class LODContext(base):                     # pragma: no cover - needs a window
        initialPosition = (0.0, 1.6, 4.0)

        def OnInit(self) -> None:
            self.hall = LODHall()
            self.sg = basenodes.sceneGraph(children=self.hall.children)
            for key in LODHall.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print('oglc-lod\n' + LODHall.help())

        def OnKey(self, event: Any) -> None:
            said = self.hall.press(event.name)
            if said:
                print(said)
                self.triggerRedraw(True)

    LODContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext levels of detail', size=(1280, 720)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
