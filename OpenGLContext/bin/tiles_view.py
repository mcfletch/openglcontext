#!/usr/bin/env python
"""oglc-tiles: stream and view an OGC 3D Tiles tileset.

Loads a ``tileset.json`` and streams its tiles by screen-space error as you fly,
rendering them with the PBR uber-shader. This is the interactive front end for the
`loaders.tiles3d` runtime; it handles the parts real datasets use:

  * glTF/GLB and b3dm tile content
  * box, sphere and geodetic ``region`` bounding volumes
  * external (nested) tilesets — a tile whose content is another ``.json``
  * Earth-Centered (ECEF) tilesets, recentred to the origin for float precision

Usage::

    oglc-tiles path/to/tileset.json
    oglc-tiles tileset.json --sse 8 --memory 512
    oglc-tiles tileset.json --capture shot.png     # offscreen still

Controls: free-fly with the mouse and arrow/WASD keys (hold to move). The camera is
auto-framed on the whole tileset at startup.
"""
import argparse
import math
import os
import sys

import numpy as np

# Real tilesets carry vertex colours and PBR materials the base pass ignores, and
# they want core-profile shaders; set these before the GL context is built.
os.environ.setdefault("OPENGLCONTEXT_PROFILE", "core")
os.environ.setdefault("OPENGLCONTEXT_RENDERER", "pbr")
os.environ.setdefault("OPENGLCONTEXT_BACKEND", "glfw")

from OpenGLContext import testingcontext
from OpenGLContext.scenegraph.basenodes import (
    sceneGraph, DirectionalLight, Background,
)
from OpenGLContext.scenegraph.tilesterrain import TilesTerrain
from OpenGLContext.loaders.tiles3d import fetch
from OpenGLContext.loaders.tiles3d.gltf_uploader import make_tile_loader
from OpenGLContext.loaders.tiles3d.frustum import view_projection

BaseContext = testingcontext.getInteractive()


def _leaf_tile(tile):
    """Descend to the first tile that actually carries drawable content.

    An external-tileset or grouping tile has no content of its own; its geometry
    lives below. We frame on the first content tile so the camera aims at real mesh.
    """
    while tile.content_uri is None and tile.children:
        tile = tile.children[0]
    return tile


def _forward(quaternion):
    """World-space look direction for a view platform's orientation quaternion."""
    r = np.asarray(quaternion.matrix())[:3, :3]
    return r.T @ np.array([0.0, 0.0, -1.0])


