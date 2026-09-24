# Multi-view rendering: N cameras on one window, one submission

## Status: In progress (2026-09-22)

Phase 1 (the PyOpenGL array checks) landed 2026-09-22. Phases 3, 4 and 5 --
`View`/`ViewLayout` with the `sequential`, `vertex` and `geometry` strategies
-- landed 2026-09-22 on the `multiview` branch of openglcontext; see "Landed"
below. Phase 2 is replaced by "Revised: one submission without world-space
shading". Phase 6's engine half -- `OrthoView`, `QuadView` and the
`tests/multiview_quad.py` tutorial -- landed 2026-09-22; the splitter drag,
per-view labels and the marble-editor adoption are next.

## What this is for

A world editor wants several views of the same world on screen at once: the
classic quad of top, front and side orthographic views around a perspective
view, or a map beside a three-quarter view. Every view shows the same scene
with the same shaders, materials, lights and shadow maps; only the camera, the
projection and the rectangle of the window differ.

The engine renders each frame for exactly one camera today, so the editors
swap cameras instead: glisteel-editor's `p` key trades the map for the angled
view (`glisteel-editor/glisteel_editor/app.py` `_look_at_it`), and
`docs/editing.rst` ("Looking at it from an angle") and
`glisteel-editor/plans/EDITOR-REMEDIATION.md` §K both name a split view as the
missing piece.

This plan makes N views an engine capability that any application can use,
and gives the editor toolkit a quad layout built on it. The target is one
submission of the scene per frame, whatever N is:

- the preferred path writes `gl_ViewportIndex` from the vertex shader
  (`GL_ARB_shader_viewport_layer_array`, or the older
  `GL_AMD_vertex_shader_viewport_index`), so each draw is issued once and
  instanced across the views it is visible in;
- a geometry-shader path does the same routing on GL 4.1 drivers without the
  vertex-shader extension (macOS), kept only if measurement says it beats the
  fallback;
- the fallback draws the scene once per view, sharing everything that does
  not depend on the camera.

The fallback exists so the feature works everywhere. The fast path is
expected on every current desktop driver; this container's Mesa radeonsi
(Radeon 8060S, GL 4.6) exposes `GL_ARB_shader_viewport_layer_array`, both AMD
extensions, `GL_ARB_viewport_array` and 16 viewports.

## Where the work lives

The editor toolkit is in the engine (`OpenGLContext.edit` and
`OpenGLContext.ui`), not in `openglcontext-editor`, which holds the baker,
world generation and assets. `openglcontext-editor/README.md` and the workspace
`CLAUDE.md` still describe the toolkit as part of that package; both are
corrected as part of phase 6.

| Project | What it gets |
| --- | --- |
| pyopengl | Size checks on the viewport, scissor and depth-range array entry points |
| openglcontext | The view block, world-space shading, `View`/`ViewLayout`, the three strategies, per-view picking and input routing, the quad layout in `OpenGLContext.edit` |
| glisteel-editor, marble-editor | Adopt the layout; the swap becomes a split |
| openglcontext-editor | README correction only |

## What the engine assumes today

Each item below is a single-camera assumption the plan has to remove. Paths
are relative to `OpenGLContext/`.

| Assumption | Where |
| --- | --- |
| One camera per frame, read from `context.getViewPlatform()` | `passes/_flat.py` `FlatPass.__call__`, `setViewPlatform` |
| The main view is the whole window; `glViewport(0, 0, w, h)` | `context.py` `Context.ViewPort` |
| Model and view premultiplied on the CPU (`modelviews = kept @ matrix`) and uploaded per draw as `modelViewMatrix` / `projectionMatrix` / `normalMatrix` | `passes/_flat.py` `renderSet`; `passes/shaderpass.py` `set_matrices` |
| Instance buffers hold an eye-space modelview per instance, re-uploaded every frame | `passes/instancing.py` `pack_instance_buffer`, `_build_instance_vao` |
| Lights, shadow matrices and `eye_to_world` resolved in eye space on the CPU | `passes/_flat.py` light setup; `passes/shadowmixin.py`; `passes/shaderpass_shadow.py` |
| No view or frame uniform block; only `MaterialBlock` at binding 1 | `shaders/pbr.frag`; `passes/pbrpass.py` |
| Every shader is `#version 330 core` | `shaders/` |
| One frustum; LOD chosen once per frame by mutating the `LOD` node | `passes/_flat.py` `calculateFrustum`, `selectLevels`; `scenegraph/lod.py` `selectAt` |
| Cascades fitted to the one camera frustum | `passes/shadowmixin.py` |
| Transparent shapes sorted back to front for the one camera | `passes/_flat.py` `shaderRenderTransparent` |
| Picking reads the pass's one `matrix`/`projection`/`viewport` | `passes/asyncpick.py` `_dispatchPickEvent`; `events/mouseevents.py` `unproject` |
| Navigation controllers and tools get one `getViewPort` callable | `edit/`, the editors' `controls.py` |

