# Planar mirrors: a reflection is another view of the scene

Status: **Complete** — 2026-09-24, visual baselines to be checked by
preflight on the main checkout. See *What landed* at the end.

## Why

Water reflects the scene ([WATER-REFLECTION.md](WATER-REFLECTION.md)), and
nothing else does. A bathroom mirror, a polished marble floor, a shop window, a
still indoor pool: each reflects the image-based-lighting probe, which is the
sky, so a mirror on a wall shows clouds. A game built on the engine wants
mirrors it can mark on a surface, and wants a dozen of them in a level without
the frame rate halving.

The water reflection draws the scene again through a mirrored camera, with its
own `renderSet`, lighting setup and opaque pass, once per view with water in
it. That is one extra submission of the scene per reflection, and a budget of
two or three reflections is all that allows.

A reflection is the same scene seen through another camera: the view matrix
mirrored in a plane and a projection whose near plane lies on it. That is what
a view in [MULTI-VIEW-RENDERING.md](MULTI-VIEW-RENDERING.md) is, and the
multi-view work already sends one draw to up to sixteen views.
`multiview.strategy.view_records` builds each view's `refToClip` from any
`modelView` and `projection`, so a mirrored, obliquely clipped camera is an
ordinary view to it. `renderShared` draws every shape that can serve several
views once, and the `vertex` and `geometry` strategies route each triangle to
the viewports in the shape's mask. So this plan makes each reflection a view,
and draws all of a frame's reflections in one shared submission.

## What lands

### 1. A reflector is something a surface is marked as

A surface reflects the scene only when its material carries a
`PlanarReflector` node, put there by the `mirror` hook in a file or by the
application in code. The engine never promotes a surface on its own: a glossy
material without one, however low its roughness, reflects the probe and costs
nothing. The node is how an author opts into the cost.

`PlanarReflector` is a scenegraph node in a new
`OpenGLContext/scenegraph/reflector.py`, registered in `basenodes` (and so in
`basenodes.pyi`), with the fields that say how much the mirror is worth:

```python
class PlanarReflector(Varied, node.Node):
    """A material's surface mirrors the scene in its plane."""
    PROTO = 'PlanarReflector'
    # tile size as a share of the mirror's screen rectangle
    scale = field.newField('scale', 'SFFloat', 1, 0.5)
    # most frames a visible reflection may go without a redraw
    interval = field.newField('interval', 'SFInt32', 1, 3)
    # weight against other reflectors when the budget is short
    priority = field.newField('priority', 'SFFloat', 1, 1.0)
    # screen offset per unit of normal tilt (the normal map's, or water's ripple)
    distortion = field.newField('distortion', 'SFFloat', 1, 0.0)
    # False keeps the node in place while the surface reflects the probe
    enabled = field.newField('enabled', 'SFBool', 1, True)
```

`PBRMaterial` gains `reflector = field.newField('reflector', 'SFNode', 1,
node.NULL)`. The material is where it belongs: the PBR program is the one that
reads a reflection, a reflection is weighted by the material's own metalness,
roughness and Fresnel, and the hook that marks it is a material hook. Every
shape drawn with that material is a mirror, each in its own plane. Being a
node, it is written and read by the VRML97 and glTF paths like any other,
shows in the scene outline and the settings page a node's fields generate,
and one `PlanarReflector` can be `USE`d by every material of a set of
mirrors, so a game tunes them together; `varied()` (the `Varied` mixin that
`WaterStyle` and the vegetation species use) gives one mirror its own. Its fields are read each frame, so a
change takes effect on the next.

Instancing keys an appearance by its material, so shapes whose materials
carry different reflectors do not batch together; a reflector's shapes draw
per view anyway (section 10).

The `water` hook puts one on its material (`interval=1`, `distortion` from
`REFLECTION_DISTORTION`), so `is_water` becomes one case of `is_reflector` and
water goes through the same path as every mirror. In code:

```python
material.reflector = PlanarReflector(interval=2)
```

The plane comes from the mesh: its best-fit plane (mean position and the
direction of least variance), carried into the world by the record's matrix.
The mark is checked once per mesh; a mesh whose points stand further than 1% of
its extent off that plane logs a warning and reflects the probe, because a
planar reflection of a curved surface is right along one line only.

The eye has to be on the side the normal faces. For water that is "above the
lake"; for a wall mirror, "in front of it". `water_plane`'s height test already
expresses this, with the mesh's normal in place of the sheet's up.

### 2. Authoring: the `mirror` hook kind

