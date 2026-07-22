# Ray-Cast Picking for Large Scenes

**Status:** Planned

**Builds on / supersedes:** [SELECTION-OPTIMIZATION.md](SELECTION-OPTIMIZATION.md) — this is
the realization of its deferred *Phase 3.1 (Hierarchical Selection with BVH)*, extended into a
full CPU ray-cast pipeline. The MRT selection buffer from Phase 2 is **kept** as the guaranteed
fallback, not replaced.

## Goal

Provide picking that is fast enough to run **on every `mousemove`, forever, on much larger scenes**
than the current O(N) selection path can handle. The pipeline must support:

- a **rough** mode (ray against object bounding boxes only), and
- a **fine** mode (precise contact point / normal), where
- geometry can **delegate to itself** for an efficient exact test (a `Sphere` does an analytic
  ray/sphere solve; a mesh does ray/triangle over a cached triangle BVH), and
- the existing **selection-buffer render always remains available** as a correctness backstop for
  geometry that has no CPU intersection (NURBS, `Text`, `Extrusion`) or when the caller forces it.

## Why the current path does not scale

The selection subsystem today is solid but has two structural limits for large scenes (see
[selection.py](../OpenGLContext/passes/selection.py)):

1. **Broad phase is O(N) per pick.** `_computeScreenSpaceBBoxes`
   ([selection.py:768](../OpenGLContext/passes/selection.py#L768)) projects *every* object's
   bounding-box corners each frame, and `shaderSelectRenderOptimized`
   ([selection.py:608](../OpenGLContext/passes/selection.py#L608)) then does a linear point-in-rect
   scan over all of them. There is **no spatial index** anywhere in the codebase (confirmed: no BVH,
   octree, kd-tree, or grid; culling in `frustumVisibilityFilter`,
   [_flat.py:792](../OpenGLContext/passes/_flat.py#L792), is also a linear scan).
2. **Every precise hit costs GPU work + a synchronous readback.** Even the MRT fast path
   (`processPickEventsFromBuffer`, [selection.py:526](../OpenGLContext/passes/selection.py#L526)) is
   one-frame-latent and still does a `glReadPixels` per pick point; the per-pick FBO fallback stalls
   the pipeline. Neither does any CPU-side geometric reasoning, so there is no cheap "rough" answer
   and no way to get a contact point/normal without a render.

There are **no per-geometry ray/intersect methods** in the tree today — all hit testing is GPU
render + pixel readback.

## What we keep

The design layers on top of existing structure rather than rewriting it:

- **Record shape.** `renderSet()` ([_flat.py:759](../OpenGLContext/passes/_flat.py#L759)) already
  yields `(sortKey, mvmatrix, tmatrix, bvolume, path)` per renderable. `tmatrix` is the local→world
  transform, `bvolume` is a **local-space** `AABoundingBox`, `path` is the `NodePath`. That is
  exactly the input a BVH and a narrow phase need.
- **Incremental scene observation.** `FlatPass` is an `SGObserver`
  ([_flat.py:61](../OpenGLContext/passes/_flat.py#L61)) that maintains a flat `self.paths` and is
  already notified of structural change via `onChildAdd` / `onChildRemove` / `onSwitchChange`
  ([_flat.py:131-147](../OpenGLContext/passes/_flat.py#L131)). This is where a cached BVH is
  invalidated.
- **Bounding volumes.** `AABoundingBox` ([boundingvolume.py:225](../OpenGLContext/scenegraph/boundingvolume.py#L225))
  gives `center`/`size` and lazy 8-corner `getPoints()`, and volumes are cache-invalidated on field
  change via `cacheVolume`/`getCachedVolume`.
- **Event outputs and fallbacks.** The `MouseEvent` contract (`objectPaths`, `viewCoordinate`,
  `worldCoordinate`, matrices, `unproject()`, [mouseevents.py](../OpenGLContext/events/mouseevents.py)),
  the MRT buffer, and the legacy `GL_SELECT` name-stack path
  (`SelectRenderPass`, [renderpass.py:395](../OpenGLContext/passes/renderpass.py#L395)) all stay. The
  new path produces the **same** event fields, so `mousein`/`mouseout`, `TouchSensor`, and
  `MouseOver` are untouched.

## Tier −1 — The gate: do nothing when nothing is listening

The cheapest pick is the one that never runs. Most frames have **no** pick-relevant handler
registered, and on-move scanning is only needed when a `mousemove`/`mousein`/`mouseout` handler
exists (rare). The gate makes "no handler" cost *zero* — no ray, no BVH, and crucially **no MRT
id-buffer rendering** during the forward pass.

Partial machinery exists and is generalized:

- `hasMouseMoveHandlers()` ([context.py:781](../OpenGLContext/context.py#L781)) already asks each
  move manager `hasReceivers()`. Generalize to **`hasPickHandlers()`**, covering every pick event
  type (`mousebutton`, `mousemove`, `mousein`, `mouseout`, and TouchSensor's button handlers), and a
  cheaper **`hasMoveHandlers()`** / **`hasClickHandlers()`** split.
- `_optimizePickEvents` ([selection.py:466](../OpenGLContext/passes/selection.py#L466)) already drops
  `mousemove` events when no move handlers exist. Extend it to also drop `mousebutton` events when no
  click handler is registered.

Gate points:

1. **Ingress** — `addPickEvent` ([context.py:761](../OpenGLContext/context.py#L761)), already gated
   by `pickEnabled`, also returns early when `not hasPickHandlers()`. The event never enters the
   queue, so `triggerPick()` does no work.
2. **Per-frame MRT** — the id-buffer is written every forward frame today. Gate `id_map` creation
   (`_flat.py` around [line 942](../OpenGLContext/passes/_flat.py#L942)) on
   `hasPickHandlers()` (cached per frame, like the existing `_has_mousemove_handlers` reset at
   [_flat.py:861](../OpenGLContext/passes/_flat.py#L861)), so a scene with no pick handlers pays no
   MRT cost at all.
3. **Move vs. click** — on-move scanning runs only if `hasMoveHandlers()`; click scanning only if
   `hasClickHandlers()`. A drag with only a click handler still skips per-move picking.

**Registration-driven enable/disable.** Because managers report live receiver sets, the gate is
re-read each frame (cheap boolean) rather than requiring explicit enable/disable calls — registering
or deregistering a handler flips the gate automatically. Showing a HUD (which registers its widgets'
handlers) turns picking on; hiding it (deregistering) turns picking back off with no bookkeeping.

## HUD-only interaction and the 2D clickable layer

A common configuration — console-style games — has **no world picking at all**: the world is driven
by simulation, and the only clickable things are HUD/overlay widgets. For this, world ray/BVH work
should be entirely bypassed and replaced by a trivial 2D test.

- **`worldPickEnabled` flag** (default `True`). When `False`, Tiers 0–3 (ray, BVH, geometry, buffer)
  never run for world geometry; only the clickable layer is consulted. Combined with the gate, a
  hidden HUD means *zero* pick work; a shown HUD means only 2D lookups.
- **Clickable layer.** The overlay/HUD renders in the existing overlay pass. A `ClickableLayer` holds
  a screen-space map from pixel → widget: either a list of axis-aligned regions (buttons/panels) hit-
  tested directly in 2D, or, for pixel-accurate irregular widgets, a small id-rendered 2D buffer
  (the same MRT id trick, but overlay-only and overlay-resolution). A pick point resolves in O(1)–
  O(#regions) with no unproject, no depth, no 3D math.
- **Composition.** The pick driver consults the clickable layer **first** (it is nearest the camera,
  always on top); a hit there consumes the event. Only if the layer misses *and* `worldPickEnabled`
  does it fall through to Tier 0. This also gives correct "HUD occludes world" behavior for free.

New `OpenGLContext/scenegraph/clickablelayer.py` (or an overlay-node method); widgets register
regions on show and drop them on hide, which also drives the Tier −1 gate.

## Architecture — three tiers plus a fallback

The gate (Tier −1) and the HUD layer sit in front of everything below; the three world tiers only run
when a world pick is actually needed.

```
mousemove/click  ─▶  Tier −1: GATE — any handler registered for this event kind?
                        │   no ─▶ drop event, no MRT, done (the common case)
                        │   yes
                        ▼
                     HUD: clickable-layer 2D hit-test (nearest, always on top)
                        │   hit ─▶ consume, done
                        │   miss and worldPickEnabled
                        ▼
                     Tier 0: build world-space Ray (pick point → near/far unproject)
                        │
                        ▼
                     Tier 1: BROAD PHASE — ray vs. cached world-AABB BVH
                        │      → candidates ordered by box-entry distance t_enter
                        │
                        ├── pickMode == 'rough' ─▶ return nearest box hit (no narrow phase)
                        │
                        ▼
                     Tier 2: NARROW PHASE — for each candidate, front-to-back:
                        │      transform ray into local space (inverse tmatrix)
                        │      geometry.intersect(local_ray, tol) → t, point, normal
                        │      keep best; stop when t_enter(next) ≥ best_t
                        │
                        ├── geometry has no intersect() ──┐
                        ▼                                  ▼
                     resolved on CPU                   Tier 3: FALLBACK
                     (set event fields directly)       selection buffer / GL_SELECT
                                                        for the unresolved candidates
```

The tiers are independently useful: Tier 1 alone is the "rough" mode; Tier 1+2 is the "fine" mode;
Tier 3 guarantees no regression in coverage.

### Tier 0 — Ray construction

New `OpenGLContext/scenegraph/ray.py`.

```python
class Ray:
    origin      # world-space point, float64 (3,)
    direction   # normalized world-space vector (3,)
    inv_dir     # 1/direction, precomputed for slab tests (inf where dir==0)
    t_min, t_max
    cone_radius # angular half-width in radians (0 for an infinitely thin ray)
```

Built from a pick point by unprojecting the near and far plane. The pass's `self.matrix` is the
camera **view** matrix (world→eye), so `gluUnProject(x, y, {0,1}, self.matrix, self.projection, vp)`
returns **world** coordinates directly — the same call `MouseEvent.unproject`
([mouseevents.py:108](../OpenGLContext/events/mouseevents.py#L108)) already uses. `cone_radius` is
derived from a configurable pixel tolerance and the vertical FOV so that zero-area geometry (points,
lines) has a finite pick target (see Tier 2).

### Tier 1 — Broad phase: a cached world-space BVH

New `OpenGLContext/scenegraph/bvh.py`.

- **Contents.** One leaf per `toRender` record, storing the record index and the record's
  **world-space** AABB (transform `bvolume.getPoints()` by `tmatrix`, then min/max — the same
  transform `greatestDepth`/`_computeScreenSpaceBBoxes` already do).
- **Build.** Median/SAH split over leaf-centroid coordinates, `O(N log N)`. Interior nodes store a
  merged AABB and child links; leaves store record indices.
- **Query.** Ray vs. node AABB via the slab test using `inv_dir`; descend near-child-first pushing
  the far child, yielding candidate record indices **ordered by `t_enter`**. A `rough` query returns
  the first leaf hit; a `fine` query streams candidates to Tier 2.
- **Caching & invalidation** — the crux of "much larger scenes":
  - The BVH is cached on the `FlatPass` instance.
  - **Structural change** (`onChildAdd`/`onChildRemove`/`onSwitchChange`) sets a `dirty` flag →
    rebuild on next pick.
  - **Transform-only animation** (same leaf set, changed `tmatrix` values) triggers a **refit**:
    recompute leaf AABBs and propagate merged AABBs bottom-up in stored node order, `O(N)`, no
    re-split. A cheap fingerprint (leaf count + a hash/sum of `tmatrix` values) distinguishes
    "refit" from "rebuild".
  - Picking reads a possibly one-frame-stale BVH (built from last frame's `toRender`), which matches
    the one-frame latency the MRT buffer already accepts.
- **Degfensive fallback.** If a record's bounding volume is `UnboundedVolume` or absent, it is marked
  *always-candidate* and always handed to the narrow phase / fallback (never culled).

Numbers this targets: broad phase from `O(N)` → `O(log N)` per pick, so 10⁴–10⁵ objects stay
interactive where the current scan does not (realizes the SELECTION-OPTIMIZATION §3.1 target).

### Tier 2 — Narrow phase: geometry-delegated intersection

**Precise intersection is a method on the geometry node** (the chosen API): each geometry owns and
can override its own test, matching "delegate to a piece of geometry." The ray is transformed into
the node's **local** space once (`inverse(tmatrix)`, cached alongside `tmatrix`) so every geometry
works in its own coordinate frame; the returned point/normal are transformed back to world.

```python
class <Geometry>:
    def intersect(self, ray, tol=None):
        """Return an Intersection(t, point, normal) in LOCAL space, or None.

        ray  -- a Ray already transformed into this node's local coordinates
        tol  -- pick tolerance (cone) for zero-area geometry; may be ignored
        """
```

`intersect()` returns a local-space hit (t, point, and — per the `PickRequest` — normal, uv, tangent,
color, primitive index, barycentric); the driver transforms point/normal to world and fills `path`,
producing the `PickResult` described under **Hit attributes**. Front-to-back driver keeps the nearest
hit and stops descending candidates once `t_enter(next) ≥ best_t`, because a nearer *box* can contain
a farther *surface*.

Coverage for v1 (all three classes requested):

| Geometry | Method | File |
|---|---|---|
| `Sphere` | analytic ray/sphere (quadratic in local space; local sphere is `radius`-centered) | [quadrics.py](../OpenGLContext/scenegraph/quadrics.py) |
| `Box` | ray/AABB slab test against `size` | [box.py](../OpenGLContext/scenegraph/box.py) |
| `Cylinder`, `Cone` | analytic infinite-body solve + cap planes, clamped to `height` | [quadrics.py](../OpenGLContext/scenegraph/quadrics.py) |
| `IndexedFaceSet`, `IndexedPolygons` | **Möller–Trumbore** ray/triangle, accelerated by a per-mesh **triangle BVH** | [indexedfaceset.py](../OpenGLContext/scenegraph/indexedfaceset.py), [indexedpolygons.py](../OpenGLContext/scenegraph/indexedpolygons.py) |
| `PointSet`, `IndexedLineSet` | **cone/tolerance** test: nearest point/segment within `tan(cone_radius)·t` of the ray | [pointset.py](../OpenGLContext/scenegraph/pointset.py), [indexedlineset.py](../OpenGLContext/scenegraph/indexedlineset.py) |
| everything else (NURBS, `Text`, `Extrusion`, `Teapot`, PBR mesh) | *no `intersect`* → Tier 3 fallback | — |

Shared helpers (the actual math, vectorized with the project's `arrays`) live in
`OpenGLContext/scenegraph/intersection.py` so node methods stay thin and testable without GL:
`ray_sphere`, `ray_aabb`, `ray_cylinder`, `ray_cone`, `ray_triangles` (batched), `ray_point`,
`ray_segment`.

**Per-mesh triangle BVH.** For indexed meshes the expensive part is triangle count, not object count.
Build a triangle BVH over the coordinate array on first pick and cache it through the existing
`cache.CACHE` keyed on the coordinate node's `point` field (same dependency mechanism as
`volumeFromCoordinate`, [boundingvolume.py:372](../OpenGLContext/scenegraph/boundingvolume.py#L372)),
so it invalidates automatically when vertices change. `ray_triangles` runs Möller–Trumbore over the
candidate leaf's triangle slice as a single batched array op.

**Zero-area geometry.** Points and lines never satisfy an exact ray hit, so `intersect` uses the
ray's `cone_radius`: a vertex/segment is a hit when its perpendicular distance to the ray is within
`tan(cone_radius)·t` (a world-space radius that grows with depth, matching a constant pixel
tolerance). The nearest qualifying primitive wins.

### Tier 3 — Fallback (always available)

If a candidate's geometry lacks `intersect()`, or the caller sets `pickMode='buffer'`, or the CPU
path yields nothing and a definitive answer is required, the driver falls back to the existing
selection path for the unresolved candidates:

- shader profile → `shaderSelectRenderOptimized` / MRT
  ([selection.py:608](../OpenGLContext/passes/selection.py#L608), [selection.py:526](../OpenGLContext/passes/selection.py#L526)),
- compatibility profile → `selectRender` / `SelectRenderPass`
  ([renderpass.py:395](../OpenGLContext/passes/renderpass.py#L395)).

Because the BVH broad phase can hand the buffer path a *tiny* candidate set instead of the whole
scene, even the fallback gets faster on large scenes.

## Hit attributes — surface normal, UV, and painting

Some callers (surface painting, decal placement, measurement) need more than *which* object — they
need the **surface data at the contact point**: geometric and shading normal, texture UV, tangent,
vertex color, and the primitive (triangle) hit. A **`PickRequest`** declares which of these it wants,
so neither path computes or allocates for data nobody uses (a plain selection asks for `point` only).

Two sources, matching the two-tier structure:

**CPU narrow phase — analytic / barycentric (exact, no GPU, zero latency).**
- Analytic primitives compute normal and UV in closed form at the hit: `Sphere` → `normal =
  normalize(p)`, UV from the same spherical parameterization the mesh uses
  ([quadrics.py](../OpenGLContext/scenegraph/quadrics.py): `u = atan2(x,z)/2π`, `v = acos(y/r)/π`);
  `Box` → face normal + planar UV; `Cylinder`/`Cone` → side vs. cap normal, wrapped/planar UV.
- Triangle meshes get it for free: Möller–Trumbore already yields **barycentric** `(u,v,w)`, so any
  per-vertex attribute interpolates directly — `attr = u·A + v·B + w·C` over the triangle's `normal`,
  `texCoord`, `color`, and tangent arrays. Exact for the geometry as authored.
- Helper `interpolate_triangle(bary, tri_indices, attr_array)` in `intersection.py`; `intersect()`
  fills only the requested fields.

**GPU buffer — an attribute G-buffer (matches the rendered image, any geometry).**
- Extend the MRT: alongside color (attach0) and id (attach1) the forward shaders optionally write
  **world-space normal** and **UV** (depth already exists). A picking-specialized partial G-buffer,
  gated by a shader flag so the extra attachments and bandwidth exist only when attribute picking is
  on.
- A pick reads id + normal + uv + depth at the sample pixel. This is the right source when the
  *rasterized* surface differs from the CPU geometry — shader displacement, `KHR_texture_transform`,
  alpha-tested cutouts — i.e. when painting must match exactly what the user sees.
- Bonus for brushes: a brush footprint is a **rectangle** of pixels, so one sub-rect readback returns
  normal+uv+id for the whole stamp in a single transfer — far cheaper than N ray casts.

Result carries the union:

```python
PickResult(path, worldPoint, depth, distance,
           geometricNormal, shadingNormal, uv, tangent, color,
           primitiveIndex, barycentric, geometry, source)   # source ∈ {raycast, buffer}
```

Unrequested/unavailable fields are `None`. The event API gains `event.surfaceNormal` and
`event.textureCoordinate` (beside the existing `worldCoordinate`) so painting code reads them
directly.

## Async, pipelined multi-sample readback

Synchronous `glReadPixels` (what `read_pixel` does today,
[selection.py:385](../OpenGLContext/passes/selection.py#L385)) stalls the CPU on the GPU — fine for
one click, wrong for painting that samples every frame. The buffer path becomes **non-blocking** and
**batched**.

**PBO ring + fence.** Read into a Pixel Buffer Object instead of client memory: `glReadPixels` into a
`GL_PIXEL_PACK_BUFFER` returns immediately (async DMA). A `glFenceSync` records when the copy
completes; a later frame polls it with `glClientWaitSync(…, 0)` (non-blocking) and only then maps the
PBO. Results land 1–2 frames late — invisible for on-move painting (~16 ms) — but throughput is
independent of sample count and never stalls.

**Batch N samples.** The driver accumulates the frame's sample points (mouse trail, brush pattern,
multi-touch) and submits them together after the forward pass: scattered points → N tiny async reads
into one packed PBO; a contiguous brush → one sub-rect read. One fence covers the batch.

**Don't stall the next frame — ring the buffer, don't gate the clear.** The concern is real: the next
frame clears the id/attribute buffer before the reads drain. The literal fix is a fence that makes the
next frame's clear wait (`glWaitSync`, a GPU-side wait) — correct, but it reintroduces a stall. The
better structure is a **ring of id/attribute FBOs** (2–3 deep): frame N writes slot N while the reads
of frame N−1 drain from slot N−1, so no clear ever waits. The fence then only tells us *when a slot's
PBO is safe to map*, not when rendering may proceed. Recommend the ring; keep the fence-gated-clear as
the degenerate one-slot fallback.

**Per-frame lifecycle (async mode):**
1. *Frame top:* poll pending fences; for each signaled batch, map its PBO, decode id/normal/uv/depth
   per sample, build events, `ProcessEvent`, recycle the PBO.
2. Render the forward pass into this frame's ring slot (id + optional attribute attachments).
3. Submit this frame's queued samples: `glReadBuffer(attachment)` → `glReadPixels` into a fresh PBO
   (async), once per attachment.
4. `glFenceSync`; store `(batch, pbo(s), fence)`.
5. Advance the ring slot; the next frame clears a *different* slot.

**Interplay with the CPU path.** CPU ray picking has no GPU round-trip, so it is already non-blocking
and zero-latency — the primary path for painting on CPU-intersectable geometry when authored-geometry
interpolation suffices. The async PBO path is for (a) geometry with no CPU `intersect`, (b)
shader-accurate attributes, and (c) wide brushes where one rect read beats many ray casts. `pickSource`
chooses; `auto` uses raycast when the geometry supports it and the buffer otherwise.

## Integration

New mixin `RayPickMixin` in `OpenGLContext/passes/raypick.py`, mixed into `FlatPass` alongside
`SelectionMixin` ([_flat.py:182](../OpenGLContext/passes/_flat.py#L182)). The pick dispatch in
`FlatPass.Render` ([_flat.py:882](../OpenGLContext/passes/_flat.py#L882)) gains a front-end:

```
events = context.getPickEvents()
if events and pick uses raycast:
    unresolved = self.rayPickEvents(mode, toRender, events)   # Tiers 0–2
    if unresolved:
        <existing buffer / GL_SELECT path on `unresolved` only>   # Tier 3
else:
    <existing path unchanged>
```

`rayPickEvents` fills, per resolved event: `objectPaths` (nearest path; full front-to-back list when
`event.processMorePaths` is set), `worldCoordinate` (the exact hit point — so `unproject()` returns
without a GL round-trip), `viewCoordinate` (via `project()` for legacy consumers), and the matrices/
viewport. Output is byte-for-byte contract-compatible with the buffer path, so downstream event
dispatch ([mouseevents.py:274](../OpenGLContext/events/mouseevents.py#L274)) is unchanged.

## Configuration

On `contextDefinition` (joining the existing `pickEnabled`, `debugSelection`):

| Flag | Values | Default | Meaning |
|---|---|---|---|
| `pickMode` | `auto` \| `raycast` \| `rough` \| `buffer` | `auto` | `auto` = raycast + buffer fallback; `rough` = BVH box hits only; `buffer` = force the existing path |
| `pickTolerancePixels` | float | `4.0` | pixel radius → `Ray.cone_radius`, for point/line picking and near-miss forgiveness |
| `worldPickEnabled` | bool | `True` | when `False`, skip all world tiers; only the HUD clickable layer is consulted (console-game HUD-only mode) |
| `pickAttributes` | set | `{point}` | surface data to resolve at the hit — any of `point/normal/uv/tangent/color`; extra attrs enable CPU interpolation and the GPU attribute G-buffer |
| `pickSource` | `auto` \| `raycast` \| `buffer` | `auto` | force the attribute source; `auto` = raycast where the geometry supports it, else buffer |
| `pickAsync` | bool | `True` | non-blocking PBO readback for the buffer path (1–2 frame latency); `False` = synchronous `glReadPixels` |
| `pickLatencyFrames` | int | `2` | id/attribute FBO ring depth for async readback |
| `debugPick` | bool | `False` | draw the ray, candidate boxes, and hit point/normal (mirrors `debugSelection`/`debugBBox`) |

`auto` keeps today's behavior for any geometry without `intersect()` and turns on the fast CPU path
where it is available — safe to enable by default.

## New / modified files

**New**
- `OpenGLContext/scenegraph/ray.py` — `Ray`, `Intersection`.
- `OpenGLContext/scenegraph/intersection.py` — vectorized ray/primitive math (no GL).
- `OpenGLContext/scenegraph/bvh.py` — object BVH + reusable triangle BVH.
- `OpenGLContext/scenegraph/clickablelayer.py` — 2D screen-space HUD hit-test.
- `OpenGLContext/passes/raypick.py` — `RayPickMixin` (driver, front-to-back, fallback handoff).
- `OpenGLContext/passes/asyncpick.py` — PBO ring + fences for non-blocking batched readback.
- `PickRequest` / `PickResult` (in `ray.py` or a `pickresult.py`) — requested attributes and the
  resolved surface sample.
- tests under `tests/` (below).

**Modified**
- `OpenGLContext/context.py` — generalize `hasMouseMoveHandlers()` → `hasPickHandlers()` /
  `hasMoveHandlers()` / `hasClickHandlers()`; gate `addPickEvent` on them.
- `OpenGLContext/passes/selection.py` — extend `_optimizePickEvents` to drop clicks with no click
  handler; gate per-frame `id_map`/MRT on `hasPickHandlers()`.
- `OpenGLContext/passes/_flat.py` — mix in `RayPickMixin`; BVH cache + invalidation hooks in the
  `SGObserver` signal handlers; pick dispatch front-end; per-frame gate.
- `quadrics.py`, `box.py`, `indexedfaceset.py`, `indexedpolygons.py`, `pointset.py`,
  `indexedlineset.py` — add `intersect()` (returns normal/uv/etc. per `PickRequest`).
- `OpenGLContext/passes/selection.py` — attribute attachments in `SelectionBufferFBO`; PBO ring.
- `OpenGLContext/shaders/vrml97_lighting.frag` / `vrml97_unlit.frag` / `pbr.frag` — optional
  world-normal + UV MRT outputs, gated by a compile/uniform flag.
- `OpenGLContext/contextdefinition.py` (or wherever `pickEnabled`/`debugSelection` live) — new flags
  (`pickMode`, `pickTolerancePixels`, `worldPickEnabled`, `debugPick`).
- `tests/point_and_click.py` — **already fixed**: was reading the dead `getNameStack()` API (only the
  obsolete `GL_SELECT` pass fills it); now reads `getObjectPaths()` like `selectrendermode.py`.
- `plans/PROJECT-PLAN.md` — summary-table entry.

## Testing strategy

Math and structure are pure-CPU, so most tests need **no GL context** (fast, deterministic):

1. **Primitive math** (`tests/test_intersection.py`): ray/sphere, ray/box, ray/cylinder, ray/cone,
   ray/triangle, ray/point, ray/segment — analytic cases with known answers (hit, miss, tangent,
   grazing, behind-origin, inside-origin), plus t/point/normal assertions.
2. **BVH** (`tests/test_bvh.py`): build + ray query on random scenes vs. a brute-force reference
   (every ray returns the same nearest record); refit-after-transform equals rebuild; invalidation
   on add/remove/switch.
3. **Narrow-phase parity** (`tests/test_raypick_parity.py`): on the `point_and_click.py`
   ([tests/point_and_click.py](../tests/point_and_click.py)) sphere scene, a grid of pick points
   resolved by ray-cast agrees with the selection-buffer path on which object (and roughly where).
4. **Fallback** : a scene mixing a `Sphere` (has `intersect`) and a `Text`/NURBS node (no
   `intersect`) confirms the unresolved node still gets picked via the buffer, and that `pickMode`
   selects the path.
5. **Performance** (`tests/test_raypick_benchmark.py`): N = 10⁴ objects, assert per-pick CPU time
   stays sub-frame and that broad phase is sub-linear (time vs. N grows ~log).
6. **Hit attributes** (`tests/test_pick_attributes.py`, pure-CPU): analytic sphere/box normal+UV at
   known points; barycentric interpolation on a hand-built triangle equals the closed-form value at
   vertices, edges, and centroid; `PickRequest` gating leaves unrequested fields `None`.
7. **Async readback** (GL, subprocess): batched N-sample submit returns the same ids/attributes as the
   synchronous path, one frame later; the ring never blocks the frame clear; fence poll is
   non-blocking. Falls back cleanly when PBO/fence extensions are unavailable.

Per the repo's testing rules, tests must exercise the real code paths with realistic inputs and
assert on outputs; GL-dependent pieces run in subprocesses or against mock modes.

## Phasing

| Phase | Deliverable |
|---|---|
| **0** | **Tier −1 gate** + demo fix. Generalize `hasPickHandlers`/`hasMoveHandlers`/`hasClickHandlers`; gate `addPickEvent` and per-frame MRT on them; extend `_optimizePickEvents` to drop click events with no click handler. Pure-CPU, no new GL. Highest value-per-line: makes the no-handler common case free and removes per-frame MRT cost. (`point_and_click.py` API fix already landed.) |
| **1** | `ray.py` + `intersection.py` + analytic primitive `intersect()` (Sphere/Box/Cylinder/Cone) + **brute-force** broad phase + Tier-3 fallback wiring + tests 1,3,4. Delivers the delegation protocol and correct picking, reviewable before the BVH. |
| **2** | `bvh.py` object BVH with cache/refit/invalidation, swapped in behind the same driver + tests 2,5. Delivers the scale target. |
| **3** | Indexed-mesh `intersect()` + per-mesh triangle BVH; `PointSet`/`IndexedLineSet` cone tolerance. Delivers precise picking on parthenon-scale meshes and zero-area geometry. |
| **4** | **HUD 2D clickable layer** + `worldPickEnabled`. Independent of the world tiers; delivers the console-game HUD-only mode and correct HUD-occludes-world behavior. Can land any time after Phase 0. |
| **5** | **Hit attributes (CPU)**: analytic normal/UV for primitives + barycentric normal/uv/tangent/color for meshes in `intersect()`; `PickRequest`/`PickResult`; `event.surfaceNormal`/`event.textureCoordinate`. Unblocks surface painting on CPU-intersectable geometry. Tests: interpolation vs. known values. |
| **6** | **Hit attributes (GPU)**: optional normal+UV MRT attachments in the forward shaders; buffer-path attribute reads + brush sub-rect reads. Shader-accurate attributes for any rendered geometry. |
| **7** | **Async pipelined readback**: PBO ring + fences, batched N-sample submit, `pickAsync`/`pickLatencyFrames`. Makes buffer-path picking non-blocking for on-move painting. (Supersedes SELECTION-OPTIMIZATION §3.2.) |
| **8** (opt.) | Refinements: `debugPick` visualization, `processMorePaths` full-list ordering, oriented boxes / bounding spheres if AABBs prove too loose. |

## Open questions / risks

- **Row-vector vs. column-major matrices.** The tree uses row-vector `point·matrix` convention while
  `gluUnProject`/`gluProject` are column-major; the ray build reuses the existing (working)
  `unproject` call, but the local-space ray transform must use `inverse(tmatrix)` in the row-vector
  convention consistently (this exact mismatch already bit the glTF bounds code — see
  GLTF-COMPLETE-SUPPORT.md). Covered by test 3 (parity) as the guard.
- **AABB looseness.** Local AABBs for rotated/elongated geometry over-select candidates; acceptable
  because the narrow phase rejects them, but Phase 4 may add OBB/bounding-sphere leaves if the
  candidate count is high in practice.
- **Instanced / shared coordinate nodes.** The `volumeFromCoordinate` pathological case
  ([boundingvolume.py:391](../OpenGLContext/scenegraph/boundingvolume.py#L391)) — many shapes
  indexing one giant coordinate node — also weakens a triangle BVH; note it, don't solve it in v1.
- **One-frame staleness.** BVH and MRT are both one frame behind; consistent and already accepted,
  but worth stating for fast-animating scenes.

## References

- [SELECTION-OPTIMIZATION.md](SELECTION-OPTIMIZATION.md) / [SELECTION-OPTIMIZATION-RESULTS.md](SELECTION-OPTIMIZATION-RESULTS.md) — the MRT buffer this builds on, and its BVH §3.1 note.
- Möller & Trumbore, *Fast, Minimum Storage Ray/Triangle Intersection* (1997).
- Williams et al., *An Efficient and Robust Ray-Box Intersection Algorithm* (slab test with `inv_dir`).