Some of the engine is already camera-independent. The gathered render table
(`gatherPaths` / `takeGather`) has no camera in it. Spot and point shadow maps
depend only on the light and the casters. The per-context shader program and
pass caches carry no view state.

## Design

### One path, with N = 1 as the ordinary case

A single-view application runs the same code with a one-view layout. There is
no separate multi-view renderer to keep in step with the real one: the whole
existing suite, visual regressions included, exercises the multi-view
machinery at N = 1 from phase 1 onward.

### Views and layouts

`OpenGLContext/views.py`, holding no GL:

- `View` - a camera (any object with the `ViewPlatform` matrix interface:
  `ViewPlatform`, `MapViewPlatform`, `OrbitViewPlatform`, the new
  `OrthoViewPlatform`), a rectangle in window pixels, a name, and a
  `ViewStyle` (shaded, unlit, wireframe; whether it draws the sky, the grid,
  the overlay decorations).
- `ViewLayout` - an ordered list of views, the rule that turns a window size
  into rectangles (single, two-way split, quad, with movable splitters), the
  active view (keyboard focus, audio listener, the view whose cascades are
  fitted), and `view_at(x, y)` for routing pointer events.
- `Context.viewLayout` - defaults to a single view wrapping
  `getViewPlatform()`, so existing applications and `self.platform`
  replacement keep working unchanged.

The largest supported N is `min(GL_MAX_VIEWPORTS, MAX_VIEWS)`, with
`MAX_VIEWS = 16` fixed by the size of the view block; `GL_MAX_VIEWPORTS` is at
least 16 on any GL 4.1 driver.

### The view block

A std140 uniform block at a new binding point, filled once per frame by one
`glBufferSubData`:

```glsl
struct ViewData {
    mat4 view;            // world (frame-origin relative) to eye
    mat4 projection;
    mat4 viewProjection;
    mat4 eyeToWorld;
    vec4 eyePosition;     // xyz, w unused
    vec4 viewportRect;    // x, y, w, h in window pixels
    ivec4 style;          // ViewStyle flags, shading mode
};
layout(std140) uniform ViewBlock { ViewData views[MAX_VIEWS]; };
```

That is 304 bytes a view and 4864 bytes for 16, inside the 16 KB minimum
`GL_MAX_UNIFORM_BLOCK_SIZE`. The Python packer is a pure function beside
`pack_material_block`, tested against the offsets the driver reports through
`glGetActiveUniformsiv(GL_UNIFORM_OFFSET)` so the two layouts cannot drift.

### World-space shading with a frame origin

Sharing one draw across views means nothing the shader receives per draw may
contain the camera. The per-draw `modelViewMatrix` becomes `modelMatrix`, the
instance attribute becomes a model matrix, and lights and shadow matrices move
to world space. The vertex shader looks the camera up in the view block.

Float32 world coordinates lose precision far from the origin, which matters in
glisteel's streamed world. Every model matrix is therefore uploaded relative
to a frame origin `O`, computed in float64 on the CPU. Each view's `view`
matrix is built relative to the same `O`. `O` follows the active view's eye in
fixed steps (1024 m, tunable), so static instance buffers only need rebuilding
when the origin moves a step. Precision near the active camera matches today's
eye-space path, and a view far from `O` (a top view framing a whole map) has
the resolution its own zoom level needs anyway.

A static instance group no longer has to be re-uploaded every frame, because
its buffer no longer contains the camera. That saving applies to single-view
applications as well; the forest's grass and trees are the case to measure.

### Strategies

`passes/multiview.py` chooses a strategy per context from its capabilities,
following the `ShadowCapabilities` pattern: a GL-free
`from_features(extensions, version)` for the rule, a cached per-context
`detect()` for the driver. `OPENGLCONTEXT_MULTIVIEW=vertex|geometry|sequential`
overrides the choice, so every strategy can be run and compared on one
machine.

| Strategy | Requires | How a draw reaches its views |
| --- | --- | --- |
| `vertex` | `GL_ARB_shader_viewport_layer_array` or `GL_AMD_vertex_shader_viewport_index`, plus `GL_ARB_viewport_array` (core 4.1) | One instanced draw; the vertex shader writes `gl_ViewportIndex` |
| `geometry` | `GL_ARB_viewport_array` (core 4.1) | One draw; a pass-through geometry shader with `invocations = MAX_VIEWS` emits the triangle to each view in the draw's list |
| `sequential` | GL 3.3 core | The draw is repeated once per view, with `glViewport` and a `viewIndex` uniform between |

All three use the same vertex and fragment shaders, with the view index
supplied differently:

