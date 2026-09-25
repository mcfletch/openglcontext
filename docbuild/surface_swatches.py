"""The picture on docs/surfaces.rst: one lit panel of each procedural surface.

Run by tools/doc_images.py (``docs/images/manifest.toml``, id
``pages/surfaces``); it also opens in a window when run directly. Left to
right, top row: checkered marble, veined marble, brick, plaster, sandstone;
bottom row: black marble tiles, glazed tiles, brushed gold, brushed copper,
brushed steel. Each panel is a metre square; the stones are tilted back so
the raking light shows their relief, and the metals lean forward so they
reflect the horizon.
"""
from __future__ import annotations

import math
import os
import sys
from typing import Any

from OpenGLContext import testingcontext
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.scenegraph import basenodes, surfaces

#: The panels are laid out in this many rows.
ROWS = 2


def swatches() -> list[Any]:
    """The scene: a panel of each surface, a camera and a raking light."""
    made = [
        surfaces.checkered_marble(512, tiles=2), surfaces.marble(256),
        surfaces.brick(256), surfaces.plaster(256), surfaces.sandstone(256),
        surfaces.marble_tiles(512, tiles=2), surfaces.tiles(256, count=4),
        surfaces.brushed_metal(256, surfaces.GOLD, 0.25),
        surfaces.brushed_metal(256, surfaces.COPPER, 0.3),
        surfaces.brushed_metal(256, surfaces.STEEL, 0.2),
    ]
    across = len(made) // ROWS
    scene: list[Any] = [
        basenodes.Viewpoint(position=(0.0, 0.0, 5.8), fieldOfView=0.6),
        basenodes.NavigationInfo(headlight=False),
        basenodes.Background(skyColor=[(0.16, 0.17, 0.19)]),
        basenodes.DirectionalLight(direction=(-0.6, -0.5, -0.6), intensity=0.8),
        basenodes.DirectionalLight(direction=(0.5, -0.2, -0.8), intensity=0.15),
    ]
    for index, maps in enumerate(made):
        column, row = index % across, index // across
        at = (1.2 * (column - (across - 1) / 2.0), 0.6 - 1.2 * row, 0.0)
        # A metal is its reflection: tilted back it shows the bright sky and
        # reads as white, leaning forward it shows the horizon and its colour.
        tilt = 12.0 if maps.metallic.mean() > 0.5 else -25.0
        scene.append(surfaces.shape(surfaces.panel(1.0, 1.0), surfaces.pbr_material(maps),
                                    at, (1.0, 0.0, 0.0, math.radians(tilt))))
    return scene


def main() -> int:
    """Open the swatches in a window."""
    os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')
    base: Any = testingcontext.getInteractive()

    class SwatchContext(base):
        def OnInit(self) -> None:
            self.sg = basenodes.sceneGraph(children=swatches())

    SwatchContext.ContextMainLoop(definition=ContextDefinition(
        title='Procedural surfaces', size=(1200, 640)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