`mirror` joins `water`, `fire`, `smoke` and `sparks` in `hooks.BUILTIN`,
handled by a new `OpenGLContext.scenegraph.mirrorhooks`. It is a material hook,
like water, so every primitive drawn with that material becomes a reflector:

    OGLC_hook = {"kind": "mirror", "scale": 0.5, "interval": 2, "priority": 1.0}

`OGLC_hook = "mirror"` is the shorthand with every default. The material the
file carries is kept: its base colour tints the reflection, its metalness and
roughness weight it through the split-sum term the probe reflection already
goes through, and its normal map breaks it up. A silvered mirror is metallic 1,
roughness 0; a polished floor is a dielectric with low roughness, and reflects
faintly looking down and strongly at a glance with no extra parameter.

The Blender add-on (`tools/blender/oglc_hook/tag.py`) gets `mirror` in its kind
list, with fields for the parameters.

### 3. A reflection is a view

For each main view and each reflector visible in it, the pass makes a mirror
`ViewFrame`:

- `modelView` - the main view's, premultiplied by `mirror_matrix` for the
  reflector's plane.
- `projection` - the main view's, cropped to the mirror's screen rectangle
  (section 5) and given the oblique near plane on the mirror's plane
  (`oblique_projection`). Both are in the matrix, so `refToClip` carries them
  into every strategy's vertex stage unchanged, and what stands behind the
  mirror is clipped in every program with no clip-plane code.
- `rect` - the reflection's tile in the reflection atlas (section 4).
- `fitted=False` - its shadows read the directional cascades by containment,
  as a non-active view already does.
- `toRender` - the frame's gather culled through the mirror view's frustum,
  as `renderWaterReflection` does now.

The mirror views of a frame are drawn together, before the main views:

1. The reflection atlas is bound, and each tile to be redrawn is cleared to
   alpha 0 under its own scissor.
2. `glFrontFace(GL_CW)` for the whole submission, since every view in it is
   mirrored. `PBRMesh` picks its front face from its modelview's determinant,
   and in a shared draw that is the reference camera's, which is not
   mirrored; it gains a pass flag, `mirrored`, that inverts its choice.
3. `renderShared(mirror_frames, …)` with the active main view as reference:
   one draw per shape for every mirror view whose mask holds it. Lights,
   shadow matrices and IBL are bound once in the reference's eye space, as
   for the main views.
4. What `sharesDraw` refuses is drawn per mirror view, as a main view draws
   it: terrain, vegetation fields, particles and other shapes with their own
   programs. Transparent shapes are not drawn into reflections at all.

Vegetation is refused for its programs, not for transparency: its cards are
alpha cutout, drawn with blending off, and are opaque as far as depth and
ordering go. `veg_billboard`, `veg_clump` and `veg_mesh` are their own programs
with their own `uModelView` and `uProjection`, and three things in them are
computed for one camera: a billboard is turned to face it, the mesh-to-impostor
cross-fade and the near and far dissolves are measured from it, and
`TreeField.update` chooses which trees are meshes and which are cards around
it. Step 8 moves the first two onto the view table, where each view's eye is
already recorded in reference space, and adds the `routeToView` stage; after
that a vegetation field is one instanced draw for every view that sees it. The
third needs no change: a reflected path from eye to tree is never shorter than
the straight one, so the choice made for the main camera is at least as
detailed as any of its mirror views needs.
5. Reflectors are not drawn into any mirror view: one bounce.

The mirror views are a submission of their own, not views added to the main
views' draw, for three reasons in the GL: they draw into another framebuffer,
they want the opposite front face, and they have to be finished before a main
view shades a reflective surface.

`GL_MAX_VIEWPORTS` is at least 16 on a GL 4.1 driver and `MAX_VIEWS` is 16, so
one submission carries sixteen mirror views: twelve mirrors in one view, or
three in each of four editor views. A frame wanting more makes a second
submission.

Under the `sequential` strategy, which a GL 3.3 driver or one without
`GL_ARB_viewport_array` gets, `renderShared` is a draw per view, and each
mirror view costs what a water reflection costs now. The budget's defaults
depend on the strategy for that reason (section 7).

### 4. The reflection atlas

Every reflection is a tile in one RGBA16F colour target with a 24-bit depth
buffer, `ReflectionAtlas`, which replaces `ReflectionBuffer`. One target:

- lets a single framebuffer take every viewport of the shared submission;
- binds once on `REFLECTION_UNIT` for every reflective draw of the frame, so
  no reflective draw rebinds a texture, and reflective shapes of one mesh can
  still batch;