- `vertex`: `#version 450`, `#extension GL_ARB_shader_viewport_layer_array :
  require` (or the AMD name), and `MULTIVIEW_VERTEX` defined. The vertex
  shader computes the view index from the instance id and writes
  `gl_ViewportIndex`.
- `geometry`: `#version 410` and a small geometry stage.
- `sequential`: the existing `#version 330 core` and a `viewIndex` uniform.

`preprocess_shader` already splices `#define` and `#extension` lines after
`#version`. It gains the ability to choose the `#version` line per program,
and the PBR program's compile adds the strategy's defines the same way it adds
`PBR_SKINNING` and the shadow defines today.

### Instancing across views: the view list and the divisor

In the `vertex` strategy every draw becomes instanced. A draw visible in `k`
of the views is issued with `instanceCount = k * instances`, and the shader
recovers both indices:

```glsl
uniform int viewCount;                 // k
uniform ivec4 viewList[MAX_VIEWS / 4]; // the k view indices, packed
int slot = gl_InstanceID % viewCount;
int viewIndex = viewList[slot / 4][slot % 4];
gl_ViewportIndex = viewIndex;
```

Per-instance attributes (model matrix, object id, material index, joint base)
are set with `glVertexAttribDivisor(location, k)`, so each instance's data is
repeated for its `k` view copies with no change to the buffer. The divisor is
VAO state, so it is set at draw time when `k` differs from the value the VAO
last had. A non-instanced shape is an instance group of one.

Because each draw lists only the views that can see it, culling stays exact
per view and no vertex work is spent on views the shape is not in. A shape
visible in one view costs the same as it does today.

### Culling and LOD across views

- Gathering runs once per frame, as today.
- Frustum culling tests each shape against every view's frustum in the
  existing vectorised `_frustumSurvivors` (8 corners by 6 planes by N views),
  producing a per-shape view mask. The draw list is the shapes with a
  non-empty mask.
- Instanced groups cull placements against the union of the views that can
  see the group's bounds (`InstancedShape.visiblePlacements` takes a list of
  frustums). Placements outside some of those views are clipped by the
  hardware.
- LOD stays one choice per frame, because `LOD.selectAt` mutates the scene
  graph. The level chosen is the most detailed any view asks for. The LOD
  metric gains an orthographic form (projected size from the ortho extent
  rather than the field of view), since `fieldOfView()` has no meaning for a
  top view. Tessellation LOD follows the same rule.
- Vegetation `field.update(camera)` and tiles `update_for_camera` take the
  layout's cameras. Their residency is the union of what each camera needs.

### Shadows

Spot and point shadow maps are rendered once and read by every view. That is
the largest share of the frame multi-view renders only once.

Directional cascades are fitted to the layout's active view; other views
sample the same cascades. Where an ortho view shows ground outside the
cascades, it samples the coarsest cascade, extended to cover the layout's
union bounds when `ViewLayout.shadowCoverage = 'union'` is set. Fitting
cascades per view would multiply the directional shadow cost by N, which the
editor case does not need.

### Framebuffer: tiles in one target

The views are rectangles of the ordinary window-sized render target, set with
`glViewportArrayv` and, with `GL_SCISSOR_TEST` enabled per index,
`glScissorArrayv`, so wide lines and points cannot draw past their tile. This
choice keeps the rest of the pipeline simple:

- The MRT selection buffer is window sized already, and a pixel belongs to
  exactly one view, so picking needs no second buffer.
- The transmission backdrop is a window copy sampled at `gl_FragCoord`, which
  is correct in any tile without change.
- The overlay UI is drawn once, over the whole window, after the views.
- Bloom and any blur that samples neighbours clamp their sample coordinates to
  the tile's `viewportRect`, so one view's highlights do not bleed into the
  next. Fullscreen passes are drawn as one triangle per view, routed by the
  same strategy.

`glClear` honours only scissor rectangle 0 under `GL_ARB_viewport_array`, so
the frame clears the whole window once. Each view's background (sky or flat
colour, per `ViewStyle`) is then drawn as a fullscreen triangle per view.

Texture-array layers (`gl_Layer`, or `GL_OVR_multiview` where NVIDIA exposes
it) were considered and set aside for the editor case: layers must share one
size, the result has to be composited back into the window, and picking would
need the layer resolved from the window position. They are the right tool for
stereo, and the view block and view-list machinery here carry over if that is
built later.

### Transparency

Back-to-front order depends on the camera, so one sorted list cannot be
correct for every view. The transparent set is drawn per view (the
`sequential` strategy for that stage only) until order-independent
transparency (`plans/ORDER-INDEPENDENT-TRANSPARENCY.md`) lands. OIT removes
the ordering, and the transparent stage then uses the context's strategy like
the opaque one. Editor scenes carry few transparent shapes; the frame-cost
test below measures what the per-view stage costs in the forest.

