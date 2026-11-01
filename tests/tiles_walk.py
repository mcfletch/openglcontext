#! /usr/bin/env python
"""Walk/fly the streamed procedural landscape (first-person, physics-driven).

Spawns an avatar on the terrain and lets you walk it with gravity + collision, or
toggle free-fly. The terrain's per-tile trimesh bodies stream into the context's
physics service with the visuals, so you walk on exactly what you see; switch to fly, rise up, then switch back to walk
and drop to the surface.

    W / A / S / D      walk forward / left / back / right
    Q / E              turn left / right
    R / F              (fly) rise / descend
    Space              jump
    G                  toggle walk / fly

The same behaviours are validated headlessly in tests/tiles3d/test_navigation.py.
"""
import math
import os
import tempfile

os.environ.setdefault("OPENGLCONTEXT_RENDERER", "pbr")
os.environ.setdefault("OPENGLCONTEXT_IBL", "off")
# A streaming demo is watched for its frame rate, not held to the display's.
os.environ.setdefault("OPENGLCONTEXT_NO_VSYNC", "1")

import numpy as np
from OpenGLContext.context import Context as BaseContext
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph.basenodes import (
    sceneGraph, DirectionalLight, Background,
)
from OpenGLContext.scenegraph.tilesterrain import TilesTerrain
from OpenGLContext.move.physicsplatform import PhysicsViewPlatform
from OpenGLContext.loaders.tiles3d import procedural as P
from OpenGLContext.loaders.tiles3d.frustum import view_projection


def _walkable_spawn():
    best, best_slope = (0.0, 0.0), 1e9
    for x in np.linspace(-300, 300, 13):
        for z in np.linspace(-300, 300, 13):
            h = max(float(P.terrain_height(np.array([x]), np.array([z]))[0]),
                    P.WATER_LEVEL)
            if h < P.WATER_LEVEL + 6 or h > 120:
                continue
            dx = float(P.terrain_height(np.array([x + 5]), np.array([z]))[0]
                       - P.terrain_height(np.array([x - 5]), np.array([z]))[0])
            slope = abs(dx)
            if slope < best_slope:
                best_slope, best = slope, (float(x), float(z))
    h = max(float(P.terrain_height(np.array([best[0]]), np.array([best[1]]))[0]),
            P.WATER_LEVEL)
    return best[0], h, best[1]


class TestContext(BaseContext):
    # The tiles' bodies come from the terrain's colliders, not from the scene's shapes.
    contextDefinition = ContextDefinition(physics=PhysicsDefinition(colliders='explicit'))

    def OnInit(self):
        print("Walk the landscape: WASD move, QE turn, G toggle fly, Space jump")
        tileset = os.environ.get("OGLC_TILES_TILESET")
        if not tileset:
            tileset = P.build_terrain_tileset(
                tempfile.mkdtemp(prefix="oglc_walk_"), extent=2048, levels=3,
                tile_res=33)
        self.terrain = TilesTerrain(tileset, fovy=math.radians(55.0), max_sse=16.0,
                                    workers=4, physics=self.physics,
                                    memory_budget=256 * 1024 * 1024)
        self.gltf_scene_ambient = 0.35
        self.sg = sceneGraph(children=[
            Background(skyColor=[[0.52, 0.70, 0.94]]),
            DirectionalLight(direction=(-0.5, -1, -0.35), intensity=1.0,
                             color=(1.0, 0.97, 0.9)),
            self.terrain,
        ])
        sx, sy, sz = _walkable_spawn()
        # Stream colliders around the spawn before dropping the avatar in.
        for _ in range(8):
            self._stream((sx, sy + 40, sz))
            self.terrain.wait_for_loads(timeout=5.0)
        # The service steps the character each frame.
        walker = self.physics.add_character(position=(sx, sy + 7, sz))
        self.avatar = PhysicsViewPlatform(walker, yaw=0.6)
        self._held = set()
        for k in ("w", "a", "s", "d", "q", "e", "r", "f"):
            self.addEventHandler("keyboard", name=k, state=1,
                                 function=self._down)
            self.addEventHandler("keyboard", name=k, state=0, function=self._up)
        self.addEventHandler("keyboard", name=" ", state=1, function=self._jump)
        self.addEventHandler("keyboard", name="g", state=1, function=self._fly)
        self._flying = False

    def _down(self, event):
        self._held.add(event.name)

    def _up(self, event):
        self._held.discard(event.name)

    def _jump(self, _event):
        self.avatar.jump()

    def _fly(self, _event):
        self._flying = not self._flying
        self.avatar.set_fly(self._flying)

    def _stream(self, eye):
        vp = self._view_projection(eye)
        self.terrain.update_for_camera(eye, self.getViewPort()[1] or 700,
                                       view_projection=vp)

    def _view_projection(self, eye):
        yaw = self.avatar.yaw if getattr(self, "avatar", None) else 0.6
        fwd = (math.sin(yaw), -0.15, -math.cos(yaw))
        center = (eye[0] + fwd[0] * 50, eye[1] + fwd[1] * 50, eye[2] + fwd[2] * 50)
        return view_projection(eye, center, (0, 1, 0), math.radians(55), 1.3,
                               1.0, 5000.0)

    def OnDraw(self, *args, **named):
        if getattr(self, "avatar", None) is not None:
            held = self._held
            fwd = ("w" in held) - ("s" in held)
            strafe = ("d" in held) - ("a" in held)
            self.avatar.turn(0.03 * (("q" in held) - ("e" in held)))
            if self._flying:
                up = ("r" in held) - ("f" in held)
                self.avatar.set_fly_move(fwd, strafe, up)
            else:
                self.avatar.set_move(fwd, strafe)
            self.avatar.apply(self)
            self._stream(self.avatar.camera_position())
        return super(TestContext, self).OnDraw(*args, **named)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