class TilesViewContext(BaseContext):
    config = None

    def OnInit(self):
        try:
            import glfw
            glfw.swap_interval(0)          # never block on vsync (offscreen hangs)
        except Exception:
            pass
        cfg = self.config
        self.gltf_scene_ambient = 0.35
        self._tile_loader = make_tile_loader(cache_dir=cfg.cache_dir)
        self.terrain = TilesTerrain(
            cfg.source, fovy=math.radians(cfg.fov), max_sse=cfg.sse, workers=4,
            memory_budget=cfg.memory * 1024 * 1024, recenter=not cfg.no_recenter,
            cache_dir=cfg.cache_dir)

        self._center, self._radius = self._framing()
        self.sg = sceneGraph(children=[
            # A gradient sky needs >=2 skyColors + a skyAngle; a lone skyColor renders
            # an empty color set (the whole frame clears to black).
            Background(
                skyColor=[[0.29, 0.44, 0.70], [0.52, 0.62, 0.80],
                          [0.80, 0.86, 0.93]],
                skyAngle=[1.20, 1.5708],
                groundColor=[[0.43, 0.40, 0.36], [0.55, 0.52, 0.47]],
                groundAngle=[1.5708]),
            DirectionalLight(direction=(-0.4, -0.82, -0.45), intensity=1.35,
                             color=(1.0, 0.96, 0.88)),
            self.terrain,
        ])

        # Frame the camera *before* priming: the residency loads the LOD the framed
        # view actually needs. Priming from the default camera pose (often inside the
        # tileset) would refine to the finest tiles, then evict them when the camera
        # jumps out to the framed pose, leaving the first frames empty.
        self._frame_camera()
        for _ in range(12):
            self._stream(self._eye())
            self.terrain.wait_for_loads(timeout=6.0)

        sys.stdout.write(
            "oglc-tiles: %d tile(s) resident; fly with mouse + WASD/arrows\n"
            % len(self.terrain.children))
        sys.stdout.flush()

    def _framing(self):
        """(centre, radius) of the whole tileset, aimed at real geometry.

        The root bounding volume gives extent; the first content tile's glTF centre
        (transformed to world space) gives an aim point that lands on the mesh even
        when the bounding-volume centre does not coincide with it.
        """
        root = self.terrain.tileset.root
        center, radius = root.bounding_volume.bounding_sphere()
        center = np.asarray(center, dtype="d")
        try:
            leaf = _leaf_tile(root)
            scene, _ = self._tile_loader(leaf)
            m = leaf.world_transform
            aim = (m @ np.append(np.asarray(scene.center, "d"), 1.0))[:3]
            # Only trust the mesh aim if it sits inside the tileset's extent.
            if np.linalg.norm(aim - center) <= radius:
                center = aim
        except Exception:
            pass
        return center, float(radius or 1.0)

    def _eye(self):
        if getattr(self, "platform", None) is not None:
            return tuple(float(v) for v in self.platform.position[:3])
        return tuple(float(v) for v in self._eye0[:3])

    def _frame_camera(self):
        """Place the camera to fit the whole tileset, looking slightly down.

        Explicit frustum: a real tileset spans metres to kilometres, so the default
        near/far would clip it. On-axis placement with a small tilt matches the
        gltf-view framing that reads well for an isolated model.
        """
        r = self._radius
        fov = math.radians(self.config.fov)
        distance = r / max(1e-3, math.sin(fov / 2.0)) * self.config.margin
        self._eye0 = self._center + np.array([0.0, r * 0.22, distance])
        if getattr(self, "platform", None) is not None:
            self.platform.setFrustum(fov, None, max(1e-4, r * 0.02), r * 60.0)
            self.platform.setPosition(tuple(float(v) for v in self._eye0))
            self.platform.setOrientation((1, 0, 0, 0.10))

    def _view_projection(self, eye):
        if getattr(self, "platform", None) is not None:
            fwd = _forward(self.platform.quaternion)
        else:
            fwd = (self._center - np.asarray(eye)) or np.array([0, 0, -1.0])
        center = np.asarray(eye) + np.asarray(fwd) * (self._radius or 1.0)
        aspect = (self.getViewPort()[0] / max(1, self.getViewPort()[1])) or 1.0
        r = self._radius
        return view_projection(eye, tuple(center), (0, 1, 0),
                               math.radians(self.config.fov), aspect,
                               max(1e-4, r * 0.02), r * 60.0)

    def _stream(self, eye):
        self.terrain.update_for_camera(
            eye, self.getViewPort()[1] or 700,
            view_projection=self._view_projection(eye))

    def OnIdle(self, *args):
        if getattr(self, "terrain", None) is not None:
            self._stream(self._eye())
            self.triggerRedraw(1)
        return super().OnIdle(*args) if hasattr(super(), "OnIdle") else None

    def OnDraw(self, *args, **named):
        if getattr(self, "terrain", None) is not None:
            self._stream(self._eye())
        return super().OnDraw(*args, **named)

    def OnShutdown(self, *args, **named):
        if getattr(self, "terrain", None) is not None:
            self.terrain.shutdown()
        return super().OnShutdown(*args, **named) if hasattr(
            super(), "OnShutdown") else None


def build_parser():
    p = argparse.ArgumentParser(
        prog="oglc-tiles", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source",
                   help="a tileset.json to stream and view: a local path or an "
                        "http(s):// URL")
    p.add_argument("--sse", type=float, default=16.0,
                   help="max screen-space error in pixels; lower = more detail "
                        "(default 16)")
    p.add_argument("--memory", type=int, default=512,
                   help="tile memory budget in MiB (default 512)")
    p.add_argument("--fov", type=float, default=55.0,
                   help="vertical field of view in degrees (default 55)")
    p.add_argument("--margin", type=float, default=1.15,
                   help="auto-frame fit factor; below 1 pulls the camera in "
                        "(default 1.15)")
    p.add_argument("--no-recenter", action="store_true", dest="no_recenter",
                   help="do not shift a geospatial (ECEF) tileset to the origin")
    p.add_argument("--cache-dir", dest="cache_dir", default=None, metavar="DIR",
                   help="where to cache tiles fetched from a URL "
                        "(default: ~/.cache/openglcontext/tiles3d)")
    p.add_argument("--capture", metavar="PNG", default=None,
                   help="render offscreen and save a still to PNG, then exit")
    p.add_argument("--frames", type=int, default=16,
                   help="frames to render before --capture (default 16)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not fetch.is_url(args.source) and not os.path.exists(args.source):
        build_parser().error("tileset not found: %s" % args.source)
    if args.capture:
        os.environ["OPENGLCONTEXT_AUTO_EXIT_FRAMES"] = str(args.frames)
        os.environ["OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR"] = (
            os.path.dirname(os.path.abspath(args.capture)) or ".")
        os.environ["OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME"] = (
            os.path.splitext(os.path.basename(args.capture))[0])
        os.environ["OPENGLCONTEXT_DISABLE_FPS_DISPLAY"] = "1"
    TilesViewContext.config = args
    TilesViewContext.ContextMainLoop()


if __name__ == "__main__":
    main()
