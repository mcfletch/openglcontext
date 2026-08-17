# One viewer: `oglc-view`

**Status:** ✅ Stages 1–6 landed (2026-08-02). Follow-on work at the end.

Executes [CODEBASE-CONSOLIDATION.md](CODEBASE-CONSOLIDATION.md) §B6, taking over
where [VIEWER-COMPONENT-EXTRACTION.md](VIEWER-COMPONENT-EXTRACTION.md) stopped.
That plan gave the glTF viewer's *component* a home; this one makes it **the**
viewer: every format, a real front end, and no per-format copy of anything.

## What it had to be

A person who types `oglc-view` with no arguments gets a **program**, not a usage
message: a launch menu, a browsable library of sample models and worlds with
pictures, a settings page, and a viewer that opens any of them. A person who
types `oglc-view something` gets that thing, whatever format it is in.

## What landed

### 1. Adapters and the shell

`OpenGLContext/viewer/adapters/` — `SceneAdapter`, `ViewerScene`,
`scene_bounds()`, and a registry keyed on suffix and content type through a new
`plugins.Adapter`, alongside the existing loader/context/node registries. A
tileset under any name is recognised by its content (`asset` + `root`).

`viewer/gltfviewer.py` became `viewer/sceneviewer.py`;
`GLTFViewerMixin`/`GLTFViewerContext` became `SceneViewerMixin`/`ViewerContext`.
`bin/gltf_view.py` became `bin/view.py` (`oglc-view`); `oglc-gltf`,
`oglc-vrml` and `oglc-tiles` are deprecating aliases for one release cycle.

Two viewer facts became adapter facts rather than glTF assumptions:

* **`recentres`** — a *model* may be moved to the origin to be framed; a
  *world* may not, because its ground plane is at y=0 and its viewpoints are in
  its own space.
* **the backdrop** — a scene that brought its own `Background` does not get a
  second one, which would be a fight over which is bound rather than a sky.
  Detected from the scene (`env.count_backgrounds`), so it is true of any
  format rather than declared per adapter.

`scripts/generate_doc_images.py` lost its 90-line hand-rolled capture context
and now runs `oglc-view --capture`, so the doc images are what a reader sees.

### 2. The remaining formats

* **OBJ** — `SceneGraphAdapter` is the shared base for every format the
  scenegraph loaders read; VRML97 and OBJ differ only in `name` and
  `recentres`.
* **3D Tiles** — `TilesAdapter` keeps a runtime alive for the scene it loaded,
  streams in `update(viewer)` once a frame and stops its workers in
  `shutdown()`. That is why an adapter is instantiated per scene.
  `bin/tiles_view.py` (244 lines) became an alias: everything it did beyond
  streaming — framing on the mesh rather than a bounding-volume centre, the
  priming rounds, the per-frame view projection — moved into the adapter, and
  its `--sse`/`--memory`/`--no-recenter`/`--cache-dir` are `ViewerOptions`
  fields that `SceneAdapter.configure()` hands to whichever adapter was chosen.

### 3. The screen, on the UI library

`viewer/overlay.py::TextOverlayMixin` is gone. The caption is
`viewer/caption.py::CaptionLayer`, a HUD layer built on a new
`ui.hudwidgets.TextBlock`, so it takes the skin, the interface scale and the one
batched draw call with everything else. `bin/gltf_demo.py`'s second copy of the
same drawing went too, along with its ~120 lines of raw-GL textured-quad blit:
the reference thumbnail is a `ui.gallery.Picture` in the same layer.

The caption sits **bottom-right**: the developer overlay is anchored top-left
and grows *down* the left edge as sections register, so anything along that side
is written over it.

`viewer/debug.py` adds a **Scene** section to the developer overlay `Alt+F`
already raises — source, adapter, radius, camera, animation, how you are moving.
`m` cycles the declared movement modes, as it does in twig-bb.

### 4. The library, the menu and the settings page