- sets the memory: the atlas is `reflectionAtlas` times the window's pixels
  (default 0.5), about 15 MB with depth at 1440p, however many mirrors there
  are.

Where the tiles go is a plain object with no GL, `TilePacker`: shelves of
power-of-two heights, a 4-texel gutter round each tile, and a tile that is not
being redrawn this frame keeping its place, so a stale reflection stays
readable. When the packer cannot place a tile it repacks, and every tile that
moved is redrawn that frame. When the atlas is full, the schedule has already
reduced tiles' scale to fit (section 8).

### 5. Drawing only the mirror's part of the screen

A bathroom mirror covers a small part of the view, and its reflection needs
only that rectangle. The planner projects the mirror's bounding box into the
main view, clips it to the view rectangle, and gives the mirror view an
off-centre projection covering that rectangle plus a guard band of 10% each
side. The tile is that rectangle times the reflector's `scale`. The frustum the
mirror view culls with is the cropped one, so its mask in the shared draw holds
only what can appear in the mirror.

A mirror outside the main view's frustum is not in its `toRender` and is not a
candidate, so no extra walk finds candidates.

### 6. Reading the reflection by projection

Water looks the reflection up at the fragment's own screen position, which is
right only when the reflection was drawn this frame for this camera. Instead,
each tile keeps the mirrored `modelproj` it was drawn with and its rectangle in
the atlas, and the fragment shader projects its world position through that
matrix into the tile. For a fresh tile that is the same texel as the screen
position, and a test holds them to it.

For a tile a frame or two old, each static object's reflection is where the
old mirrored camera saw it; the error is the parallax between the old eye and
the new, under a texel of a half-scale tile at walking pace over two frames.
Moving objects in a reflection lag by the tile's age. The guard band covers a
turn of the head between redraws. A texel outside the tile, or one the mirror
view left at alpha 0, reads the probe instead, as the sky does for water now.

### 7. The budget

The budget is per frame, across every main view:

| Setting | Default | Meaning |
|---|---|---|
| `ContextDefinition.planarReflections` (env `OPENGLCONTEXT_PLANAR_REFLECTIONS`) | on | Reflectors reflect the scene. Off, every reflector reflects the probe. `waterReflection` stays as the water-only switch. |
| `reflectionViews` (`OPENGLCONTEXT_REFLECTION_VIEWS`) | 16 under `vertex` or `geometry`, 2 under `sequential` | Most mirror views drawn in one frame. |
| `reflectionSeparateViews` (`OPENGLCONTEXT_REFLECTION_SEPARATE_VIEWS`) | 4 | Of those, most that also draw the shapes a shared draw refuses (terrain, vegetation, particles), each of which costs a draw per mirror view. |
| `reflectionAtlas` (`OPENGLCONTEXT_REFLECTION_ATLAS`) | 0.5 | The atlas's size as a share of the window's pixels, which bounds the texels drawn. |
| `reflectionMilliseconds` (`OPENGLCONTEXT_REFLECTION_MS`) | 0 (off) | A GPU time the mirror submission aims to stay under, measured (section 9). |

The first four are counts and sizes, so a capture or a visual baseline draws
the same reflections every run. The last adapts to the machine and is off by
default for that reason.

With the shared draw, a mirror view's cost is its fragments plus a vertex-stage
copy of what it sees, and the draw calls do not grow with the number of
mirrors. Fragment cost is bounded by the atlas. The separate-view cap is there
because terrain and vegetation are the costly shapes in an outdoor reflection
and do not share yet; making their own programs multi-view is its own step
(step 8 below) and raises that cap to `reflectionViews` when it lands.

### 8. The schedule

Which mirror views are drawn each frame is decided by `ReflectionSchedule`, a
plain object with no GL. Each frame it is given the candidates, each with its
reflector, screen rectangle, tile age in frames, how far the camera has moved
relative to the mirror since the tile was drawn, and whether its frustum holds
any shape that does not share. It returns the ones to draw and each one's tile
size. The rules, in order:

1. A candidate with no tile, or whose tile was drawn for another view, plane or
   size, or was moved by a repack, must be drawn.
2. A candidate whose tile has reached its reflector's `interval` must be drawn.
3. A candidate whose camera has moved or turned far enough that the
   reprojected tile is wrong by more than a texel must be drawn. The bound is
   an angle: the camera's turn plus its travel over its distance to the
   mirror, against the angle one texel of the tile subtends.