### View styles and grouping

A per-view style that the shader can express (unlit, flat colour, a debug
channel, grid-on-ground) is a field in the view block, and views that differ
only in those still share one submission.

A style that needs different GL state cannot share a draw: `glPolygonMode` is
not per viewport. The planner partitions the layout into view groups whose
state agrees and renders each group with the context's strategy. A quad with
one wireframe view is two groups: three views in one submission, one in
another. The `sequential` fallback is the same planner with groups of one.

The planner (`plan_view_groups(layout, capabilities) -> list[ViewGroup]`) is a
pure function, so its tests need no window.

### Input, picking and navigation

- `ViewLayout.view_at(x, y)` names the view under the pointer. The context
  stamps it on each mouse event, and `event.unproject()` and
  `edit.surface.ray_from` use that view's matrices and rectangle.
- Async picks record the view they were submitted for. A pick drained a frame
  later unprojects through the camera as it was when that frame was drawn,
  not through whatever the camera is now.
- Pointer-down captures the view: a drag that leaves the tile keeps talking to
  the view it began in.
- Each view carries its own navigation controller (`MapControls` for top,
  front and side; `OrbitControls` for perspective). The editor's event order
  (overlay, then tool, then camera) runs against the view under the pointer.
- The active view changes on pointer-down in a view. Keyboard navigation and
  the audio listener follow it.
- `TranslationGizmo` sizes its handles per view from the view block, so a
  handle has the same pixel size in every view. The handle geometry is shared
  and scaled in the vertex shader.

### The editor quad

In `OpenGLContext.edit`:

- `OrthoViewPlatform` - an axis-aligned orthographic camera (top, bottom,
  front, back, left, right), generalising `MapViewPlatform`, which becomes its
  top-down case. Pan and zoom-about-cursor are shared with `MapView`.
- `QuadLayout(ViewLayout)` - top, front, side and perspective, with a
  draggable cross splitter, a maximise toggle for the active view
  (conventionally the space bar), and a label and axis triad drawn per view by
  the overlay.
- Tools that work in the map (`ToolMode`, `Pointer`) work in any orthographic
  view, since `ray_from` already handles orthographic unprojection. Tools that
  need a surface point in the perspective view use the pick.

glisteel-editor replaces the `p` swap with a two-view split by default and the
quad on request. marble-editor adopts the quad.

## PyOpenGL

`glViewportArrayv`, `glScissorArrayv` and `glDepthRangeArrayv` (and the `NV`
double aliases) accept any array for `v`, without checking its length against
`count`. The generated wrappers record this (`# INPUT glViewportArrayv.v size
not checked against 'count'`, in `OpenGL/GL/VERSION/GL_4_1.py` and
`OpenGL/GL/ARB/viewport_array.py`). A short array lets the driver read past
the end of the buffer. The wrappers gain a size check (4 per viewport or
scissor, 2 per depth range) that raises before the call, with tests in
`tests/gl/test_gl41.py` for the short-array case. Forty-two inputs in
`GL_4_1.py` carry the same note. The other thirty-nine are a separate sweep,
recorded in PyOpenGL's own plan rather than done here.

Landed 2026-09-22, as a size kind rather than three wrappers: a `from-argument`
size with a multiplier, a minimum on both the C and the ctypes paths, applied to
the whole viewport-array family (the GLES2 `NV`/`OES` forms, the `NVX`
multicast pair and `glScissorExclusiveArrayvNV` included). The sweep is
[pyopengl/plans/INPUT-ARRAY-SIZES.md](../../pyopengl/plans/INPUT-ARRAY-SIZES.md).

## Phases

Each phase is red/green, lands with its documentation, and passes
`tools/preflight.py` for every project it touched.

1. PyOpenGL array checks. Short-array tests red, wrappers green. Landed.
2. The view block and world-space shading, at N = 1. Introduce `ViewBlock`, the
   frame origin, world-space lights and shadow matrices, and model-matrix
   instance buffers, with no visible change. The existing visual regression
   suite is the gate and must stay within its current tolerances. Static
   instance buffers stop re-uploading per frame; the forest frame cost is
   measured before and after.
3. `View`, `ViewLayout` and the `sequential` strategy. Layouts, `view_at`,
   per-view event routing and picking, per-view culling masks, LOD across
   views, shared shadows, tiled viewports and scissors, per-view backgrounds
   and post-effect clamping. This is the complete feature on every driver, and
   it produces the reference images the faster strategies are held to.
4. The `vertex` strategy. The view list, the divisor, the shader variant and
   the capability detection. Strategy-equivalence tests render the same
   four-view scene under `sequential` and `vertex` and compare the images
   within the visual suite's tolerance.
