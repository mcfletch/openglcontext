#! /usr/bin/env python
"""Demo: instanced vegetation scattered on terrain (Phase 4).

Scatters many cone "shrubs" over a heightfield surface via the deterministic
surface-scatter; every shrub shares one geometry, so the instancing engine collapses
them into a single draw. Shrubs use a VRML material (reliably lit) for a clear green.
"""
import math
import os

# glTF tiles use PBR materials, which are shader-only: force the core profile (and
# skip analytic-sky IBL, which washes the terrain) so the demo runs when launched
# directly, not only under the test harness's environment.
os.environ.setdefault("OPENGLCONTEXT_IBL", "off")

from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import (
    sceneGraph, DirectionalLight, Background, Shape, Cone, Appearance, Material,
)
from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.tiles3d import sample
from OpenGLContext.loaders.tiles3d.vegetation import build_vegetation_group


class TestContext(BaseContext):
    initialPosition = (0, 90, 200)
    initialOrientation = (-1, 0, 0, 0.5)

    def OnInit(self):
        try:
            import glfw; glfw.swap_interval(0)
        except Exception:
            pass
        print("Instanced vegetation scattered over a heightfield surface")
        pos, nrm, idx = sample._grid_mesh(-120, 120, -120, 120, 21)
        ground = gltf.load_gltf(sample._glb(
            pos, nrm, idx, color=(0.20, 0.32, 0.12, 1.0))).group
        shrub = Shape(
            geometry=Cone(bottomRadius=2.5, height=8.0),
            appearance=Appearance(material=Material(
                diffuseColor=(0.10, 0.55, 0.12))),
        )
        veg = build_vegetation_group(
            pos, idx.reshape(-1, 3), shrub, density=0.004, seed=1,
            scale_range=(0.7, 1.6))
        print("scattered %d shrubs (1 draw via instancing)" % len(veg.children))
        self.gltf_scene_ambient = 0.2
        self.sg = sceneGraph(children=[
            Background(skyColor=[[0.5, 0.7, 0.95]]),
            DirectionalLight(direction=(-0.5, -1, -0.35), intensity=1.0),
            ground,
            veg,
        ])


if __name__ == "__main__":
    TestContext.ContextMainLoop()
