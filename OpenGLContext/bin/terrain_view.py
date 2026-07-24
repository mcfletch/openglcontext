#! /usr/bin/env python
"""``oglc-terrain`` — view and walk a streamed 3D-Tiles terrain world.

Bakes (or loads) a terrain tileset and lets you walk it first-person with gravity +
collision, or free-fly. The terrain streams with frustum-culled level-of-detail;
collision comes from the terrain surface so you walk on what you see. Vegetation
(distance-LOD conifers) is scattered on grass elevations and a translucent water
surface fills the valleys.

Sources:
  * (default)            a procedural world — rolling hills, a river canyon, a lake,
                         and snow-capped mountains
  * ``--dem IMAGE``      a real heightmap (grayscale DEM: PNG/TIFF, e.g. QGIS/USGS/SRTM)
  * ``TILESET.json``     an existing OGC 3D Tiles tileset (positional; fly-only)

Examples::

    oglc-terrain                         # walk the default procedural world
    oglc-terrain --fly                   # start in free-fly
    oglc-terrain --extent 4096 --levels 4
    oglc-terrain --dem heightmap.png --height-scale 600
    oglc-terrain path/to/tileset.json

Controls:
    W / A / S / D      move        Q / E   turn
    Shift  (hold)      sprint      G       toggle walk / fly
    R / F              fly up / down       Space   jump
    - / =              slower / faster (fly & sprint speed)
"""
import argparse
import math
import os
import sys
import tempfile
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

os.environ.setdefault("OPENGLCONTEXT_PROFILE", "core")
os.environ.setdefault("OPENGLCONTEXT_RENDERER", "pbr")
os.environ.setdefault("OPENGLCONTEXT_IBL", "off")
os.environ.setdefault("OPENGLCONTEXT_BACKEND", "glfw")
os.environ.setdefault("OPENGLCONTEXT_SHADOWS", "1")          # sun shadows through the canopy
os.environ.setdefault("OPENGLCONTEXT_SHADOW_CASCADES", "3")

import numpy as np
from OpenGLContext import testingcontext
from OpenGLContext.scenegraph.scenegraph import SceneGraph as sceneGraph
from OpenGLContext.scenegraph.light import DirectionalLight
from OpenGLContext.scenegraph.background import Background
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.quadrics import Cone
from OpenGLContext.scenegraph.box import Box
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.material import Material
from OpenGLContext.scenegraph.tilesterrain import TilesTerrain
from OpenGLContext.scenegraph.group import Group
from omi_physics.world import PhysicsWorld
from omi_physics import model
from omi_physics.character import CharacterCapabilities
from OpenGLContext.move.physicsplatform import PhysicsViewPlatform
from OpenGLContext.loaders.tiles3d import procedural as P
from OpenGLContext.loaders.tiles3d import dem as DEM
from OpenGLContext.loaders.tiles3d.vegetation import (
    scatter_disc, group_from_scatter, partition_by_distance,
)
from OpenGLContext.loaders.tiles3d import foliage
from OpenGLContext.loaders import cc0
from OpenGLContext.loaders.tiles3d.frustum import view_projection

if TYPE_CHECKING:
    from OpenGLContext.context import Context as BaseContext
    from OpenGLContext.loaders.tiles3d.scatter import Scatter
else:
    BaseContext = testingcontext.getInteractive()

HOLD = 0.6           # seconds a key event keeps driving movement; wide enough to bridge
                     # the OS char-repeat initial delay when only 'keypress' events come
                     # (key-up on 'keyboard', where available, stops movement promptly)


def _slice_scatter(s: "Scatter", i: int, n: int) -> "Scatter":
    """Every n-th placement, so a scatter can be split across several prototypes."""
    from OpenGLContext.loaders.tiles3d.scatter import Scatter
    return Scatter(s.positions[i::n], s.yaws[i::n], s.scales[i::n])


def _resolve_world(cfg: argparse.Namespace) -> tuple[str, "P.HeightFn | None"]:
    """Return (tileset_path, height_fn|None). height_fn drives collision + vegetation."""
    if cfg.source and cfg.source.endswith(".json"):
        return cfg.source, None
    directory = tempfile.mkdtemp(prefix="oglc_terrain_")
    if cfg.dem:
        height_fn = DEM.height_function_from_image(
            cfg.dem, cfg.extent, cfg.height_scale, base=cfg.base)
    else:
        height_fn = P.terrain_height
    path = P.build_terrain_tileset(directory, extent=cfg.extent, levels=cfg.levels,
                                   tile_res=cfg.tile_res,
                                   height_fn=None if height_fn is P.terrain_height
                                   else height_fn)
    return path, height_fn