4. Every other candidate is optional, scored by screen area × priority ×
   (age + 1), highest first, and drawn while the budget has room.

When rules 1-3 ask for more than the budget allows, the must-draw candidates
are taken by the same score, and those left over are drawn at half scale before
any is left stale. A candidate left out keeps its old tile, or reflects the
probe if it has none. Age raises a candidate's score every frame it is passed
over, so none is left out indefinitely.

In a room with a large wall mirror, a polished floor and ten small mirrors down
a corridor, under `vertex` on a discrete GPU: all twelve fit the default view
count, the large mirror and floor redraw every frame on area, and the small
ones redraw every second or third frame as their `interval` allows, so the
atlas carries the texels of four or five tiles a frame. Under `sequential` the
same scene draws two mirror views a frame and the small mirrors take turns.

Within a mirror view:

- Levels of detail are the ones the frame chose for its main views, which are
  at least as detailed as a reflection needs, since a reflected object is
  further from the eye than the mirror is. Mirror views take no part in
  `chooseLevels`.
- A shape whose bounds project to under two texels of a tile is left out of
  that view's mask.
- The sky is not drawn; alpha 0 lets the probe through.

### 9. Measuring what it costs

`reflectionMilliseconds` needs the GPU time of the mirror submission. A small
`GpuTimer` in `OpenGLContext.passes` holds `GL_TIME_ELAPSED` queries in a ring
of three, so a result is read two frames after it was issued and nothing waits
on the GPU. The schedule scales the atlas texels it will fill by a smoothed
ratio of target to measured time, between 0.25 and 1. Session telemetry records
each frame's mirror views, texels and time as a phase of the frame.

### 10. Shader

`planarReflected()` loses its `waveEnabled` gate. A reflective draw sets a
`planarMatrix` (the tile's mirrored `modelproj`), a `planarTile` (its rectangle
in the atlas) and `planarDistortion`. The lookup:

- world position through `planarMatrix`, into the tile, clamped half a texel
  inside it;
- pushed by the normal's tilt from the plane's normal times
  `planarDistortion`, which for water is the ripple and for a mirror is its
  normal map;
- for a rough surface, read at mip levels 1 or 2, which the 4-texel gutter
  keeps inside a tile. The atlas is mipmapped after the submission only in a
  frame where a drawn tile belongs to a reflector with roughness above 0.05.
  A reflector above 0.6 roughness is not a candidate: the prefiltered probe is
  as blurred as that reflection would be;
- blended over the probe by alpha, as now.

A reflective shape is drawn per main view, since each main view reads a
different tile for it; `sharesDraw` refuses a reflector. With that, a reflector
among several views reflects the scene in each of them, where water shared
across views reflects the sky now.

`PBR_PLANAR_REFLECTION` stays the compile-out for a driver without the texture
unit.

## What it takes, in order

Each step is Red/Green, and the logic in steps 1-4 lives in plain objects with
no GL.

1. The `PlanarReflector` node and `PBRMaterial.reflector`, the mesh plane fit
   and the planarity check; `is_reflector` with water as one case. Tests that
   the node round-trips through the VRML97 writer and the glTF hook, for planes at every orientation, a shear in
   the placement, and a mesh that is not flat.
2. Mirror `ViewFrame`s: the cropped, guard-banded oblique projection and the
   projective lookup. Tests that a fresh tile's projective texel equals the
   screen-position texel for a spread of mirrors and cameras, and that
   `view_records` carries a mirror frame's clip transform exactly.
3. `TilePacker`: gutters, stable placement of stale tiles, repacking and
   reporting what moved.
4. `ReflectionSchedule`: the view, separate-view and atlas budgets are never
   exceeded; every visible candidate is drawn within its `interval` while the
   must-draw set fits; a camera jump forces a draw; a candidate passed over
   rises until drawn; a short budget halves scale before leaving a tile stale;
   the millisecond feedback stays within its bounds.
5. The pass: `ReflectionAtlas`, the mirror submission through `renderShared`
   with the `mirrored` front-face flag, per-view draws of what does not share,
   and reflective draws reading their tiles. `renderWaterReflection` becomes
   this. The water baselines must not move, and a draw count holds the mirror
   submission to one draw per shared shape whatever the number of mirror
   views, under `vertex` and `geometry`, as the multi-view suite does for main
   views.
