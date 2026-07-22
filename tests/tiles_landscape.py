#! /usr/bin/env python
"""Showcase: streamed procedural landscape with vegetation.

A multi-level 3D Tiles quadtree of procedural terrain — rolling grassland, a river
canyon, a lake, and rocky snow-capped mountains, coloured by per-vertex height/slope
— streamed with frustum-culled LOD, plus instanced shrubs scattered on the grass.

The physics/walk-mode navigation this terrain supports is validated headlessly in
tests/tiles3d/test_navigation.py; this script is the visual showcase.

Env: ``OGLC_TILES_TILESET`` reuses an existing tileset; otherwise one is baked.
"""
import math
import os
import tempfile

os.environ.setdefault("OPENGLCONTEXT_PROFILE", "core")
os.environ.setdefault("OPENGLCONTEXT_RENDERER", "pbr")   # honours vertex colours
os.environ.setdefault("OPENGLCONTEXT_IBL", "off")

from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import (
    sceneGraph, DirectionalLight, Background, Shape, Cone, Box, Appearance, Material,
)
from OpenGLContext.scenegraph.tilesterrain import TilesTerrain
from OpenGLContext.loaders.tiles3d import procedural as P
from OpenGLContext.loaders.tiles3d.vegetation import (
    build_vegetation_lod, build_grass_patch, conifer,
)
from OpenGLContext.loaders.tiles3d.frustum import view_projection


class TestContext(BaseContext):
    initialPosition = (0, 300, 780)
    initialOrientation = (-1, 0, 0, 0.44)

    def OnInit(self):
        print("Streamed procedural landscape: terrain LOD + vegetation")
        try:                                # don't block on vsync (offscreen capture)
            import glfw
            glfw.swap_interval(0)
        except Exception:
            pass
        tileset = os.environ.get("OGLC_TILES_TILESET")
        if not tileset:
            tmp = tempfile.mkdtemp(prefix="oglc_landscape_")
            tileset = P.build_terrain_tileset(tmp, extent=2048, levels=3,
                                              tile_res=33)
        self.terrain = TilesTerrain(tileset, fovy=math.radians(50.0),
                                    max_sse=16.0, workers=4,
                                    memory_budget=256 * 1024 * 1024)
        self.gltf_scene_ambient = 0.35
        water = Shape(geometry=Box(size=(3000, 0.4, 3000)),
                      appearance=Appearance(material=Material(
                          diffuseColor=(0.08, 0.26, 0.40), transparency=0.35,
                          specularColor=(0.5, 0.6, 0.7), shininess=0.9)))
        self.sg = sceneGraph(children=[
            Background(skyColor=[[0.52, 0.70, 0.94]]),
            DirectionalLight(direction=(-0.5, -1, -0.35), intensity=1.0,
                             color=(1.0, 0.97, 0.9)),
            self.terrain,
            water,
            self._vegetation(),
        ])
        for _ in range(6):
            self._update()
            self.terrain.wait_for_loads(timeout=5.0)

    def _vegetation(self):
        # Trees over the central region on grass elevations only, with a distance
        # LOD: full cone mesh near the camera, cheap billboard impostor far away.
        pos, nrm, col, idx = P.terrain_patch(-700, 700, -700, 700, 48)
        near = conifer(height=13.0)
        far = Shape(geometry=Box(size=(6.0, 12.0, 1.0)),
                    appearance=Appearance(material=Material(
                        diffuseColor=(0.10, 0.38, 0.12))))
        keep = lambda p: (p[:, 1] > P.WATER_LEVEL + 4.0) & (p[:, 1] < 130.0)
        return build_vegetation_lod(pos, idx.reshape(-1, 3), near, far,
                                    density=0.00035, seed=7, camera=self._camera(),
                                    near_distance=450.0, scale_range=(0.7, 1.7),
                                    keep=keep)

    def _camera(self):
        return tuple(self.platform.position)[:3] if self.platform else \
            self.initialPosition

    def _update(self):
        eye = self._camera()
        vp = view_projection(eye, (0, 40, 0), (0, 1, 0), math.radians(50),
                             1.0, 1.0, 5000.0)
        self.terrain.update_for_camera(eye, self.getViewPort()[1] or 700,
                                       view_projection=vp)

    def OnDraw(self, *args, **named):
        if getattr(self, "terrain", None) is not None and self.platform is not None:
            self._update()
        return super(TestContext, self).OnDraw(*args, **named)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