5. The `geometry` strategy, behind measurement. Built and held to the same
   equivalence tests; it becomes the automatic choice on drivers without the
   vertex extension only if it measures faster than `sequential` there.
   Otherwise it stays selectable by environment variable and the reason is
   recorded here.
6. The editor quad. `OrthoViewPlatform`, `QuadLayout`, splitters, maximise,
   per-view labels and gizmo sizing, and the glisteel-editor and marble-editor
   adoption. Documentation: `docs/editing.rst` gains the split and quad views
   (its "one window, two cameras" passage is rewritten), a new
   `docs/multiview.rst` covers `ViewLayout` for applications, and
   `docs/structure.rst` describes the view block. The editors' READMEs lose the
   "swap, not a split" limit, and the `openglcontext-editor` README and
   workspace `CLAUDE.md` stop placing the toolkit in that package.

## Landed: the sequential strategy (2026-09-22)

Built first, at the maintainer's direction: the no-extension GL 3.3 path, with
the faster strategies as upgrades where the driver allows them.

- `OpenGLContext/views.py` (no GL): `View`, `ViewStyle` (scene or flat-colour
  background, wireframe), `ViewLayout` with `single`/`split`/`stack`/`quad`
  and custom arrangements, `split_at`, `maximise`, `view_at`, the active view,
  and `route(event)` with press capture. `Context.viewLayout` /
  `getViewLayout()` / `routeEvent()`; `Event.view`.
- `OpenGLContext/passes/multiview.py`: `MultiviewCapabilities.from_features`
  / `detect`, `choose`, `ContextDefinition.multiview` and
  `OPENGLCONTEXT_MULTIVIEW`, and `ViewFrame`.
- The flat pass (both profiles) walks the scene once, chooses LOD once for
  every view (`LOD.levelAt`, `lod.Viewer`, the orthographic metric), culls per
  view, renders shadow maps once fitted to the active view, and draws each view
  inside its viewport and scissor. Picks resolve through the camera of the
  event's view, async picks through the camera as it was drawn.
- Shadow bindings keep the light's own matrices and compose the eye-space
  matrix per view; a view the cascades were not fitted to chooses its cascade
  by containment (`cascadeByFit`). Spot/point lights are kept while any view
  sees their reach.
- Bloom runs per view rectangle with clamped samples. Two defects found on the
  way and fixed: the bloom composite ran after `presentFrame`, so a bloomed
  frame was presented and screenshotted before its composite (black first
  frame, overlay bloomed); and `supports_bloom = False` on the compatibility
  pass was never consulted.
- Docs: `docs/multiview.rst` (new), `environment.rst`, `renderpasses.rst`,
  `structure.rst`, `shadows.rst`, `editing.rst`, both indexes.

The single-view frame is the same code with one view, and the whole suite,
visual regression included, passes on it unchanged.

## Landed: one submission for every view (2026-09-22)

- `geometry`: `shadersource.geometry_stage_source` generates the geometry stage
  from each lit vertex shader's `out` list (renamed `gs_*` by define), invoked
  once per view (`invocations = N`, so GL 4.0 or `GL_ARB_gpu_shader5` as well
  as viewport arrays), emitting each triangle to the views in `viewMask`.
- `vertex`: `shadersource.vertex_routing_source` compiles the lit vertex
  shaders at GLSL 4.10 with `GL_ARB_shader_viewport_layer_array` (or the AMD
  name); `routeToView` sends copy `gl_InstanceID % viewCount` to
  `viewList[...]`. Draws go through `multiview.draw_arrays` /
  `draw_elements`, instanced `mode.viewCopies` times; `draw_instanced_mesh`
  multiplies its instance count and sets every per-instance divisor to match.
- `ViewBlock` (binding 2): `mat4 refToClip; vec4 eye; ivec4 flags` per view,
  96 bytes, packed by `multiview.pack_view_table` and held to the driver's
  offsets in `tests/unit/test_multiview_shader.py`.
- `VRML97ShaderProgram.select_program_set(views, strategy)` keeps a second
  compiled set of the lit and vertex-colour programs per (strategy, views),
  each initialised once; every uniform setter already targets the set in
  place. The fragment shaders read the viewer through `toViewer()` and
  `viewCascadesByFit()` (`_viewer_inc.glsl`), which are `-p` and `false` in
  the single-view programs.
- Which shapes share: `FlatPass.sharesDraw` -- opaque, `geometry.multiviewShared`
  (Box, quadrics, IndexedFaceSet, triangle `PBRMesh`), no appearance program,
  no impostor or transmission, no per-view placements. Everything else is drawn
  per view after the shared stage. Tessellation LOD in a shared draw measures
  to the closest of `mode.viewerEyes`.