* `viewer/library.py` — `Entry`, `Library`, `default_library()`. **Derived**
  from `loaders.gltf_demos`'s roster (191 entries in a checkout) rather than
  authored again, so the library and the capture harness cannot drift on how a
  model has to be shown. Categories are facts already in the data: authored
  cameras or an interior ⇒ *Scenes*; materials needing a lit backdrop ⇒
  *Materials*; a local build ⇒ *Local builds*.
* `viewer/menu.py` — `main_menu()` and `browse_screen()`, plain `Panel` trees.
* `viewer/screens.py` — which key raises which, and what happens when one is
  answered. `F1` library, `F10` settings, `F6` controls: the keys twig-bb uses.
  Settings and bindings are `ui.settings` and `ui.bindings` unchanged.
* `ViewerContext.openSource()` / `openEntry()` swap the scene in a running
  window — new adapter, new scenegraph, new framing — with the load in the
  background and a superseded load dropped.

### 5. Many entries

`ui/pictures.py::PictureCache`, which `OverlayRenderer.imageTexture` now goes
through: fetches an http(s) URL through the hardened resolver, decodes on a
worker thread, uploads a couple per frame on the render thread, and evicts the
least recently used once a texel budget is reached. A skin asset still loads
blocking (its first frame needs it); a gallery does not.

The `Carousel` already showed a fixed window of a wrapping list, so it needed
page-at-a-time buttons rather than virtualisation.

### 6. Verification

Live, captured frames rather than exit codes: glTF, VRML97 and OBJ opened and
captured; the launch menu, the library with real preview images downloading, and
a scene swapped from one adapter to another in a running window; GLFW, Pygame
and Qt each rendering the same world in core profile (GLFW and Pygame
pixel-identical); the compatibility profile rendering with its screen furniture.

## Defects found on the way

Each got a red test before its fix.  The first four predate this work; the rest
are things this work broke or left half-done, caught by running it.

1. **`Context.DoInit` let a forced redraw recurse into `OnDraw`.** Anything that
   asks for a frame during `OnInit` — `ScreenMixin.addHUDLayer` does, and adding
   a HUD in `OnInit` is what the documentation tells an application to do — drew
   against a half-built context and then blocked in the buffer swap. Redraws are
   deferred for the duration of `OnInit` now; the request itself is kept.
2. **The OBJ loader could not read a file.** `parse` split its lines as `bytes`
   and compared them against `str`, so it raised `TypeError` on the first line of
   every file it was ever given.
3. **`oglc-gltf --capture` hung under a compositor.** A mapped surface throttles
   the swap to the compositor's frame callback, and with no window consuming
   frames the swap never returns. Every other caller in the tree set
   `OPENGLCONTEXT_HIDDEN` and `OPENGLCONTEXT_NO_VSYNC` by hand first; the viewer
   now sets them for whoever runs it.
4. **The compatibility render pass drew no screen at all.** `renderShaderOverlay`
   was called only from the core/shader path, so a compatibility-profile context
   had no HUD, no developer overlay and no panels — a viewer whose menu could not
   be seen. Both passes ask for it now.
5. **`resolve_source` exited the process** for a missing file, which is right at
   start-up and became unacceptable the moment a viewer could open a second
   scene: clicking a stale library entry would have killed the window. It
   answers `None`; the policy lives with the caller.
6. **The movement modes were declared only by building a physics avatar**, so a
   viewer in free-fly — the default — had none: the controls page found nothing
   to offer and *silently did not open*, and `m` had nothing to cycle. They are
   declared at set-up now, and redeclared at the avatar's scale when a world is
   cooked.
7. **`oglc-gltf-demo` opened on the launch menu over its own model**, because
   "nothing to show" was being read as "no `source` was named" and a catalogue
   browser has no single source. The question is `hasSceneToShow()`, which a
   host with scenes of its own answers for itself.

## Second pass (2026-08-02, from live use)

Six things found by actually driving it, each fixed red-first.