6. `GpuTimer` and the telemetry phase.
7. The `mirror` hook kind and the Blender panel fields.
8. Terrain and vegetation programs gain the multi-view stage, so they share
   across mirror views and across editor views alike: the `routeToView`
   include, billboard facing and distance fades taken from `views[vView].eye`,
   and a `multiviewShared` mark `sharesDraw` accepts for a field that culls
   its placements against the union of the views that see it. Tracked in
   MULTI-VIEW-RENDERING.md; the separate-view cap goes when it lands. A lake
   in a forest is the ordinary outdoor case, so this step is worth doing
   before step 9's demo is measured.
9. A demo scene in `tools/blender/demos/`: a room with a large mirror, a
   corridor of small ones, a polished floor and a pool. Rendered-frame tests
   of a mirror showing what stands in front of it, a floor reflecting a lamp,
   twelve mirrors under each strategy against one baseline, and a stale tile
   after a small camera move matching a fresh one within tolerance.
10. Documentation (below).

## Documentation

- `docs/reflections.rst`, new: what a reflector is, the `mirror` hook and its
  parameters, the `PlanarReflector` node and its fields, how reflections are drawn as views, every
  budget setting with its units and default, what the schedule does with a
  short budget, and the limits.
- `docs/multiview.rst`: mirror views as a second use of the shared draw.
- `docs/water.rst`: its reflection section points to the new page for the
  shared mechanism and keeps what is water's own.
- `docs/gltf.rst`: the hook-kind list gains `mirror`.
- `docs/renderpasses.rst`: the mirror submission in the frame's order.
- `docs/telemetry.rst`: the reflection phase.
- `docs/index.rst` and `docs/documentation.rst` list the new page.
- `tools/blender/README.md`: the new kind.
- `CLAUDE.md`'s directory map: `reflection.py` describes reflections, not
  water's alone.
- WATER-REFLECTION.md's limits on one plane per view and on shared water are
  lifted, and PROJECT-PLAN.md says so.

## Limits

- Flat surfaces only. A curved mirror, a chrome sphere or a car body reflects
  the probe; that is the per-object probe in [RUNTIME-IBL.md](RUNTIME-IBL.md).
- One bounce: a mirror seen in a mirror reflects the probe.
- A moving object's reflection lags by its tile's age, up to its `interval`
  frames. `interval=1` on a reflector where that shows.
- Transparent shapes are not drawn into any reflection.
- Sixteen mirror views per submission; more cost another submission.

## Questions for review

- Should `waterReflection` fold into `planarReflections`, with water being one
  reflector? The plan keeps both, so a game can keep its lake and drop its
  mirrors.
- Is half the window's pixels the right atlas default?
- Should the `mirror` hook also be allowed on an object (every material of its
  mesh), as fire is, or only on a material, as water is?

## Answers from review (2026-09-24)

- `waterReflection` folds into `planarReflections`: water is one reflector,
  and one switch turns every reflection off.
- The atlas stays at half the window's pixels.
- The `mirror` hook is allowed on a material and on an object. On a material
  the material shades the reflection; on an object every surface shows only the
  reflection (`PlanarReflector.replace`), its own materials set aside.

## What landed (2026-09-24)

Modules: `scenegraph/reflector.py` (`PlanarReflector`, `WATER`),
`scenegraph/mirrorhooks.py`, `scenegraph/surfaces.py`, `passes/reflection.py`
(arithmetic), `passes/reflectiontiles.py` (`TilePacker`, `ReflectionSchedule`),
`passes/reflectionplanner.py` (`ReflectionPlanner`: the whole per-frame
decision, no GL), `passes/reflectionatlas.py`, `passes/gputimer.py`, and
`bin/mirrors_demo.py` (`oglc-mirrors`). The Blender hall is
`tools/blender/demos/mirrors.py`. User page: `docs/reflections.rst`.

Where it departs from the plan above, and why:

- Rule 3 of the schedule measures the camera's *travel* over its distance to
  the mirror, not its turn: a turn about the eye leaves every reprojected point
  where it was, and the guard band covers what it brings into view. The plan's
  "under a texel at walking pace over two frames" does not hold: walking at
  1.5 m/s three metres from a mirror moves a half-scale tile's reflection about
  four texels a frame, so a moving camera redraws the mirrors near it every
  frame and `interval` pays off for a still or slow camera and far mirrors.
- One bounce became two: a mirror seen in a mirror view shows the reflection it
  had the frame before, read from a copy of the atlas through the previous
  frame's lookups. With one bounce the floor's reflection of a wall mirror was
  the mirror's bare metal, a gold smear.
- The first `SETTLE_FRAMES` (2) frames' reflections are provisional: drawn
  again before they are kept, and never passed on to another mirror. Their
  colours can be far off while programs compile and textures upload, and
  mirrors facing each other kept passing that on.
