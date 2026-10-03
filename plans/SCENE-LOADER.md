# Scene loader

Status: landed 2026-10-03, on `main`. preflight not yet run: see Open.

## What it is

`OpenGLContext.loaders.sceneloader.SceneLoader` is the loader package's front
door and is held by every `Context` as `self.sceneLoader`. It reads a path, a
URL or bytes on a worker thread and delivers the format's native result
(`GLTFScene`, `SceneGraph`) to a callback or a `pydispatch` signal on the
thread that polls it. Which format reads a source is chosen by
`loaders/formats.py` from the adapters registered under `plugins.Adapter`, so a
format registered by a third party loads through the same call.

## Decisions

- A held object, not a base class. The first attempt split
  `SceneViewerMixin` into a `SceneLoaderMixin` base; that left loading
  inheritable only by a viewer. The viewer is now a client of the loader, and
  `SceneViewerMixin` keeps what is a viewer's concern: one scene at a time, the
  newest request cancelling the one before.
- Requests are independent. `AsyncSceneMixin` had one load token per context,
  so a second request superseded the first. A loader has any number in flight;
  a caller that wants only the newest request calls `request.cancel()` on the one before.
- Native results. `SceneAdapter` gained `read()` (the format's own result) and
  `present()` (that result as a `ViewerScene`); `load()` is the two in turn.
  `GLTFAdapter` presents a `GLTFScene` as it is; `SceneGraphAdapter` measures a
  `SceneGraph`. `TilesAdapter.read()` returns its `ViewerScene` because the
  streaming runtime is part of what it loads.
- In-memory content. `SceneAdapter.accepts_content` and `read_content()`;
  implemented for glTF and the scenegraph formats.
- Deliveries cross threads on a `RenderQueue` (`events/renderqueue.py`), made by
  `ContextCore.setupRenderQueue` beside the loader. The main loops run it once
  an iteration before `OnIdle` (`windowsystem/base.py`, `wx.py`; its own
  `handoff` loop-trace phase), not from `OnIdle` or `OnDraw`: subclasses that
  override `OnIdle` do not call up, and `OnDraw` is the wrong end of the frame.
  Any background work queues a call the same way. A call may return `DEFER` to be
  made on the next run, which is how a replay holds a delivery to its frame.
- Readers and adapters are separate. `loaders/readers.SceneReader` is what a
  format gives the loader (`read`, `read_content`, `configure`, `shutdown`);
  `SceneAdapter(SceneReader)` adds what a viewer asks (`present`, `update`,
  `recentres`). Both register under `plugins.Adapter`; the viewer's lookups
  refuse a reader that is not an adapter. twig-bb registers `LevelReader` for
  `.bsp` and `.pk3`; 3D Tiles reading is `loaders/tiles3d/reader.TilesReader`
  (native result: the primed `TilesTerrain`) and `TilesAdapter` adds the
  viewer's half.
- Format dispatch moved from `viewer/adapters/__init__.py` to
  `loaders/formats.py`, so the loader package does not import the viewer;
  `viewer.adapters` re-exports it.
- Session replay is kept: each delivery is marked `scene-mounted`, and a
  replay holds or waits for it by frame.
- The viewer reads sources through `sceneLoader.load(source, reader=self.adapter,
  options=self.options)` and presents the result on arrival (`requestSource`);
  `requestScene` serves scenes that are not sources; `loadScene()` is the
  synchronous read a capture needs, through `load_now`.

## Scripts and demos

Every runnable script and demo in `tests/` and `OpenGLContext/bin/` that read a
model now reads it through `self.sceneLoader` (`bake_demo`, `multiview_quad`,
`using_vrml97`, `using_obj`, `using_clips`, `using_npc`, `navmesh_demo`,
`node_modify`, `timesensorobject`, `cubeback_rot`, `lod_demo` and `lod_hall`,
`crowd_demo`, `tiles_vegetation`, `profile_view`, `character_sheet`,
`gltf_demo`; `view --list-cameras` reads with `adapter.load`, which is `read` then `present`, since it runs with no context). A bounded run holds its frame count and its
clock while loads are pending (`Context.loadsPending`), so the capture harness
still photographs the loaded scene. `multiview_quad` frames its views after the
window has its size, where it framed them at a viewport of (0, 0) before; its
reference image was replaced.

## Removed

`viewer/asyncscene.py` (`AsyncSceneMixin`) and its test. twig-bb's
`TwigContext` now submits its level through `sceneLoader.submit()`. An adapter
that overrode `load()` alone must override `read()` (and `present()` if its
result is not already a `ViewerScene`).

## Open

- `tools/preflight.py openglcontext` and twig-bb's suite.
- `openglcontext-qt` and the other games have not been checked for contexts that
  bypass `Context.__init__`.
- Imports a format's `read()` makes for the first time run on the worker thread;
  `loaders/background.py` explains why that is a hazard. A `prepare` step on the
  adapter would move them to the calling thread.
