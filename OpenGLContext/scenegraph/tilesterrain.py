"""TilesTerrain: a scenegraph node that streams an OGC 3D Tiles terrain.

Mounts as a `Group` whose children are the tile subtrees currently selected for the
camera. Each frame the owning context calls `update_for_camera(camera,
viewport_height)`: the node runs one streaming tick (traverse -> load -> upload ->
evict, with coarse-parent fallback) and replaces its `children` with the resulting
drawables, which the render pass then re-integrates and draws.

Loading and glTF parsing happen on background worker threads; only the (cheap) mount
and the draw run on the GL thread.
"""
import json
import math
import os

from OpenGLContext.scenegraph.group import Group
from OpenGLContext.loaders.tiles3d import fetch
from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset
from OpenGLContext.loaders.tiles3d.runtime import TilesetRuntime
from OpenGLContext.loaders.tiles3d.gltf_uploader import (
    make_tile_loader,
    GLTileUploader,
)


class TilesTerrain(Group):
    """A streamed 3D Tiles terrain mounted as a scenegraph group.

    `tileset_path` is a local path or an http(s) URL; content and any external
    (nested) tilesets resolve against it, and remote payloads are cached under
    `cache_dir` (default: the per-user cache dir).
    """

    def __init__(self, tileset_path, memory_budget=256 * 1024 * 1024,
                 max_sse=16.0, fovy=math.radians(45.0), prefetch_factor=2.0,
                 max_uploads_per_update=4, workers=2, physics_world=None,
                 recenter=True, cache_dir=None, **named):
        super().__init__(**named)
        self.fovy = fovy
        doc = json.loads(fetch.read_bytes(tileset_path, cache_dir=cache_dir))
        if fetch.is_url(tileset_path):
            base_uri = fetch.dir_of(tileset_path)
        else:
            base_uri = os.path.dirname(os.path.abspath(tileset_path)) + os.sep
        resolver = lambda uri: json.loads(fetch.read_bytes(uri, cache_dir=cache_dir))
        tileset = build_runtime_tileset(doc, base_uri=base_uri, recenter=recenter,
                                        resolve_external=resolver)
        self.tileset = tileset
        on_renderable = on_evicted = None
        self.colliders = None
        if physics_world is not None:
            from OpenGLContext.loaders.tiles3d.physics_colliders import TerrainColliders
            self.colliders = TerrainColliders(physics_world)
            on_renderable = self.colliders.on_renderable
            on_evicted = self.colliders.on_evicted
        self.runtime = TilesetRuntime(
            tileset, make_tile_loader(cache_dir=cache_dir), GLTileUploader(),
            memory_budget=memory_budget, fovy=fovy, max_sse=max_sse,
            prefetch_factor=prefetch_factor,
            max_uploads_per_update=max_uploads_per_update, workers=workers,
            on_renderable=on_renderable, on_evicted=on_evicted,
        )

    def update_for_camera(self, camera, viewport_height, max_sse=None,
                          view_projection=None):
        """Run one streaming tick and update the visible tile children.

        `view_projection` (a 4x4 view-projection matrix) enables frustum culling so
        only tiles in view are refined and streamed; omit it to consider all tiles by
        distance.
        """
        drawables = self.runtime.update(camera, viewport_height, max_sse=max_sse,
                                        view_projection=view_projection)
        # Preserve node identity for the pass's add/remove observers: only rewrite
        # `children` when the visible set actually changes.
        if list(self.children) != drawables:
            self.children = drawables
        return drawables

    def wait_for_loads(self, timeout=5.0):
        return self.runtime.wait_for_loads(timeout=timeout)

    def shutdown(self):
        self.runtime.shutdown()