1. **Every picture was upside down.** PIL hands its rows over top first and a GL
   texture's `v` runs bottom up, so the bytes as they came put every picture on
   its head — the gallery, the demo browser's reference thumbnail and twig-bb's
   level shots alike. Flipped once at decode, so no caller has to know this was
   ever a question. Measured against a real framebuffer
   (`test_ui_picture_orientation_gl.py`), not reasoned about. The decode path is
   unchanged from before this work, so it predates it.
2. **A carousel arrow chose as well as moved.** `release()` activated whatever
   the press landed on, arrows included, so a caller that opened the selection —
   which is what a band of pictures is *for* — opened something every time
   somebody pressed an arrow to look at the next one. An arrow looks; a picture
   chooses.
3. **Choosing a model left the launch menu over it.** The browse screen's
   `on_close` ran its Cancel handler for *every* close, and Cancel with nothing
   yet loaded puts the menu back. Only a close carrying no result is a cancel.
4. **Nothing on the shelf could actually be opened.** A Khronos entry carried
   the bare sample *name*, which is neither a path nor a URL, so the viewer
   answered "file not found". Entries carry the sample's own `.glb` URL.
5. **Escape ended the session outright.** Bound straight to `OnQuit`, so a key
   pressed to back out of something else threw away a loaded world or a match in
   progress, with no confirmation. `Context.OnEscape` is now a seam whose default
   is still to quit; the viewer and twig-bb override it to raise their menu, where
   **Resume** is offered first and Quit is still one click away.
6. **The suite opened a window per GL test.** Several hundred of them, flashing
   over whatever the person running it was doing. `tests/conftest.py` sets
   `OPENGLCONTEXT_HIDDEN` for the session, and `renderoptions.clean_environment`
   now carries the two *presentation* variables across rather than dropping them
   — how a render is shown is not what it contains, and every caller who forgot
   to pin them opened a window.

Also in this pass, because the shelf was full of things nobody wants to look at:
**`SceneSpec.feature_test`**, set from one readable roster
(`FEATURE_TEST_NAMES` plus the `Compare*` family, 63 of 150). The viewer shelves
those last as *Feature tests*, and `oglc-gltf-demo` walks the demos before the
fixtures — one flag, so the two cannot disagree. And the launch menu grew an
**address box**, since a viewer launched from a desktop has no command line to
pass a URL on.

## Third pass (2026-08-02, from live use)

More found by driving it, each fixed red-first.

8. **Nothing on the shelf could be opened.** An entry carried the bare sample
   *name*, which is neither a path nor a URL. Entries carry the sample's own
   URL — and `sample_model_url` names the `.glb`, which **Sponza, SciFiHelmet
   and Suzanne do not publish**, so `load_sample_url` falls back through the
   other variants exactly as `load_sample` always had.
9. **A model's textures were re-downloaded on every open.** `Resolver` memoised
   sub-resources *in itself*, and a fresh one is built per load. They go through
   the on-disk cache now: Sponza is 4.6 s cold and 0.7 s warm.
10. **Preview pictures took ~10 s to appear** for a file that fetches in 0.12 s.
    Nothing asked for a frame when one finished decoding, so it appeared
    whenever the next unrelated event happened to cause one. `PictureCache`
    reports arrivals; the renderer turns that into `triggerRedraw(0)`.
11. **`anim_time` leaked from the capture roster into the viewer**, pinning
    BrainStem, Fox and CesiumMan to one instant while the caption said
    "playing". That field exists for reproducible stills.
12. **Switching animation froze a skinned model.** `cycleAnimation` built a bare
    `Player`, losing the skins and world-matrix hook the *scene* wires in. The
    scene builds it now.
13. **Escape** — see 5 — and, at the user's direction, **Ctrl+PageUp/PageDown**
    steps the library while plain PageUp/PageDown stays the scene's own cameras.
14. **Keyboard navigation**: Tab and Space/Enter already worked; the up/down
    arrows did not move between items. `Panel.key` handles them after the
    focused widget declines, so a `Select`, `Slider` or `Carousel` keeps its own
    arrows.