def _surface(height_fn: "P.HeightFn", x: float, z: float) -> float:
    return max(float(height_fn(np.array([x]), np.array([z]))[0]), P.WATER_LEVEL)


def _water(extent: float) -> Shape:
    """A large translucent water surface at the water level."""
    return Shape(
        geometry=Box(size=(extent * 1.2, 0.4, extent * 1.2)),
        appearance=Appearance(material=Material(
            diffuseColor=(0.08, 0.26, 0.40), transparency=0.35,
            specularColor=(0.5, 0.6, 0.7), shininess=0.9)))


def _walkable_spawn(height_fn: "P.HeightFn") -> tuple[float, float, float]:
    best, best_slope = (0.0, 0.0), 1e9
    for x in np.linspace(-300, 300, 13):
        for z in np.linspace(-300, 300, 13):
            h = _surface(height_fn, x, z)
            if h < P.WATER_LEVEL + 6 or h > 120:
                continue
            slope = abs(_surface(height_fn, x + 5, z) - _surface(height_fn, x - 5, z))
            if slope < best_slope:
                best_slope, best = slope, (float(x), float(z))
    return best[0], _surface(height_fn, *best), best[1]


class TerrainContext(BaseContext):
    config: Any = None
    # Members supplied by the interactive runtime base (event + navigation mixins)
    # that the minimal type-check-time ``Context`` alias does not expose.
    addEventHandler: Any
    movementManager: Any

    def OnInit(self) -> None:  # pragma: no cover - live GL context, streaming + upload
        from OpenGLContext.physics.demo import disable_vsync
        disable_vsync()
        cfg = self.config
        sys.stdout.write(__doc__[__doc__.index("Controls:"):])
        sys.stdout.flush()
        tileset, self.height_fn = _resolve_world(cfg)

        # No trimesh floor: terrain is a height field, so we clamp the avatar to
        # height_fn analytically each frame (exact, matches the visuals, and cannot be
        # tunnelled through at any frame rate). The physics world still gives gravity,
        # jumping and smooth motion.
        self.world = PhysicsWorld(
            gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
        self.gltf_scene_ambient = 0.28             # lower fill -> shadows read stronger
        children = [
            # A gradient sky needs >=2 skyColors + a skyAngle; a lone skyColor renders
            # an empty color set (the whole frame clears to black).
            Background(
                skyColor=[[0.24, 0.44, 0.78], [0.52, 0.70, 0.94],
                          [0.82, 0.90, 0.98]],
                skyAngle=[1.20, 1.5708],
                groundColor=[[0.40, 0.44, 0.36], [0.55, 0.55, 0.48]],
                groundAngle=[1.5708]),
            DirectionalLight(direction=(-0.45, -0.8, -0.4), intensity=1.25,
                             color=(1.0, 0.95, 0.82)),
        ]
        # For a procedural/DEM world the ground is a detailed camera-following textured
        # patch (below); the coarse streamed tiles are only used to render a raw
        # tileset.json, which has no height field to build a patch from.
        self.terrain = None
        if self.height_fn is None:
            self.terrain = TilesTerrain(tileset, fovy=math.radians(60.0),
                                        max_sse=cfg.sse, workers=4,
                                        memory_budget=cfg.memory * 1024 * 1024)
            children.append(self.terrain)
        else:
            children.append(_water(cfg.extent))
        self.sg = sceneGraph(children=children)

        if self.height_fn is not None:
            sx, sy, sz = _walkable_spawn(self.height_fn)
        else:
            sx, sy, sz = 0.0, 200.0, 0.0
        self._spawn_xz = np.array([sx, sz])
        if self.terrain is not None:
            for _ in range(8):
                self._stream((sx, sy + 40, sz))
                self.terrain.wait_for_loads(timeout=5.0)

        # Dense forest, in two camera-following layers: a wide, slowly-refreshed tree +
        # shrub field, and a tight, frequently-refreshed grass field you walk through.
        self._veg = cfg.no_vegetation or self.height_fn is None
        # CC0 photographic materials (cached; None if offline -> procedural fallback).
        sys.stdout.write("Fetching CC0 textures (first run only)...\n")
        sys.stdout.flush()
        dirt = (cc0.try_material("forest_floor") or cc0.try_material("ground")
                or foliage.procedural_ground_maps())
        self._ground_maps = dirt
        self._rock_maps = cc0.try_material("rock")
        needle = cc0.try_material("dirt") or cc0.try_material("moss") or dirt
        bark_maps = cc0.try_material("bark") or {}
        bark = bark_maps.get("color")
        # Materials the ground splat blends: [dirt, rock, needle/litter].
        self._splat_mats = cast("list[str]", [m.get("color") for m in
                                (dirt, self._rock_maps or dirt, needle)
                                if m.get("color")])

        # Textured, alpha-cut foliage. Grass and flowers don't cast shadows (the big
        # cost); trees and rocks do.
        self._tree_proto = foliage.conifer(height=10.0, bark_path=bark)
        # Distant trees: a cheap 3D dark cone (reads as a conifer from any angle; flat
        # billboards look like green chevrons at mid-distance).
        self._tree_far = Shape(geometry=Cone(bottomRadius=2.4, height=9.0),
                               appearance=Appearance(material=Material(
                                   diffuseColor=(0.07, 0.26, 0.10))))
        self._grass_near = foliage.no_shadow(
            foliage.grass_card(width=1.1, height=1.0, seed=3, planes=2))
        self._grass_far = foliage.no_shadow(
            foliage.grass_card(width=1.3, height=1.0, seed=5, planes=1))
        self._flower_proto = foliage.no_shadow(
            foliage.flower_card(width=0.6, height=0.6, seed=2))
        self._branch_proto = foliage.branch(bark_path=bark, seed=1)
        rm = self._rock_maps
        self._rock_protos = ([foliage.rock(rm, 1), foliage.rock(rm, 4)] if rm else [])
        self._pebble_proto = foliage.rock(rm, 9) if rm else None
        self._tree_pos = np.zeros((0, 2))       # collider positions (x,z)
        self._rock_pos = np.zeros((0, 2))
        self._rock_rad = np.zeros(0)
        # Trees thin out on steep rock, and leave a small clearing at the spawn so you
        # don't start inside a trunk.
        self._tree_keep = lambda p: (
            (p[:, 1] > P.WATER_LEVEL + 2.0) & (p[:, 1] < 135.0)
            & (foliage.slope01(cast("P.HeightFn", self.height_fn), p[:, 0], p[:, 2])
               < 0.42)
            & (np.hypot(p[:, 0] - self._spawn_xz[0],
                        p[:, 2] - self._spawn_xz[1]) > 6.0))
        self._ground_node: Any = None
        self._ground_center: Any = None
        self._detail_node: Any = None
        self._detail_center: Any = None
        self._trees_node: Any = None
        self._grass_node: Any = None
        self._trees_center: Any = None
        self._grass_center: Any = None
        if not self._veg:
            self._refresh_ground((sx, sy, sz))
            self._refresh_trees((sx, sy, sz))
            self._refresh_grass((sx, sy, sz))
            self._refresh_detail((sx, sy, sz))

        caps = CharacterCapabilities(walkSpeed=16.0, runSpeed=34.0, sprintSpeed=90.0,
                                     flySpeed=90.0, eyeHeight=1.7, stepHeight=0.7)
        self.avatar = PhysicsViewPlatform(self.world, caps,
                                          position=(sx, sy + 6, sz), yaw=0.6)
        self.avatar.bind((sx, sy + 6, sz))
        self._flying = bool(cfg.fly) or self.height_fn is None
        self.avatar.set_fly(self._flying)
        self._sprint = False
        self._mult = 1.0

        # The default free-fly navigator also writes context.platform; unbind it so the
        # character controller is the sole camera driver (otherwise built-in nav keys
        # glide the view and our per-frame apply() snaps it back — the "jump-back" bug).
        if self.movementManager is not None:
            self.movementManager.unbind(self)
            self.movementManager = None

        # Movement is registered on BOTH key-down ('keyboard') and character
        # ('keypress') events: some backends (GLFW under a nested Wayland compositor)
        # deliver only char events, so relying on 'keyboard' alone leaves WASD dead
        # while single-shot 'keypress' toggles (g/space) still work. HOLD is wide
        # enough to bridge the OS char-repeat initial delay when only char events come.
        self._keys: dict[str, float] = {}
        for k in "wsadqerf":
            self.addEventHandler("keyboard", name=k, state=1, function=self._on_key)
            self.addEventHandler("keyboard", name=k, state=0, function=self._on_key_up)
            self.addEventHandler("keypress", name=k, function=self._on_key)
        self.addEventHandler("keyboard", name="<shift>", state=1,
                             function=self._shift_on)
        self.addEventHandler("keyboard", name="<shift>", state=0,
                             function=self._shift_off)
        # One-shot toggles on 'keypress' only (registering on both event types would
        # fire them twice and cancel the toggle).
        self.addEventHandler("keypress", name=" ", function=self._on_jump)
        self.addEventHandler("keypress", name="g", function=self._toggle_fly)
        self.addEventHandler("keypress", name="=", function=self._faster)
        self.addEventHandler("keypress", name="-", function=self._slower)
        self.keyRepeatDelay = 0.06
        self._last = time.time()

    # -- input -----------------------------------------------------------
    def _on_key(self, event: Any) -> None:
        self._keys[event.name] = time.time()

    def _on_key_up(self, event: Any) -> None:
        self._keys.pop(event.name, None)

    def _shift_on(self, event: Any) -> None:
        self._sprint = True

    def _shift_off(self, event: Any) -> None:
        self._sprint = False

    def _on_jump(self, event: Any) -> None:
        self.avatar.jump()

    def _toggle_fly(self, event: Any) -> None:
        self._flying = not self._flying
        self.avatar.set_fly(self._flying)

    def _faster(self, event: Any) -> None:
        self._mult = min(self._mult * 1.5, 8.0)

    def _slower(self, event: Any) -> None:
        self._mult = max(self._mult / 1.5, 0.25)

    # -- vegetation (camera-following forest) ---------------------------
    _KEEP = staticmethod(
        lambda p: (p[:, 1] > P.WATER_LEVEL + 2.0) & (p[:, 1] < 135.0))

    def _swap_child(self, old: Any, new: Any) -> None:
        kids = list(self.sg.children)
        if old is not None and old in kids:
            kids[kids.index(old)] = new
        else:
            kids.append(new)
        self.sg.children = kids

    def _refresh_trees(self, center: Sequence[float]) -> None:
        d = self.config.density
        hf = cast("P.HeightFn", self.height_fn)
        c = (float(center[0]), 0.0, float(center[2]))
        # A dense forest: full-mesh conifers close in, cheap billboards beyond.
        trees = scatter_disc(c, 240.0, 0.03 * d, seed=101, height_fn=hf,
                             keep=self._tree_keep, scale_range=(0.7, 1.8),
                             water_level=P.WATER_LEVEL)
        near, far = partition_by_distance(trees, c, 75.0)
        node = Group(children=[group_from_scatter(near, self._tree_proto),
                               group_from_scatter(far, self._tree_far)])
        self._swap_child(self._trees_node, node)
        self._trees_node = node
        self._trees_center = np.array([c[0], c[2]])
        self._tree_pos = trees.positions[:, [0, 2]].astype("d")

    def _refresh_ground(self, center: Sequence[float]) -> None:
        c = (float(center[0]), 0.0, float(center[2]))
        node = foliage.ground_patch_blended(c, 150.0,
                                            cast("P.HeightFn", self.height_fn),
                                            self._splat_mats, res=52, tex_size=1024,
                                            water_level=P.WATER_LEVEL)
        self._swap_child(self._ground_node, node)
        self._ground_node = node
        self._ground_center = np.array([c[0], c[2]])

    def _refresh_grass(self, center: Sequence[float]) -> None:
        d = self.config.density
        hf = cast("P.HeightFn", self.height_fn)
        c = (float(center[0]), 0.0, float(center[2]))
        # Very dense near the camera; sparser, single-plane cards further out.
        near = scatter_disc(c, 18.0, 1.2 * d, seed=303, height_fn=hf,
                            keep=self._KEEP, scale_range=(0.7, 1.6),
                            water_level=P.WATER_LEVEL)
        far = scatter_disc(c, 55.0, 0.12 * d, seed=404, height_fn=hf,
                           keep=self._KEEP, scale_range=(0.8, 1.7),
                           water_level=P.WATER_LEVEL)
        node = Group(children=[group_from_scatter(near, self._grass_near),
                               group_from_scatter(far, self._grass_far)])
        self._swap_child(self._grass_node, node)
        self._grass_node = node
        self._grass_center = np.array([c[0], c[2]])

    def _refresh_detail(self, center: Sequence[float]) -> None:
        """Rocks, pebbles, wildflowers and fallen branches near the camera."""
        d = self.config.density
        c = (float(center[0]), 0.0, float(center[2]))
        hf = cast("P.HeightFn", self.height_fn)

        def rocky(p: np.ndarray) -> np.ndarray:
            return self._KEEP(p) & (foliage.slope01(hf, p[:, 0], p[:, 2]) > 0.12)

        kids: list[Any] = []
        if self._rock_protos:
            rocks = scatter_disc(c, 90.0, 0.004 * d, seed=501, height_fn=hf,
                                 keep=self._KEEP, scale_range=(0.6, 2.4),
                                 water_level=P.WATER_LEVEL)
            for i, proto in enumerate(self._rock_protos):
                part = _slice_scatter(rocks, i, len(self._rock_protos))
                kids.append(group_from_scatter(part, proto))
            self._rock_pos = rocks.positions[:, [0, 2]].astype("d")
            self._rock_rad = (0.75 * rocks.scales).astype("d")
            pebbles = scatter_disc(c, 45.0, 0.03 * d, seed=502, height_fn=hf,
                                   keep=rocky, scale_range=(0.15, 0.5),
                                   water_level=P.WATER_LEVEL)
            kids.append(group_from_scatter(pebbles, self._pebble_proto))
        flowers = scatter_disc(c, 24.0, 0.10 * d, seed=503, height_fn=hf,
                               keep=self._KEEP, scale_range=(0.8, 1.6),
                               water_level=P.WATER_LEVEL)
        kids.append(group_from_scatter(flowers, self._flower_proto))
        branches = scatter_disc(c, 30.0, 0.015 * d, seed=504, height_fn=hf,
                                keep=self._KEEP, scale_range=(0.6, 1.5),
                                water_level=P.WATER_LEVEL)
        kids.append(group_from_scatter(branches, self._branch_proto))
        node = Group(children=kids)
        self._swap_child(self._detail_node, node)
        self._detail_node = node
        self._detail_center = np.array([c[0], c[2]])

    def _maybe_refresh_vegetation(self, eye: Sequence[float]) -> None:
        if self._veg:
            return
        here = np.array([eye[0], eye[2]])
        if np.linalg.norm(here - self._grass_center) > 16.0:
            self._refresh_grass(eye)
        if np.linalg.norm(here - self._detail_center) > 22.0:
            self._refresh_detail(eye)
        if np.linalg.norm(here - self._trees_center) > 160.0:
            self._refresh_trees(eye)
        if np.linalg.norm(here - self._ground_center) > 70.0:
            self._refresh_ground(eye)

    def _view_projection(self, eye: Sequence[float]) -> np.ndarray:
        yaw = self.avatar.yaw if getattr(self, "avatar", None) else 0.6
        pitch = self.avatar.pitch if getattr(self, "avatar", None) else -0.1
        fwd = (math.sin(yaw) * math.cos(pitch), math.sin(pitch),
               -math.cos(yaw) * math.cos(pitch))
        centre = (eye[0] + fwd[0] * 60, eye[1] + fwd[1] * 60, eye[2] + fwd[2] * 60)
        return view_projection(eye, centre, (0, 1, 0), math.radians(60), 1.4,
                               1.0, 7000.0)

    def _ground_clamp(self) -> None:
        """Keep the avatar on the exact terrain surface (walk mode).

        Snaps the capsule base to `height_fn(x, z)` whenever it is at or below the
        surface, and zeroes downward velocity — so gravity, jumps and slopes still feel
        natural but the avatar can never sink into or fall through the ground, whatever
        the frame rate. In fly mode it only stops you dropping below the terrain."""
        if self.height_fn is None:
            return
        ch = self.avatar.character
        x, z = float(ch.position[0]), float(ch.position[2])
        surf = max(float(self.height_fn(np.array([x]), np.array([z]))[0]),
                   P.WATER_LEVEL)
        half = ch.height * 0.5
        base = ch.position[1] - half
        tol = 0.05 if not self._flying else 0.0
        if base <= surf + tol:
            ch.position[1] = surf + half
            if ch.vy < 0.0:
                ch.vy = 0.0
            if not self._flying:
                ch.grounded = True

    def _object_collision(self) -> None:
        """Push the avatar out of tree trunks and rocks (analytic capsule vs cylinder/
        sphere). Vectorised over the current collider set, so it's cheap."""
        ch = self.avatar.character
        px, pz = float(ch.position[0]), float(ch.position[2])
        cr = ch.caps.radius
        for pos, rad in ((self._tree_pos, 0.45), (self._rock_pos, self._rock_rad)):
            if len(pos) == 0:
                continue
            dx = px - pos[:, 0]
            dz = pz - pos[:, 1]
            d = np.hypot(dx, dz)
            r = cast(np.ndarray, rad if np.ndim(rad) else np.full(len(pos), rad)) + cr
            hit = (d < r) & (d > 1e-4)
            if hit.any():
                k = np.argmin(d - r)          # resolve the deepest overlap
                if hit[k]:
                    push = float(r[k] - d[k]) if np.ndim(r) else float(r - d[k])
                    ch.position[0] = px + dx[k] / d[k] * push
                    ch.position[2] = pz + dz[k] / d[k] * push

    def _stream(self, eye: Sequence[float]) -> None:
        if self.terrain is not None:
            self.terrain.update_for_camera(eye, self.getViewPort()[1] or 700,
                                           view_projection=self._view_projection(eye))

    def OnIdle(self, *args: Any) -> int:
        if getattr(self, "avatar", None) is None:
            return 0
        # The per-frame walk/fly movement loop below needs a live navigator +
        # window; it is driven by the terrain render/subprocess tests.
        return self._on_idle_move(*args)  # pragma: no cover - interactive movement loop

    def _on_idle_move(self, *args: Any) -> int:  # pragma: no cover - interactive loop
        now = time.time()
        dt = min(now - self._last, 0.05)
        self._last = now
        nav = self.avatar

        def held(k: str) -> bool:
            return now - self._keys.get(k, 0) < HOLD
        fwd = (1.0 if held("w") else 0.0) - (1.0 if held("s") else 0.0)
        strafe = (1.0 if held("d") else 0.0) - (1.0 if held("a") else 0.0)
        if os.environ.get("OGLC_AUTOWALK"):        # headless movement self-test
            fwd = 1.0
        if held("q"):
            nav.turn(-1.8 * dt)
        if held("e"):
            nav.turn(1.8 * dt)
        if self._flying:
            up = (1.0 if held("r") else 0.0) - (1.0 if held("f") else 0.0)
            nav.set_fly_move(fwd * self._mult, strafe * self._mult, up * self._mult)
        else:
            mode = "sprint" if self._sprint else "walk"
            nav.set_move(fwd, strafe, mode=mode)
        nav.update(dt)
        self._ground_clamp()
        if not self._flying:
            self._object_collision()
        nav.apply(self)
        eye = nav.camera_position()
        self._stream(eye)
        self._maybe_refresh_vegetation(eye)
        self.triggerRedraw(1)
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oglc-terrain", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", nargs="?", default=None,
                   help="an existing tileset.json to view (omit for a procedural world)")
    p.add_argument("--dem", metavar="IMAGE", default=None,
                   help="bake from a grayscale heightmap image instead of noise")
    p.add_argument("--extent", type=float, default=2048.0,
                   help="world size in metres (default 2048)")
    p.add_argument("--levels", type=int, default=3,
                   help="quadtree LOD depth; tiles = sum(4**l) (default 3 -> 21 tiles)")
    p.add_argument("--tile-res", type=int, default=33, dest="tile_res",
                   help="vertices per tile edge (default 33)")
    p.add_argument("--height-scale", type=float, default=400.0, dest="height_scale",
                   help="DEM: world height for full-white (default 400)")
    p.add_argument("--base", type=float, default=-40.0,
                   help="DEM: height offset; below 0 makes low areas water (default -40)")
    p.add_argument("--sse", type=float, default=16.0,
                   help="screen-space error target in pixels; lower = more detail")
    p.add_argument("--memory", type=int, default=256,
                   help="resident tile memory budget in MiB (default 256)")
    p.add_argument("--density", type=float, default=1.0,
                   help="vegetation density multiplier (lower = faster, default 1.0)")
    p.add_argument("--no-vegetation", action="store_true", dest="no_vegetation",
                   help="skip trees")
    p.add_argument("--fly", action="store_true",
                   help="start in free-fly instead of walk mode")
    p.add_argument("--size", default=None, help="window size, e.g. 1280x720")
    return p


def main(argv: list[str] | None = None) -> Any:
    args = build_parser().parse_args(argv)
    if args.source and args.dem:
        build_parser().error("give either a tileset.json or --dem, not both")
    TerrainContext.config = args
    if args.size:
        w, h = (int(v) for v in args.size.lower().split("x"))
        return TerrainContext.ContextMainLoop(size=(w, h))
    return TerrainContext.ContextMainLoop()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
