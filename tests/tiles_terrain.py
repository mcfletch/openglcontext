#! /usr/bin/env python
"""Demo: streamed OGC 3D Tiles terrain (Phase 1).

Mounts a `TilesTerrain` node over a generated heightfield tileset and streams tiles
as the camera moves. The terrain is updated each frame from the view platform before
the render pass runs, so the visible tile set (coarse root far away, finer quadrant
tiles up close) tracks the viewpoint.

Set ``OGLC_TILES_TILESET`` to point at an existing tileset.json; otherwise a sample
tileset is baked into a temporary directory on startup.
"""
import math
import os
import tempfile

# glTF tiles use PBR materials, which are shader-only, so force the core profile so
# the demo runs when launched directly (not only under the test harness). PBR ambient
# is IBL-based; with no environment probe the analytic sky washes the terrain to flat
# grey, so drive lighting from an explicit sun + modest ambient.
os.environ.setdefault("OPENGLCONTEXT_PROFILE", "core")
os.environ.setdefault("OPENGLCONTEXT_RENDERER", "pbr")  # PBR renderer honours vertex colors
os.environ.setdefault("OPENGLCONTEXT_IBL", "off")

from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import (
    sceneGraph, Transform, DirectionalLight, Background,
)
from OpenGLContext.scenegraph.tilesterrain import TilesTerrain
from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset


class TestContext(BaseContext):
    initialPosition = (0, 150, 175)
    initialOrientation = (-1, 0, 0, 0.62)  # pitch down toward the terrain

    def OnInit(self):
        try:
            import glfw; glfw.swap_interval(0)
        except Exception:
            pass
        print("Streamed 3D Tiles terrain: green heightfield that refines up close")
        tileset = os.environ.get("OGLC_TILES_TILESET")
        if not tileset:
            tmp = tempfile.mkdtemp(prefix="oglc_tiles_")
            tileset = build_sample_tileset(tmp)
        self.terrain = TilesTerrain(
            tileset, fovy=math.radians(45.0), max_sse=12.0, workers=3,
        )
        self.gltf_scene_ambient = 0.12
        self.sg = sceneGraph(children=[
            Background(skyColor=[[0.5, 0.7, 0.95]]),
            DirectionalLight(direction=(-0.5, -1, -0.35), intensity=0.95,
                             color=(1.0, 0.98, 0.9)),
            self.terrain,
        ])
        # Prime the first tiles so the opening frame is populated (a real app would
        # let them stream in over a few frames instead).
        for _ in range(6):
            n = len(self.terrain.update_for_camera(self.initialPosition, 600))
            self.terrain.wait_for_loads(timeout=5.0)
            if n:
                break

    def OnDraw(self, *args, **named):
        # Update the visible tile set from the current viewpoint before the pass runs.
        if getattr(self, "terrain", None) is not None and self.platform is not None:
            height = self.getViewPort()[1] or 600
            camera = tuple(self.platform.position)[:3]
            self.terrain.update_for_camera(camera, height)
        return super(TestContext, self).OnDraw(*args, **named)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