- Measured, 4 views, 400 boxes, shadows on, 1280x960, Radeon 8060S radeonsi:
  `sequential` 39.3 ms/frame (1534 draws), `geometry` 19.8 ms (400),
  `vertex` 19.1 ms (400). With the 400 as one instanced group: 16.1, 11.9 and
  11.4 ms. `geometry` is therefore the automatic choice where `vertex` is not
  offered (phase 5's condition), and `vertex` where it is.
- Tests: `test_multiview_geometry.py` renders one four-view scene with
  shadows, a transparent shape and an instanced crowd under each shared
  strategy and both renderers, and holds it to `sequential` (< 0.5% of pixels
  differ) and to one draw per shared shape; picking through a shared view.

Found on the way, not fixed here: PyOpenGL's `glGetUniformIndices` (GL 3.1
and `ARB_uniform_buffer_object`) sizes its output array by looking the
`uniformCount` argument up as a `glGet` enum, so any count but a handful
raises `KeyError`; the GLES3 wrapper already takes a list of names. The
engine passes its own output array. It belongs with the size sweep in
`pyopengl/plans/INPUT-ARRAY-SIZES.md`, whose uncommitted work touches the same
wrapper code.

## Landed: degrading, and the editor quad (2026-09-22)

- A strategy whose programs fail to compile is logged once and passed over
  (`FlatPass.multiviewFailed`, `MultiviewCapabilities.choose(failed=...)`):
  that frame draws the views in turn and the next uses the next strategy,
  so `vertex` falls to `geometry` and that to `sequential`. A layout of more
  views than `GL_MAX_VIEWPORTS` is drawn in turn (`FlatPass.sharesViews`).
  Held by `tests/unit/test_multiview_geometry.py` with forced compile failures
  and a forced viewport limit. A GL 3.3 driver without the extensions
  (`MESA_GL_VERSION_OVERRIDE=3.3` with the extensions overridden off) draws the
  quad tutorial identically, pixel for pixel, to the 4.6 driver.
- `OpenGLContext.multiview.cameras.OrthoView` / `OrthoViewPlatform`: the six axis
  views, pan, zoom about a pixel, box framing, pixel/world in the view's
  plane. `MapView` was kept as it is, since editors use its `(x, z)` API; the
  `'top'` OrthoView draws what it draws, which a test holds.
- `OpenGLContext.multiview.quad.QuadView`: the layout of three orthographic
  views and an `OrbitView`, `frame(minimum, maximum)`, and `handle(event)`
  for the context's pointer events (drag pans an ortho view, left drag orbits
  the perspective one and other buttons pan it, the wheel zooms the view under
  the pointer). `OrbitView` gained `frame_box` and per-view `nearest` /
  `furthest`; `GLTFScene` gained `minimum` / `maximum`.
- The multi-view code is a package of its own, `OpenGLContext.multiview`: the
  view model (`views`), the strategy a driver allows (`strategy`, which was
  `passes/multiview.py`), the axis-aligned camera (`cameras`, which was
  `edit/orthoview.py`), the gestures (`gestures`), the arrangements
  (`viewset`) and the ready-made four (`quad`). An editor is one caller of it;
  a game's mirror, a camera wall and a split screen are others, and none of
  them wants to import an editor toolkit to get a second view.
- `OpenGLContext.multiview.viewset.ViewSet`: several arrangements of one set of
  views, shown by name. An arrangement names the views it shows and is placed
  by how many there are -- one fills the window, two go side by side, four
  around a centre. The cameras are shared, so a switch shows what was already
  being looked at; `driven` names the views the pointer moves the cameras of,
  and `frame(minimum, maximum)` fits a box in each camera as its kind is
  fitted. `QuadView` is one of these with a single arrangement, and
  glisteel-editor's four are another.
- `OpenGLContext.multiview.gestures.ViewGestures`: the pointer moving the camera
  of the view it lands in, which `QuadView` is built on and an application
  laying out its own views uses directly. `views` names the views it drives, so
  a window whose plan view belongs to its tools keeps that one; `layout` is
  assignable, for a window that rearranges its views. It moves a
  `MapViewPlatform` as well as an `OrthoViewPlatform`.
- glisteel-editor adopted it (`glisteel_editor/views.py`): the `p` swap became
  four arrangements of the same cameras -- map, angled, the two side by side,
  and the quad with the front and left elevations -- with `v` taking them in
  turn and `space` maximising one. The map keeps the tools wherever it is on
  screen, since `MapControls` is told the map's own rectangle and a window
  pixel is read in the map's own pixels. The editor's `OrbitControls` went:
  `ViewGestures` does it. What is left in `glisteel_editor/views.py` is which
  views the editor has and how a landscape is fitted into them; marble-editor
  wants the same four arrangements over a map and an orbit camera, and builds
  its own `ViewSet` when it adopts them.
