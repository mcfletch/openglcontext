"""TilesetRuntime: the per-frame streaming tick.

Ties traversal, residency, background loading, and GL upload into one `update(camera,
viewport_height)` call that returns the drawables to render this frame. The steps are:

1. traverse -> render set (ideal) and want set (render + prefetch margin);
2. mark the want set recently-wanted and enqueue any not-yet-loaded tiles by priority;
3. drain finished loads and, throttled to a per-frame cap, upload them to GL;
4. evict least-recently-wanted resident tiles past the memory budget, releasing GL
   resources, while pinning tiles currently used as a coarse fallback;
5. build the draw list, substituting the nearest resident ancestor for any wanted
   tile whose finer content has not arrived yet, so the world sharpens in rather than
   holing.

GL work is delegated to an `uploader` (`upload(tile, payload) -> (drawable, nbytes)`
and `release(drawable)`), so the orchestration is testable without a GL context.
"""
from OpenGLContext.loaders.tiles3d.traversal import select_tiles
from OpenGLContext.loaders.tiles3d.residency import Residency
from OpenGLContext.loaders.tiles3d.loadmanager import LoadManager
from OpenGLContext.loaders.tiles3d.frustum import Frustum


class TilesetRuntime:
    def __init__(self, tileset, loader_fn, uploader, memory_budget,
                 fovy, max_sse=16.0, prefetch_factor=2.0,
                 max_uploads_per_update=4, workers=2, hysteresis=0.0,
                 on_renderable=None, on_evicted=None):
        self.tileset = tileset
        self.uploader = uploader
        self.hysteresis = hysteresis
        self._refined_state = {}
        # Fired when a tile's content becomes drawable / is evicted, so consumers
        # (e.g. physics colliders) can track the resident set. Both take (tile, drawable).
        self.on_renderable = on_renderable
        self.on_evicted = on_evicted
        self.residency = Residency(memory_budget)
        self.loadmgr = LoadManager(loader_fn, workers=workers)
        self.fovy = fovy
        self.max_sse = max_sse
        self.prefetch_factor = prefetch_factor
        self.max_uploads_per_update = max_uploads_per_update
        self._drawables = {}   # id(tile) -> drawable
        self._ready_payloads = {}  # id(tile) -> (tile, payload) awaiting upload

    def update(self, camera, viewport_height, max_sse=None, visible=None,
               view_projection=None):
        max_sse = self.max_sse if max_sse is None else max_sse
        if visible is None and view_projection is not None:
            frustum = Frustum.from_matrix(view_projection)

            def visible(tile):
                center, radius = tile.bounding_volume.bounding_sphere()
                return frustum.contains_sphere(center, radius)
        selection = select_tiles(
            self.tileset, camera, viewport_height, self.fovy, max_sse,
            prefetch_factor=self.prefetch_factor, visible=visible,
            hysteresis=self.hysteresis, refined_state=self._refined_state,
        )
        self.residency.note_wanted(selection.want)
        self._request_loads(selection.want, camera)
        self._collect_ready()
        self._upload_ready()
        draw, pinned = self._build_draw_list(selection.render)
        self._evict(selection.want, pinned)
        return draw

    def wait_for_loads(self, timeout=5.0):
        return self.loadmgr.wait_idle(timeout=timeout)

    def shutdown(self):
        self.loadmgr.shutdown()

    def _request_loads(self, want, camera):
        for tile in self.residency.wanted_to_load(want):
            self.residency.begin_load(tile)
            priority = tile.bounding_volume.distance_to(camera)
            self.loadmgr.request(tile, priority)

    def _collect_ready(self):
        for tile, payload in self.loadmgr.poll_ready():
            if isinstance(payload, Exception):
                # Failed load: drop back to unloaded so it can be retried later.
                self.residency.evict(tile)
                continue
            self.residency.set_ready(tile)
            self._ready_payloads[id(tile)] = (tile, payload)

    def _upload_ready(self):
        uploaded = 0
        for key in list(self._ready_payloads):
            if uploaded >= self.max_uploads_per_update:
                break
            tile, payload = self._ready_payloads.pop(key)
            drawable, nbytes = self.uploader.upload(tile, payload)
            self.residency.set_renderable(tile, nbytes)
            self._drawables[id(tile)] = drawable
            uploaded += 1
            if self.on_renderable is not None:
                self.on_renderable(tile, drawable)

    def _renderable_or_ancestor(self, tile):
        if id(tile) in self._drawables:
            return tile
        for ancestor in tile.ancestors():
            if id(ancestor) in self._drawables:
                return ancestor
        return None

    def _build_draw_list(self, render):
        draw = []
        pinned = []
        seen = set()
        for tile in render:
            resolved = self._renderable_or_ancestor(tile)
            if resolved is None or id(resolved) in seen:
                continue
            seen.add(id(resolved))
            draw.append(self._drawables[id(resolved)])
            if resolved is not tile:
                pinned.append(resolved)
        return draw, pinned

    def _evict(self, want, pinned):
        for tile in self.residency.enforce_budget(keep=list(want) + pinned):
            drawable = self._drawables.pop(id(tile), None)
            if drawable is not None:
                self.uploader.release(drawable)
                if self.on_evicted is not None:
                    self.on_evicted(tile, drawable)
