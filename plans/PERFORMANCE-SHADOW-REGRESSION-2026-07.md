# Parthenon Shadow-Pass Performance Regression (2026-07)

**Status:** R1–R5 shipped (shadow-CPU); real-world root cause corrected (see §7).
**Symptom:** `oglc-gltf ../../parthenon/parthenon.glb` dropped from ~60 fps to ~20 fps while walking around.
**Verdict:** The `unix.py` GLX/EGL probe is exonerated (0.02 %). R1–R5 cut the
shadow-pass **CPU** substantially, but **that was not the real-world frame-rate
wall** — see §7 for the corrected, on-display root cause (the viewer pinning the
fps-adaptive shadow cascades, plus shared-GPU load and the FPS overlay). Read §7
first: it supersedes the "recover most of the lost 40 fps" prediction in §5.

---

## 1. How this was measured

Profiled the live GLFW window (real NVIDIA GL in this container), not a headless
proxy, so the numbers reflect the actual render loop:

```bash
py-spy record -o profile.json --format speedscope --rate 250 --subprocesses -- \
    oglc-gltf parthenon/parthenon.glb --turntable --size 800x600
```

6010 samples over 23.8 s on the main thread. Two independent instrumentation
passes (call-count wrappers on `ShadowMapMixin`) confirmed the per-frame work.

`--turntable` was used to force continuous redraws for a clean steady-state
sample. The user's real complaint is **walking around** (camera moves, scene
static), which as shown below is an even better fit for the caching remedies than
the turntable case.

---

## 2. The evidence

### 2.1 The platform probe is NOT the cause

The `a0be8048` commit ("UNIX glx/egl selected by using a context-level probe")
warned it "has a run-time cost". Measured inclusive time in the profile:

| Frame / function | Inclusive % of frame |
|---|---|
| `platform.GetCurrentContext` (the new probe) | **0.02 %** |
| `getExtensionProcedure` / `glXGetCurrentContext` / `eglGetCurrentContext` | 0.00 % |

`getExtensionProcedure` resolves each GL entry point **once** and caches it, and
`_active_api` short-circuits after the first probe. The probe is real but
irrelevant to frame rate. **No action needed for performance** (it can stay as-is).

### 2.2 The shadow pass dominates the frame

Inclusive time, main thread:

| Function | Inclusive % of frame |
|---|---|
| `OnDraw` → `Render` (whole frame) | ~90 % |
| **`renderShadowMaps`** | **68 %** |
| `build_instance_groups` | 13 % |
| `_cullOccluders` | 11.8 % |
| `draw_instanced_mesh` | 4.9 % |

Self-time (CPU actually burned in Python), by file:

| File | Self % | Hot functions |
|---|---|---|
| `passes/shadowmixin.py` | **24.2 %** | `_casterWorldAABBCorners` 10.3 %, `_worldPointsFromRecords` 4.8 %, `_renderDepthGroup`, `_cullOccluders` |
| `passes/instancing.py` | 13.3 % | `draw_instanced_mesh`, `build_instance_groups`, `pack_instance_buffer`, `_material_texture_ids` |
| `scenegraph/boundingvolume.py` | 11.5 % | `visible` 8.9 %, `getPoints` |
| numpy `_methods.py` (`_amin`/`_amax`) | 6.7 % | per-caster AABB min/max |
| `passes/_flat.py` | 6.2 % | `renderSet`, `greatestDepth` |

Roughly **two-thirds of the frame is the shadow pass**, and almost all of it is
pure-Python CPU, not GPU wait. Removing that redundant work is precisely the ~3×
that turned 60 fps into 20 fps.

### 2.3 What the shadow pass does every frame

Instrumented over 8 s of live rendering:

| Quantity | Per frame |
|---|---|
| Shadow-caster records in the scene | **287** |
| `renderShadowMaps` calls | 1 (every frame, unconditionally) |
| `_cullOccluders` calls | **7.8** (per light × per cascade/cube-face) |
| Caster bounding-volume `visible()` tests | **~2 252** |
| `_renderDepth` calls | 7.8 |
| Per-node depth draws (`path.Render`) into shadow maps | **~1 190** |

So each frame the shadow subsystem:

1. Rebuilds the full 287-node caster list, world points, and per-caster world-space
   AABB corners from scratch (`_shadowCasterRecords`, `_worldPointsFromRecords`,
   `_casterWorldAABBCorners`) — [shadowmixin.py:135-141](../OpenGLContext/passes/shadowmixin.py#L135-L141), [shadowmixin.py:492-580](../OpenGLContext/passes/shadowmixin.py#L492-L580).
2. Runs `_cullOccluders` ~8 times, each a Python loop over all 287 casters calling
   `boundingvolume.visible()` (a numpy matmul + plane test per caster) — [shadowmixin.py:384-407](../OpenGLContext/passes/shadowmixin.py#L384-L407).
3. Redraws ~1 190 caster nodes into the depth maps.

`renderShadowMaps(toRender)` is called **unconditionally every frame** with no
dirty-check and no frame-to-frame caching of either the caster data or the maps —
[_flat.py:965-967](../OpenGLContext/passes/_flat.py#L965-L967), [shadowmixin.py:105-143](../OpenGLContext/passes/shadowmixin.py#L105-L143).

---

## 3. Root cause

Two things multiply together:

1. **The glTF model is heavy: 287 discrete renderable nodes.** The recent loader
   work ("CHECKPOINT Reasonably parthenon-esque rendering, but very heavy model")
   produces a scene of 287 separate caster nodes rather than a handful of merged
   meshes.

2. **The shadow subsystem cost is O(casters × shadow-passes) with no caching.**
   With 4 lights and their cascades/cube-faces there are ~8 depth passes; each
   re-culls and partly re-draws all 287 casters, and every frame rebuilds the
   camera-independent caster geometry from scratch. The `frustcullaccel` C
   extension *is* active, but ~2 252 Python-level `visible()` calls per frame still
   cost real time.

The names `_toRender_cache` / `_caster_points` suggest caching, but they are
**recomputed every frame** ([shadowmixin.py:135-141](../OpenGLContext/passes/shadowmixin.py#L135-L141)).

**Key insight for the walking case:** `_shadowCasterRecords`, `_caster_points`,
`_casterWorldAABBCorners`, and the spot/point shadow maps themselves are all
**camera-independent** — they depend only on scene transforms, bounds, and light
positions. When walking, none of those change, yet all are recomputed and all
maps are re-rendered every frame.

---

## 4. Suggested remedies (priority order)

### R1 — Cache camera-independent caster data across frames *(biggest, safest win)*
`_shadowCasterRecords()`, `_worldPointsFromRecords()` and `_casterWorldAABBCorners()`
read only node transforms and bounding volumes. Compute them once and invalidate on
a scene-graph generation/dirty counter (light or geometry transform change), not
every frame. For a static scene these drop to zero cost.
*Impact:* removes most of the 24 % `shadowmixin` self-time + the 6.7 % numpy AABB
cost while walking. Low risk (pure memoization of already-deterministic values).

### R2 — Cache the shadow maps across frames (per-light dirty check)
Spot and point shadow maps are fully camera-independent; a directional CSM depends
on the camera frustum but its caster inputs do not. Re-render a light's depth map
only when that light or a caster it sees has moved. Walking a static scene →
spot/point maps render **once** and are reused every subsequent frame.
*Impact:* potentially eliminates most of the 68 % for the user's actual scenario.
Directional cascades still re-fit to the camera, so keep those, but feed them the
R1-cached caster bounds.

### R3 — Cull once per light instead of once per cascade/face
`_cullOccluders` runs 7.8×/frame, each a full 287-caster scan (~2 252 tests). Cull
once against the light's whole frustum (or a cheap union of its cascade frusta) and
reuse the surviving set per cascade. `_casterWorldAABBCorners` is likewise
recomputed per directional light though its input is the constant caster set — hoist
it out of the per-cascade loop ([shadowmixin.py:281](../OpenGLContext/passes/shadowmixin.py#L281)).
*Impact:* cuts the 11.8 % `_cullOccluders` cost by ~4–8×.

### R4 — Vectorize the cull
Even cached, the cull is 287 individual Python `visible()` calls. Batch all caster
AABB corners into one `(N,8,4)` array and do a single vectorized frustum-plane test
(one matmul + reduce) rather than a Python loop, or extend the `frustcullaccel`
batch API to take all boxes at once.

### R5 — Reduce caster count in the loader *(attacks the root multiplier)*
287 separate renderable nodes is the underlying driver. At load time, merge static
primitives that share a material into single meshes, and confirm repeated geometry
(e.g. the columns) actually collapses. Instancing runs (`build_instance_groups`,
13 %) yet the depth pass still issues ~1 190 per-node draws/frame — investigate why
the instanced depth path ([shadowmixin.py:632-650](../OpenGLContext/passes/shadowmixin.py#L632-L650))
leaves so many casters un-instanced. Ties into
[INSTANCED-GEOMETRY.md](INSTANCED-GEOMETRY.md).

### R6 — Build the `frustcullaccel` / accelerator C extensions in this env
The C path is active via `vrml.arrays.frustcullaccel`, but a batched C cull
(paired with R4) would remove the remaining per-call Python overhead.

### R7 — Platform probe: no change needed
Confirmed at 0.02 % of frame time. Leave `unix.py` as-is; it is not a perf concern.
(The commit's "verify the trade-off is acceptable" question is now answered: yes.)

---

## 5. Expected outcome

The shadow pass is ~68 % of the frame and is almost entirely redundant per-frame
Python work for a static scene. R1 + R2 alone (cache caster data + reuse
camera-independent maps while walking) should recover most of the lost 40 fps —
i.e. restore the ~60 fps the user saw — because "walking around" never changes the
inputs those computations depend on. R3–R6 harden the turntable / dynamic case
where casters genuinely move each frame.

**Profiling artifacts:** `profile.json` (speedscope) and the two instrumentation
scripts are in the session scratchpad.

---

## 6. Implementation progress

Measured with a display-free benchmark (`bench.py`): hidden GLFW/EGL window, core
profile, cascades pinned to 3, timing `renderShadowMaps` per call. Two motion
modes: **walk** (camera moves, model + lights static — the user's scenario, where
the caches should hit) and **spin** (model rotates every frame — cache-miss case).

Baseline `renderShadowMaps` per call: **walk 22.35 ms, spin 22.04 ms**
(re-renders everything every frame).

| Stage | walk (ms) | spin (ms) | Notes |
|---|---|---|---|
| Baseline | 22.35 | 22.04 | every frame rebuilds + re-renders all maps |
| + R1 | 18.50 (−17 %) | 20.72 (−6 %) | caster world-points / AABB cached across frames |
| + R3 | 17.25 (−23 %) | 19.95 (−9 %) | directional cull once per light, not per cascade |
| + R2 | 14.15 (−37 %) | 19.75 (−10 %) | spot/point depth maps reused while static |
| + R4a | 9.45 (−58 %) | 14.92 (−32 %) | instance grouping hoisted out of the per-cascade loop |
| + R4b | 7.94 (−64 %) | 13.08 (−41 %) | modelview + instance-buffer packing vectorized |
| + R5 | **6.22 (−72 %)** | **12.52 (−43 %)** | instance grouping cached across frames/lights |

All five are implemented, TDD'd (`tests/test_shadow_caching.py`, 20 tests + a
`pack_instance_buffer` equivalence test + extensions to `test_shadowmixin.py`), and
each verified pixel-identical to the pre-change baseline (0.000 % of pixels over
threshold — the captured frame renders 30 frames first, so the reused maps + caches
are exercised across motion, not just the first frame). Broad regression sweep
(shadows + instancing + gltf + pbr, 181 tests) green.

**walk** (the user's "walking around" case) is where the caches pay off: the
shadow pass dropped **22.35 → 14.15 ms, −37 %**. **spin** (the model rotating every
frame) only gets R3's structural saving, because a moving caster correctly
invalidates the R1/R2 caches (the spin number staying at ~20 ms, not dropping to
14 ms, is the proof the invalidation works — stale reuse would have shown the
cached cost).

### R1 — done (camera-independent caster-data cache)
`_refreshCasterData()` rebuilds the caster records (cheap: `transformMatrix()` and
`boundingVolume()` are dependency-cached) and derives `_caster_points` /
`_caster_aabb` only when a `_casterSignature` — the identities of each caster's
transform matrix and bounding volume — changes. A static scene under a moving
camera reuses last frame's world geometry; the per-caster AABB corners are also
now computed once and shared by both directional lights (previously recomputed per
directional light). Tests: `TestCasterDataCache`.

### R3 — done (cull once per directional light)
`_renderDirectional` builds all cascades' view/proj up front, then culls the caster
pool a single time against an ortho fitted to the union of every cascade's receiver
corners (which bounds every individual cascade), and draws the shared survivor set
into each cascade layer. A caster outside a given cascade is clipped by that
cascade's own projection exactly as before — but the O(N-casters) cull scan runs
once per light instead of once per cascade (was 3×). Spot lights already culled
once; point lights keep their per-face empty-skip. Tests:
`TestDirectionalCullsOncePerLight`.

### R2 — done (spot/point depth-map reuse)
`_depthMapFresh(light, transform, array_key)` keys a per-light cache on the light's
dependency-cached transform, the caster signature, and the physical depth texture +
layer. When all three are unchanged, the spot depth pass (`bind_layer` +
`_renderDepth`) and the whole point-light cube face loop are skipped — last frame's
depth is still valid because a spot/point map is camera-independent. The binding
matrix (which folds in the moving camera) is still recomputed every frame. The
`array_key` (texture id) means a pool realloc or `disposeShadowMaps` auto-forces a
re-render. Directional CSM re-fits to the camera and is never cached here. Tests:
`TestSpotMapReuse`, `TestPointMapReuse`, plus the dispose-clears-cache assertion.

### R4 — done (hoist instance grouping + vectorize the draw prep)
Two parts:
- **R4a (hoist).** The group/single partition depends only on the caster set, not
  the light or cascade, so `_renderDirectional` now builds it **once** via the new
  `_depthGrouping()` and passes it to every cascade's `_renderDepth`, instead of
  each `_renderDepth` rebuilding it. That alone took walk 13.8 → 9.5 ms. Tests:
  `TestDirectionalGroupsOncePerLight`.
- **R4b (vectorize).** `_renderDepthGroup` built each instance's light-space
  modelview in a Python loop of per-member `dot`s, and `pack_instance_buffer`
  filled the instance VBO one instance at a time. Both are now single batched numpy
  ops (`_lightSpaceModelviews` = one `matmul`; pack = one `reshape`). Tests:
  `TestLightSpaceModelviews`, `test_stacked_ndarray_matches_list_of_matrices`.

### R5 — done (grouping cache), reframed after profiling
The report first scoped R5 as a **loader mesh-merge** to cut the 287-node caster
count, on the belief the depth pass "still issues ~1 190 per-node draws". Profiling
the post-R4 build corrected that: instancing already collapses the 287 casters to
**10 instanced groups + 19 singles = 29 draws per cascade**. The columns *do*
collapse (groups of 96 / 46 / 46). So the caster count is not a *draw*-count
problem — it is a per-frame **CPU** cost (rebuilding the grouping, culling, near-fit
over 287 records). The effective fix for a static scene is therefore to **cache the
grouping across frames and across lights**, not to merge meshes.

`_depthGrouping` now memoises its result in `_depth_grouping_cache`, keyed on the
caster signature (a moved caster invalidates) and the occluder set's path
identities (a change in which casters a light sees invalidates). A static scene
reuses one build every frame, and the two directional lights share a build when
they cull to the same set. This took walk 7.9 → 6.2 ms and drove `_depthGrouping`
from 13 % of the frame to **0.4 %**. Tests: `TestDepthGroupingCache` (5 cases) +
the dispose-clears-cache assertion.

### Profile shift (walk, py-spy, offscreen)

| Function | Baseline | After R1–R5 |
|---|---|---|
| `_casterWorldAABBCorners` | 10.3 % | **~0 %** (cached) |
| `_depthGrouping` / `build_instance_groups` | 13 %+ | **0.4 %** (cached) |
| `_cullOccluders` (inclusive) | 11.8 % | 6.8 % |
| `boundingvolume.py` (self) | 11.5 % | 8.1 % |
| `shadowmixin.py` (self) | 24.2 % | 15.0 % |
| `instancing.py` (self) | 13.3 % → 29 % (post-R3) | 13.0 % |

### Where the walk frame stands now, and what's left
`renderShadowMaps` is down to ~55 % of the walk frame with **no single dominant
cost**. The remaining shadow-CPU is spread across the *inherently* camera-dependent
directional CSM work that cannot be cached: `_renderDepthGroup` (13 %, the actual
per-cascade instanced draws — `_lightSpaceModelviews` + `pack` + `draw` + GL upload),
`_extend_near_for_casters` (8.6 %, per-cascade near-plane fit over the caster boxes),
and the per-caster `_cullOccluders` scan (6.8 %). Genuine next steps, in value
order:
- **Vectorize `_cullOccluders`** against the cached per-caster world boxes (one
  batched plane test vs 287 Python `visible()` calls) — the "vectorize the cull"
  idea, deferred here because an exact (oriented-box) vectorization needs the
  per-caster corners cached, not just the AABB.
- **Hoist / vectorize `_extend_near_for_casters`** across a light's cascades.
- **Loader-side merge (original R5)** would still help the **spin / animated** case
  (where per-frame caches miss), by shrinking the 287-record iteration itself — but
  it is a large, higher-risk loader change (materials, baked transforms, picking
  ids, skinning) with limited upside for the already-instanced columns, so it is
  left as future work rather than shipped here.

Net: the user's **walking** scenario — the actual complaint — improved **22.35 →
6.22 ms per shadow pass, −72 %**; the spin/turntable case **22.04 → 12.52 ms,
−43 %**.

---

## 7. Reality check — why the real-world gain was only 20 → ~23–35 fps

The R1–R5 numbers above are all from an **offscreen CPU benchmark** that timed
`renderShadowMaps` in isolation. On the real display they translated to only
~20 → 23 fps. Profiling the *actual* display (foreground, with permission)
corrected several of my earlier conclusions. Recorded here so the next person
doesn't repeat the mistakes.

### What was actually measured wrong
- **The offscreen benchmark measured shadow-pass CPU, not the frame.** Headless,
  the whole parthenon frame renders at ~80 fps even at 1080p — so the shadow-pass
  CPU that R1–R5 cut was never the frame-rate wall on the real display. My py-spy
  root cause (shadow pass = 68 % of samples) was 68 % of **on-CPU** time; py-spy
  without `--idle` doesn't sample time blocked in the driver/present, so it
  over-weighted the CPU-bound shadow work.
- **`glFinish`-per-phase measurements are misleading.** Putting `glFinish` after
  `renderShadowMaps` *serialised* the shadow GPU work and made it look like ~11 ms
  ("shadow resolution barely matters, cascade count does"). Without that barrier
  the GPU pipelines the passes and the true per-frame delta of a cascade is far
  smaller. Trust **end-to-end cadence with vsync off**, not `glFinish` segment
  timers.

### What the real display actually shows (foreground, vsync off)
Whole-frame, parthenon, camera dolly (no physics):

| Size | pinned 3 cascades | adaptive (this fix) | 1 cascade |
|---|---|---|---|
| 1280×960 | 56 fps | **64 fps** | 69 fps |

- **Present is cheap** (~3–5 ms); the frame is render-bound, split roughly evenly
  between the shadow depth passes and the color/IBL pass. No single dominant cost
  survives after R1–R5.
- **The FPS overlay costs ~3 ms/frame.** All the R1–R5 benchmarks disabled it;
  the interactive session has it on (it's how you read fps). With it on, the same
  scene reads **~36 fps** — matching the user's report.
- **Shared-GPU load in this container is significant and variable.** The identical
  config measured 64 fps and 40 fps minutes apart. The user's 20–35 fps swing is
  substantially this, not the code.

### The one real interactive win found here — ship it
The viewer **pinned `OPENGLCONTEXT_SHADOW_CASCADES=3`** at import, which *disabled*
the fps-adaptive cascade controller that is explicitly designed to shed cascades
below 60 fps. Each cascade is a full depth pass over the scene (the single largest
shadow lever — shadow *resolution* barely matters, so it's per-pass overhead, not
fill). **Fix:** pin cascades only for `--capture` (reproducible reference frames);
leave interactive adaptive. On the parthenon the controller settles at 1 cascade,
lifting the render ~56 → 64 fps — a bigger real-world gain than all of R1–R5.
`gltf_regression` renders `--no-shadows`, so baselines are unaffected; a `--capture`
frame stays pixel-identical to the old pinned output. Tests:
`test_gltf_view_cli.py::TestApplyRenderEnv` (interactive-adaptive / capture-pins /
explicit-override). Decision confirmed with the user; both directional lights keep
casting (no fill-light change).

### Honest bottom line
- R1–R5 are correct, tested, shipped CPU wins, but they attacked a bottleneck that
  wasn't the real-display wall — hence the underwhelming 20 → 23 fps.
- The cascade-pin fix is the highest-value interactive change and is shipped.
- Beyond that there is **no single hot spot left**; further real gains need broad
  per-pass-overhead / color-pass work, a lighter FPS overlay, or simply a less
  contended GPU. Use `tests/diag_live.py` (live render/present/cadence/pick/
  physics/cascade monitor) in a real session to see where a given machine's frame
  time goes, rather than trusting an offscreen CPU benchmark.