- `OpenGLContext.multiview.navigation.ViewNavigation`: what the pointer does
  in one view. Each view carries one; it says which gestures its camera can be
  moved by (`pan`, `rotate` where the camera turns, `zoomin`/`zoomout`, and
  `zoomdrag` for a pointer with no wheel) and holds the bindings that raise
  them. The bindings are `KeyBinding` nodes and a button is named as the event
  system names it, so the bindings screen and the binding file already handle
  them. `ViewGestures` resolves each event through the view it lands in, so
  rebinding one view changes that view alone.
- `OpenGLContext.ui.viewchrome.ViewChrome`: the furniture of a window of
  views -- each one's name, an axis triad that turns with its camera, an
  expand button, a navigation button offering that view's gestures, and a
  splitter on each dividing line with a handle where a quad's two cross. A
  modeless panel that paints nothing of its own, so a press on no control
  reaches the scene. Every part switches off, and `only` gives one view a set
  of its own. glisteel-editor gives its map the expand button alone.
- `tests/multiview_quad.py` loads any glTF model into the quad; it is in the
  visual suite with a baseline and in the "Interface and Tools" tutorial path.
- `scripts/multiview_bench.py` measures a layout against a single view, which
  is what an editor wants before it opens four views. At 1280x960 on a Radeon
  8060S (Mesa radeonsi), 60 frames after 20 warm-up frames, the quad costs
  against one view: one glTF model (Lantern, 3 draws) 1.40x `vertex`, 1.43x
  `geometry`, 1.58x `sequential`; 400 boxes batched into one instanced draw
  8.80 ms -> 1.34x, 1.40x, 2.08x; 400 boxes drawn singly 16.60 ms -> 1.21x,
  1.24x, 2.41x. So a shared strategy costs about a quarter to a half again,
  and the fallback between a half and a further 1.4x on top of that.

Found on the way and fixed in the engine:

- glTF models drew nothing under the compatibility profile: `PBRMesh` had no
  fixed-function draw and `PBRMaterial` no `render`. Both exist now (factors
  through `glMaterial`, the base colour map bound by `Appearance`).
- The fixed-function sphere background was clipped by any near plane beyond
  one unit, which an orbit camera's is; it draws with `GL_DEPTH_CLAMP`.

Found on the way in PyOpenGL: with OpenGL_accelerate, the typed client-array
setters (`glVertexPointerf`, `glColorPointerf`, ...) leave the driver reading
memory that does not hold the array; with `PYOPENGL_USE_ACCELERATE=0` they are
correct. It is what drew the compatibility profile's sphere background
magenta. The C dispatch layer recorded one set of customisations per entry
point, so every typed variant replayed the first (`...Pointerd`) variant's
GLdouble converter while telling the driver its own type. Fixed on pyopengl
branch `pointer-lifetime` (3d9e8715, not yet merged): customisations belong to
the chain that made them. `test_sphere_background_legacy.py` passes against
it and fails against a PyOpenGL without it.

## Landed: the view menu, the scene's cameras, and pointer feedback (2026-09-23)

- The name menu drew as text at the bottom of the window: `ViewChrome` pushed
  it without a size and `OverlayStack.push` left `laidOutFor` alone, so the
  frame never laid the menu out. `push` without a size now invalidates the
  stack. The menu was also built without its stack, so its submenus could not
  open; the stack a panel is pushed on is now its stack unless it names one.