15. **Only GLFW honoured `OPENGLCONTEXT_HIDDEN`.** Pygame, GLUT and wx mapped a
    window regardless, and `clean_environment` stripped the flag from any
    capture spawned through it. One reader (`renderoptions.hidden_window`), all
    four backends, and the two *presentation* variables now survive cleaning.
16. **Feature tests**: 71 of 150 roster entries marked, including the
    `Compare*` and `*TestGrid` families, and the shelf no longer offers
    `tests/wrls` at all — that is test data, not content.

## Follow-on

* `bin/terrain_view.py` (562 lines) still carries its own context. It is a
  world *generator* as much as a viewer and wants splitting (`oglc-bake`) first,
  per §B6.
* The developer overlay is taller than a short window and is clipped rather than
  scrolled — pre-existing, and more visible now that the viewer adds a section.
* The spawn clearance probe noted in
  [VIEWER-COMPONENT-EXTRACTION.md](VIEWER-COMPONENT-EXTRACTION.md) is still a
  placement test rather than a swept move.
* Preview pictures could be prefetched a page ahead rather than on first paint.
## Examine, in three parts

Right-drag was reported as doing nothing, then as unusably wild. Three separate
faults, each measured rather than reasoned about:

1. **No moves reached the drag.** The selection pass drops mouse-move events
   when nothing is listening, and asked `Context.hasMouseMoveHandlers`, which
   asked the dispatcher for receivers. A *capture* registers no receivers — it
   swaps the manager in the slot — so during a right-drag the check said nobody
   was listening and filtered away every move the drag existed to consume.
   `EventHandlerMixin.isCapturingEvents` answers that now. Proved by
   neutralising the method: MOVED became DID NOT MOVE.
2. **The pivot had nothing to do with what was on screen.** It fell back to a
   fixed ten units ahead of the camera, so a model framed four units away
   orbited about a point six units behind itself. It is now the scene's own
   bounding sphere (`Context.sceneBounds` / `examineCenter`,
   `boundingvolume.boundingSphere`), and a point ahead of the camera only when
   the camera is *inside* the scene.
3. **A click on empty sky unprojected successfully.** Depth 1.0 is a real world
   point out at the far plane — measured at (53.8, 42.1, 114.3) for a model
   three units across, a 77° swing for a small drag. A picked point is now taken
   only within reach of the bounding sphere (`EXAMINE_PICK_REACH`).

Separately the trackball turned a **full circle** for a drag to the edge of the
window; `EXAMINE_DRAG_ANGLE` halves it. Measured: 57° → 28.7° for a 40px drag,
with the distance to the pivot unchanged.

* **Bare PgDn did nothing either**, and for a different reason:
  `Context.__init__` ran `setupCallbacks` *before*
  `setupDefaultEventCallbacks`, so the framework's defaults were registered last
  and replaced whatever the application had bound for the same key. The viewer
  asked for PgDn and got `OnNextViewpoint`. PgUp worked only because nothing
  binds a default for it. The two now run defaults-first, which is the order the
  names imply. Found by tracing every registration of the key in a live context,
  not by reading.
* **Ctrl+PgUp/PgDn did nothing**: modifiers are `(shift, control, alt)` and the
  binding asked for the third slot, so it was Alt. A source-inspecting test
  asserted the same literal with a comment claiming the order was
  `(shift, alt, ctrl)`, which is how it survived. Bindings are now a
  `KeyBinding` table (`SceneViewerMixin.viewerKeys`) driven by real events
  through a real manager in `tests/unit/test_viewer_keys.py`, and every one
  fires on the key *release* so a held key does not repeat the action twenty
  times a second.

## Method

Red/Green throughout: the test first, watched failing, then the code. Test
expectations that turned out wrong were corrected in the *tests* — SFBool fields
read as 0/1, `Widget.activate()` rather than `Panel.dispatch()` is what a click
does, and a widget's `on_change` fires without the tree having been linked.