- A still scene: the pass asks the context for another frame while any mirror
  in view has a provisional reflection, none, one off by more than a texel, or
  a view that left out a mirror now drawn. Reaching `interval` does not ask.
  Without this a context that draws only on change showed the settling frames'
  reflections, or the probe, for good.
- The schedule takes mirrors with no usable reflection before those merely
  due, and halves a mirror too large for the texel budget in its turn; set
  aside until the end, the largest mirror (a floor) lost every view to smaller
  ones and was never drawn.
- A frame's texel budget is half the atlas (`reflectionatlas.FILL`): shelves
  of power-of-two heights do not pack the whole of it. When drawn tiles still
  do not fit, kept tiles give up their room, then drawn ones are halved.
- A mirror's roughness is its factor times the mean of its roughness map. A
  textured glTF material has factor 1, and was judged too rough to reflect.
- The GPU timer runs whenever mirror views are drawn, so the overlay and
  telemetry always have the number; the millisecond target only reads it.
- `planarReflections` is read every frame (the driver's support once), so a
  settings screen can switch it; `waterReflection` was read once.

Found on the way and fixed: `OPENGLCONTEXT_MULTIVIEW` was never read by
`requested_strategy` unless the field had been set; Blender's single-precision
float properties wrote tags like `0.6000000238418579` (the lakeside demo is
rebuilt from its script).

Limits found: where a mirror reflects nothing it shows the environment probe,
which is procedural unless the scene has an HDR or cubemap sky; a VRML97
`Background`'s colours do not reach it (a RUNTIME-IBL question). Metals that
are not flat still reflect only the probe.

Step 8: the billboard, clump, near-mesh and ground programs route through the
view table (`_multiview_inc.glsl`, `routeToView`), measure fades and fog from
each fragment's own view (`toViewer`), and are compiled per shared draw by
`instancedgl.ViewPrograms`; an instanced draw is multiplied by
`instancedgl.view_copies`. They are `multiviewShared`, so they share editor
views and mirror views alike, and the separate-view cap now covers particles
and text. Departure: in a shared draw every card faces the *active* view's
camera, under both strategies, since the geometry strategy's vertex stage does
not know its view; for a mirror view that is the mirror image of the card the
viewer sees, which is right. The choice of which trees are meshes and which are
cards stays the active camera's, as planned. Found on the way:
`vertex_outputs` missed outputs declared several to a line, and the ground
culled by counter-clockwise winding even when seen in a mirror, so water had
never reflected terrain's ground.

Still open: the visual-regression baselines, checked by preflight on the main
checkout once this is merged.


## After use in oglc-mirrors (2026-09-24)

Found by recording every frame of the demo with pyopengl-video and logging the
plan beside each frame:

- Flashing between mirror and matte at a still camera: the packer's shelves
  took only tiles of their own height class, so a tile that shrank a few texels
  into the next class found no room beside the floor's tall tile, and a drawn
  tile then evicted the kept ones, which evicted it the frame after. The packer
  now puts a shorter tile beside taller ones, and tiles that do not all fit are
  placed by screen area times priority, so the same mirrors keep their tiles.
- Stutter while turning: a shared draw's programs were compiled for each new
  count of views, about 120 ms each. They are compiled for a power of two of
  views, and the mirror views ask for their whole budget once.
- A mirror seen in a mirror read the reflection planned for the main view: the
  probe when no view saw it, and a tile cropped to the main view's rectangle,
  whose edge showed as the camera turned. Every mirror in view now has a
  `ReflectedView` of its own, the mirrors inside it are found by testing only
  the scene's mirrors against its frustum, and each chain of mirrors is planned
  from its own camera, `reflectionBounces` deep (2 by default). A nested mirror
  is planned from its parent's projection before the oblique near plane: two
  oblique steps left a far plane that clipped everything the second mirror
  showed. The floor-and-wall tests had asserted the old, wrong image, and now
  stand the box where the double reflection sees it.
- A view drawn without a nested reflection that is not yet scheduled shows the
  probe for it and is drawn again once it arrives (`drawn_without`), in place
  of waiting for it: under a short budget the wait never ended.
- `PlanarReflector.reflectance` (0.97; water 1.0) scales what a mirror
  reflects, which tells a mirror from an opening onto the same room.

Still open: the fps-adaptive IBL drops to `analytic` for a hundred frames when
a heavy frame dips under 45 fps, which changes every glossy surface at once.