- The name is a button (the corner buttons' face and a caret), and its menu is
  View (the eight kinds), Cameras, Rendering (shaded / wireframe), Zoom to fit
  and Maximise. "What the pointer does" and the never-built `NavigationButton`
  (whose `open_navigation` did not exist) are gone; `ViewNavigation` itself is
  unchanged and still rebinds per view from code and the bindings screen.
- Menus: the row under the pointer takes the keyboard and draws
  `skin.menuHighlight`; every row has an access letter (automatic, or
  `mnemonic`), underlined one pixel under the baseline (`FontMetrics.baseline`
  from the atlas); a menu with no room below opens on top of what opened it
  (`above`); separators have room either side. Rows had their text 8 px above
  centre -- the row was inset vertically by its horizontal padding.
- Every interactive widget shows `skin.hoverWash` under the pointer (unless it
  lights itself) and a ripple (`RIPPLE_SECONDS`) from the press point, or from
  its middle when run from the keyboard. Roots track running effects and the
  overlay asks for frames while any run; a chosen menu lingers `linger`
  seconds so its ripple is seen.
- Scene cameras: the render pass publishes its live Viewpoint paths as
  `SceneGraph.viewpointPaths` each frame and calls
  `Context.OnViewpointsChanged`; viewpoint binding reads the same table rather
  than its own `visitor.find` walk, so a Viewpoint added after the first frame
  (an async glTF load) is bindable. `multiview.viewpoints` turns the paths into
  `SceneCamera`s (VRML97 Viewpoints and glTF cameras alike, nested transforms
  applied) and `look_through` points a view through one -- an `OrbitView`
  standing at the camera (`OrbitView.stand_at`), or the Viewpoint bound for a
  view drawn through the window's camera.
- `QuadView` opens its perspective view thirty degrees round from the front
  (`OPENING_HEADING`) rather than straight down -z, or through the camera
  `choose_camera` picks the first time `cameras_found` is told any; its orbit
  may go below the model (`OrbitView(lowest=...)`).

Still open: wiring a QuadView with its own orbiting camera into a window takes
about forty lines the demo spells out (layout, framing, chrome, event routing,
redraws, cameras), where `MultiViewMixin` over the window's own camera takes
one call. A mixin option for an orbiting perspective view would make the two
the same size.

## Revised: one submission without world-space shading

Phase 2 as written moves every shader to world space so a draw carries no
camera. There is a smaller route to the same single submission. The shared
stage draws with the *active* view as a reference camera: the CPU uploads
modelviews and instance buffers in the reference camera's eye space exactly as
the sequential path does, lights and shadow matrices are bound once in that
space, and only the last step differs -- a generated geometry stage (or, for
`vertex`, the vertex stage) emits each primitive once per view in the draw's
view mask with `gl_Position = views[v].refToClip * vPosition` and
`gl_ViewportIndex = v`. The eye-space varyings stay in reference space, so the
fragment shaders keep their lighting unchanged; what depends on the actual
viewer reads a per-view record: the eye's position in reference space (view
vector, fog distance), the clip transform (refraction lookup), and whether the
view reads cascades by depth or by containment. The record is 96 bytes
(`mat4 refToClip; vec4 eye; ivec4 flags`), so 16 views are 1.5 KB.

Precision matches the plan's frame-origin argument: reference eye space is
world space centred on the active camera.

Shapes that draw with a program the stage is not compiled into (vegetation,
terrain, particles, text, point and line sets), transparent and transmissive
shapes, and backgrounds stay per view.

2026-09-24 ([PLANAR-MIRRORS.md](PLANAR-MIRRORS.md) step 8): terrain ground and
the instanced vegetation now join the shared draw, through
`instancedgl.ViewPrograms`; particles, text, point and line sets remain per
view.

## Tests

- Pure, no window: `ViewLayout` rectangles for each layout and window size,
  splitter drags and the maximise toggle; `view_at` on tile boundaries;
  `plan_view_groups` partitioning; strategy selection from extension lists
  (`from_features`); the view-block packer; per-view frustum masks and the
  union placement cull; the ortho LOD metric; frame-origin stepping and the
  float64-to-float32 relative matrices.
- With a GL context (`gl_context` fixture): view-block offsets against the
  driver; the shader variant compiles for each strategy the driver supports;
  the divisor survives VAO rebinds.
- Visual (`visual_regression_runner`): a four-view scene recorded under
  `sequential`, with `vertex` and `geometry` held to it; per-view backgrounds;
  bloom not crossing a tile edge; a wireframe view grouped beside shaded ones.
- Interactive (`interactive_runner`, `event_sender`): a click in each quadrant
  selects through that view's camera; a drag that starts in one tile and
  leaves it keeps its view; the active view changes on click.
- Frame cost: a deterministic count of `glDraw*` calls per frame for the
  four-view forest scene. `vertex` issues the single-view count and
  `sequential` issues N times it, excluding the transparent stage until OIT.
  A wall-clock comparison of the two runs under the `serial` marker as a
  reported figure. The count is the gate, because it does not depend on
  what else the machine is doing.

## Decisions for the maintainer

- Moving shading from eye space to world space with a frame origin (phase 2)
  touches every core-profile shader and the instancing layout. It is what lets
  one draw serve several cameras, and it removes the per-frame re-upload of
  static instance buffers for every application.
- Shader programs move off `#version 330 core` where the strategy needs it
  (`450` for `vertex`, `410` for `geometry`). `sequential` keeps 330, so GL
  3.3 drivers keep working.
- Transparency is drawn per view until OIT exists, rather than sorted once for
  the active view with visible errors in the others.

## Open questions

- Which shipping drivers expose `GL_ARB_shader_viewport_layer_array`. Mesa
  radeonsi does (this container); NVIDIA exposes it on Maxwell and later. The
  Intel Windows driver and Mesa iris need confirming in CI, where the
  strategy's choice is logged.
- Whether `GL_NV_viewport_array2`'s `gl_ViewportMask[]`, which broadcasts one
  primitive to several viewports without instancing, is worth a fourth
  strategy on NVIDIA. It would replace the divisor arithmetic with a mask. It
  is only worth building if phase 4 shows the instance multiplication costing
  anything measurable.
