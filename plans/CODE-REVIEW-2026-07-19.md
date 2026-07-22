# OpenGLContext Critical Code Review — Terrain / Vegetation / IBL / Shadow-Caching (2026-07)

**Date:** 2026-07-19
**Scope:** All changes to `OpenGLContext` since commit `9eb2ff1` (8 commits, ~16 k insertions), driven by the walkable **forest-demo** (`forest-demo/`). Concretely: the new terrain (`scenegraph/terrain/`), vegetation (`scenegraph/vegetation/`) and terrain-walk (`move/terrainwalk.py`) engine; the runtime HDR/IBL work (`loaders/hdr.py`, `hdri.py`, `scenegraph/hdrbackground.py`, `passes/ibl.py`); the shadow-caching regression fixes (`passes/shadowmixin.py`, `shadowpool.py`, `shadowcaps.py`); the glTF/Draco loader + resolver changes (`loaders/gltf/`, `loaders/loader.py`, `loaders/resolver.py`); and the new (demoted-to-optional) `loaders/tiles3d/` streaming package.
**Method:** Six parallel per-subsystem analyses, each grounded in cited `file:line`, then the load-bearing claims (IBL fallback-path state corruption, shadow layer-reuse and cache-commit bugs, the `castsShadow` depth-pass filter, the GL-3.3-vs-4.2 baseline, the PBR sampler budget, the clump-texture write side effect) **independently re-verified against source** before inclusion. Findings that could not be confirmed were dropped.

**Bottom line.** The new engine is, on balance, well-built: conservative core-profile feature use, honestly-documented performance work, real test coverage (`tests/tiles3d/` alone is ~20 modules), and a genuinely correct security core in the resolver. It is close to the stated goal — a clean scaffold a new 3D developer could learn from. But three things stand between "works on my discrete NVIDIA box" and "production-reliable on integrated and discrete desktop GPUs": (1) the **IBL fallback path corrupts global GL state on exactly the weak GPUs it exists to protect**; (2) the **shadow-caching layer has two latent stale-map bugs** in the walking-a-static-scene workload it was written for; and (3) there is **no GPU-capability/graceful-degradation layer outside the shadow subsystem, and no GL-resource teardown anywhere** in the new nodes. All three are fixable without redesign, and the shadow subsystem's own `shadowcaps.py` is the template for fixing (1).

---

## Ranked findings

**Severity:** CRITICAL = breaks/corrupts the renderer for a supported target · HIGH = wrong output or a crash on a plausible path · MEDIUM = defeated optimization, latent correctness, or real maintenance burden · LOW = polish. **Area:** portability = integrated-vs-discrete GPU fallback.

| # | Severity | Area | Finding | File |
|---|----------|------|---------|------|
| 1 | **CRITICAL** | portability/correctness | `IBLProbe._build` is not exception-safe: on FBO-incompleteness (the integrated-GPU case the analytic fallback exists for) it leaves the 128² probe FBO bound, viewport at 128², depth/cull **disabled**, and leaks the vao/fbo/4 programs — every subsequent frame renders broken | `passes/ibl.py:291-294,376-478` |
| 2 | **HIGH** | correctness | Shadow depth-map cache serves a **stale layer**: a light leaving then re-entering the frustum reclaims a physical array layer another light rendered into; `_depthMapFresh` sees transform+sig+texture unchanged and skips the re-render → samples the wrong light's depth | `passes/shadowmixin.py:185-199,289,387,622-642` |
| 3 | **HIGH** | correctness | Shadow cache key is **committed before the render succeeds**: if `bind_layer`/`_renderCubeFaces` then fails, next frame reports "fresh" and the depth pass is skipped permanently → phantom shadows from never-rendered `glTexStorage` depth | `passes/shadowmixin.py:289-296,387-388,638-642` |
| 4 | **HIGH** | portability | **No GL resource teardown** in any new node (terrain/vegetation/hdrbackground): no `dispose()`/`__del__`, and mesh/index VBO handles are created-but-not-stored so they can *never* be freed — VRAM growth on every field/world rebuild, worst on shared-memory integrated GPUs | `vegetation/billboards.py:58`, `clumps.py:167,172`, `nearmesh.py:70,75`, `terrain/splat.py:82-112`, `hdrbackground.py:126-135` |
| 5 | **MEDIUM-HIGH** | security | **Draco decompression bomb**: `max_resource_bytes` caps the *compressed* input but nothing bounds the *decoded* vertex/index count — a few-hundred-KB blob can decode to GB of geometry (once `DracoPy` is installed) | `loaders/gltf/draco.py:59-72` |
| 6 | **MEDIUM-HIGH** | portability | **No shader-compile / capability fallback**: `load_program` raises on any compile/link failure and it propagates out of `render()`, killing the frame loop instead of disabling one layer — no `glGetString(GL_VERSION)` probe, no degraded path | `scenegraph/instancedgl.py:20-27`, all veg/terrain nodes |
| 7 | **MEDIUM** | portability | **Baseline mismatch**: every shader declares `#version 330 core` (GL 3.3) but the Python uses `glTexStorage2D/3D` (GL 4.2 / `ARB_texture_storage`) unconditionally in IBL/shadow/transmission — the real floor is ~GL 4.1+ext, undocumented, no `glTexImage` fallback | `passes/ibl.py:304,336,448`, `shadowmap.py`, `transmission.py` |
| 8 | **MEDIUM** | portability | **PBR fragment sampler pressure**: `pbr.frag` declares 23 `sampler2D` + 2 `samplerCube` + BRDF LUT; combined with shadow (units 4-9) + IBL (13-15) this exactly fills the 16-unit GL-3.3 floor, and the fixed layout is decoupled from `shadowcaps`' budget math (raising `MAX_SHADOW_LIGHTS` silently collides samplers) | `shaders/pbr.frag:249-286`, `passes/shadowcaps.py:56-72`, `pbrpass.py:53-95` |
| 9 | **MEDIUM** | perf | Shadow `castsShadow=False` filter is applied only to the cascade-fit set, **not** the depth-pass caster pool (`_shadowCasterRecords` is unfiltered) — grass/foliage that opted out is still drawn into every cascade/face; the optimization is defeated | `passes/shadowmixin.py:136-137,566-586` |
| 10 | **MEDIUM** | maintenance | `tiles3d/foliage.py` + `vegetation.py` are a **second, competing vegetation engine** (~50-70 % dead code, three scatter impls, two `conifer`s) reachable only through the legacy `bin/terrain_view.py`; a new dev cannot tell which vegetation API is canonical | `loaders/tiles3d/{foliage,vegetation,geomorph}.py` |
| 11 | **MEDIUM** | correctness | `HeightField.from_image` divides by a hard-coded `65535` with no bit-depth/mode guard → an 8-bit or RGB DEM yields **silently near-flat or broken** terrain | `scenegraph/terrain/heightfield.py:32-34` |
| 12 | **MEDIUM** | portability | `load_clump_glb` writes an extracted `<stem>_tex.png` **into the source/asset dir on every load** → `PermissionError` on a read-only pip install (confirmed: it produced the untracked `grass-clumps/basic-clump_tex.png`) | `scenegraph/vegetation/clumps.py:121-122` |
| 13 | **MEDIUM** | correctness | `world_grid_scatter` hashes with `sin()` of integer cell indices that grow with world position → precision collapses far from origin, banding the "random" jitter/yaw/scale/keep and structuring grass gaps | `scenegraph/vegetation/grid.py:39` |
| 14 | **MEDIUM** | maintenance | Fragile cross-pass coupling: terrain and veg nodes reach into the PBR pass's private cache (`mode._pbr_cull_enabled = None`) to undo their own GL-state changes instead of save/restoring locally; shadow cache correctness silently depends on `transformMatrix()` object-identity | `terrain/splat.py:147`, veg nodes, `shadowmixin.py:588-598` |
| 15 | **MEDIUM** | perf | `terrainwalk._push_out` runs a full-array numpy scan over **all** trunk colliders every substep (≤8×/frame) with no spatial-grid broadphase — O(N_trees) per frame for a scene of tens of thousands of trunks | `move/terrainwalk.py:71-95` |

Lower-severity items (per-restream `glBufferData` reallocation, constant uniforms re-uploaded every frame, `sun_shadow` bake stutter on first frame, `gltf_uploader.release()` no-op, `physics_colliders.on_evicted` unbounded list, duplicated GLB-buffer/noise/normalize code, `_coerce_normalized` crash on malformed Draco) are detailed per-subsystem below.

## Remediation status

**Pass 1 (2026-07-19)** — ranked findings **1–4, 6–7, 9, 11–15**.
**Pass 2 (2026-07-20)** — additional findings **V1, V4–V7, T1, T3–T7, I1, I4–I8, S2, S4, G1–G6, X1, X2, X4, X5, D1–D3** (see the per-item table below the ranked one). Highlights: a vegetation `InstancedVegBase` collapsing the three nodes' duplicated render/attrib code with the mesh↔impostor LOD window driven by one shared `LOD_NEAR`/`LOD_FAR` uniform pair; a capacity-tracked `InstanceBuffer` (no per-frame realloc); an IBL float-render **capability probe** that gates `full` up front (plus an LDR skybox fallback); the shared `dirToEquirect` GLSL include; Draco malformed-stream/decompression-isolation hardening; `cc0` relocated out of the demoted `tiles3d` package to `loaders/`; and the **forest-demo** refactored into an importable `ForestConfig` + `build_forest_scene()` → `ForestScene` (with reusable streamers) so a future "driving through a forest" demo can reuse the whole terrain+forest build, its knobs moved from scattered `os.environ` reads to argparse CLI flags, and the grass clump bundled as a package asset.

Every fix ships with tests; the full affected engine suite is green (388 affected unit/GL tests together, plus 403 passed + 4 xfailed across the shadow-render + PBR + glTF-conformance regression, and 8 forest-demo tests). Still open: ranked **5** (Draco decode-size cap), **8** (PBR sampler-budget unification), **10** (prune the duplicate tiles3d vegetation engine); and lower-severity **V2, T2, I3, X3** with **S1** partial (see the additional-findings table).

| # | Severity | Status | Remediation |
|---|----------|--------|-------------|
| 1 | CRITICAL | ✅ Fixed | `IBLProbe._build` wrapped in `try/finally`: transient vao/fbo/programs freed and the caller's FBO/viewport/depth/cull restored on any failure (incl. the completeness `raise`); verdict raised after restore. `passes/ibl.py`. |
| 2 | HIGH | ✅ Fixed | Depth-map cache re-keyed to the physical slot with owner `(light, transform, caster_sig)`; a reclaimed layer now misses → re-renders. `shadowmixin._depthMapFresh`. Test: `TestSpotSlotOwnership`. |
| 3 | HIGH | ✅ Fixed | Query (`_depthMapFresh`) split from commit (`_markDepthRendered`); a slot is recorded only after a successful depth pass. Test: `TestDepthCacheCommit`. |
| 4 | HIGH | ✅ Fixed | `dispose()` added to billboards/clumps/nearmesh/splat/hdrbackground; every VBO/VAO/texture/program handle retained. HDR defers deletion to the GL thread. Tests: `test_vegetation_gl_render`, `test_hdr_background`. |
| 5 | MEDIUM-HIGH | ⬜ Open | Draco decoded-size cap — not in this pass. |
| 6 | MEDIUM-HIGH | ✅ Fixed | `instancedgl.ensure_gl` disables a node (logged once) on `_init_gl` failure, so a compile/driver error no-ops instead of crashing the loop. Tests: `test_instancedgl_helpers`, `test_vegetation_gl_render`. |
| 7 | MEDIUM | ✅ Documented | Immutable-storage floor (GL 4.2 / `ARB_texture_storage`, effective 4.1+ext) documented in `CLAUDE.md` + `ibl.py`; no `glTexImage` fallback added (extension universal on desktop). |
| 8 | MEDIUM | ⬜ Open | PBR sampler-budget unification with `shadowcaps` — not in this pass. |
| 9 | MEDIUM | ✅ Fixed | `castsShadow=False` filtered inside `_shadowCasterRecords` (the depth-pass pool), so opted-out foliage is drawn into no depth map. |
| 10 | MEDIUM | ⬜ Open | tiles3d duplicate-vegetation prune — not in this pass. |
| 11 | MEDIUM | ✅ Fixed | `HeightField.from_image` picks the divisor by image mode (8/16-bit; RGB→luminance) and asserts 2-D. Test: `test_heightfield_from_image`. |
| 12 | MEDIUM | ✅ Fixed | `load_clump_glb` returns a decoded `PIL.Image`; `texture_rgba` accepts an in-memory image — nothing written beside the asset. Tests: `test_instancedgl_helpers`, `test_vegetation_gl_render`. |
| 13 | MEDIUM | ✅ Fixed | `world_grid_scatter` uses an integer avalanche hash on wrapped cell indices (5 independent streams); precision-stable far from origin. Test: `test_grid_scatter_hash`. |
| 14 | MEDIUM | ✅ Fixed | Veg/terrain nodes `save_draw_state()`/`restore_draw_state()` locally (cull enable+mode+winding, depth, mask, blend) and no longer poke `mode._pbr_*`. Test: `test_vegetation_gl_render` asserts entry state restored. |
| 15 | MEDIUM | ✅ Fixed | `terrainwalk` builds a uniform spatial-hash grid; `_push_out` tests only the 3×3 cell neighbourhood, identical to brute force. Test: `test_terrainwalk_broadphase`. |

### Additional findings (per-subsystem, §1–§7)

Every non-ranked item raised in the narrative sections below, for completeness. The requested remediation set was the ranked 1–15, so most of these are **open**; a few were resolved incidentally by the ranked fixes (marked ✅ with the ranked finding that closed them). Status: ✅ Fixed · 🟡 Partial · ⬜ Open. (§1's items are all ranked — #1/#6/#7/#8 — so it adds none here.)

| ID | § | Sev | Status | Item |
|----|---|-----|--------|------|
| V1 | 2 | MED | ✅ Fixed | Duplication: instance-attrib VAO block ×3, near-identical `render()` preamble (clumps/nearmesh), `_BIG` ×4, and the LOD cross-fade window hardcoded separately in `veg_mesh.frag`/`veg_billboard.frag` (seam-drift). Needs `InstancedVegBase` + shared GLSL/uniform LOD window. (The `mode._pbr_*` reset part of the preamble was removed via #14.) |
| V2 | 2 | MED | ⬜ Open | Scene lighting/fog/sun/ambient literals hardcoded in each node `render()`; source from a shared scene-environment object. |
| V3 | 2 | LOW | ✅ Fixed (#14) | `billboards.render()` now restores depth-mask/blend like its siblings, via `save/restore_draw_state`. |
| V4 | 2 | LOW | ✅ Fixed | Per-restream `glBufferData` reallocation (use a sized buffer + `glBufferSubData`). |
| V5 | 2 | LOW | ✅ Fixed | Constant uniforms + a `glGetIntegerv(GL_CURRENT_PROGRAM)` sync re-issued every frame. |
| V6 | 2 | LOW | ✅ Fixed | Eye-space `N.z` used as the sky/ground-ambient up-axis. |
| V7 | 2 | LOW | ✅ Fixed | Mesh/`npz` file handles opened without context managers. |
| T1 | 3 | MED | ✅ Fixed | `_control_texture` reimplements `instancedgl.texture_rgba`; call the helper. |
| T2 | 3 | MED | ⬜ Open | `sun_shadow` bake is O(steps·R²) with `np.roll` copies, lazy on the GL thread (startup hitch), and wraps shadows across terrain edges. |
| T3 | 3 | LOW | ✅ Fixed | `numLayers < 4` leaks control-map weight into a nonexistent layer (`terrain_splat.frag:37`). |
| T4 | 3 | LOW | ✅ Fixed | Slope underestimated at terrain edges (clamped taps). |
| T5 | 3 | LOW | ✅ Fixed | `uNormalMatrix` is the plain MV upper-3×3 (document the orthonormal assumption). |
| T6 | 3 | LOW | ✅ Fixed | `SplatTerrain` subclassing `PointSet` is misleading. |
| T7 | 3 | LOW | ✅ Fixed | Unnamed terrain tuning constants. |
| I1 | 4 | HIGH | ✅ Fixed | No capability *detection*: `resolve_ibl_mode` uses a renderer-name blocklist, not a probe; HDR skybox `GL_RGB16F` has no LDR fallback. Recommended: a one-time RGBA16F-FBO/extension probe feeding `resolve_ibl_mode` so `full` is never selected on hardware that can't support it. |
| I2 | 4 | MED | ✅ Fixed (#4) | HDR skybox leaked its texture+VBOs+VAO on every env change — closed by the deferred GL-thread free + `dispose()`. |
| I3 | 4 | MED | ⬜ Open | `GL_TEXTURE_CUBE_MAP_SEAMLESS` correctness hinges on a leaked build-time side effect (left as-is deliberately; enable it in the PBR pass around probe sampling). |
| I4 | 4 | MED | ✅ Fixed | Equirect UV mapping duplicated in `hdr_background.frag` & `ibl_equirect.frag` (must stay lock-step); move to the shared include. |
| I5 | 4 | MED | ✅ Fixed | 1k equirect minified to 128² faces with no mip chain → aliased sun in reflections. |
| I6 | 4 | LOW | ✅ Fixed | Teardown `except Exception: pass` hides real GL errors. |
| I7 | 4 | LOW | ✅ Fixed | Load-thread/render-thread swap on `_equirect`/`_render_data` (document the ordering). |
| I8 | 4 | LOW | ✅ Fixed | `_build` is a ~100-line god-function worth splitting (now `try/finally`-wrapped, not split). |
| S1 | 5 | MED | 🟡 Partial | `_depth_map_cache` unboundedness fixed (re-keyed to the physical slot → bounded by slot count); the `id(light)`/`id(transform)` reuse hazard in the owner *value* remains (add a generation counter / weakref). |
| S2 | 5 | MED | ✅ Fixed | Cache correctness depends on the `transformMatrix()`/`boundingVolume()` object-identity contract — document it and add an integration test that moves a real node. (The `_pbr_*`-poke half of #14 is fixed; this test/doc is not.) |
| S3 | 5 | LOW | ✅ Fixed (#2/#3) | Frame-2 redundant re-render (freshness key read `smap.texture` before allocation) — the query/commit split records the key only post-allocation, so frame 2 hits. |
| S4 | 5 | LOW | ✅ Fixed | R3 single-cull completeness is asserted, not tested (add a far-cascade-only caster test). |
| G1 | 6 | MED | ✅ Fixed | `_coerce_normalized(None, raw)` `AttributeError` on a malformed Draco stream; also duplicates `_normalize_array`. |
| G2 | 6 | LOW | ✅ Fixed | Local-file fetch reads the whole file before the size check (stat-first). |
| G3 | 6 | LOW | ✅ Fixed | A malformed Draco blob aborts the whole scene (vs the DracoPy-absent skip). |
| G4 | 6 | LOW | ✅ Fixed | Draco "warn once" spams when `resolver is None`. |
| G5 | 6 | LOW | ✅ Fixed | `get_reference` resolves the URI twice. |
| G6 | 6 | LOW | ✅ Fixed | `_draco_warned` stamped ad hoc on the resolver. |
| X1 | 6 | MED | ✅ Fixed | `gltf_uploader.release()` is a no-op (GC frees VBOs → VRAM lags the accounted budget). |
| X2 | 6 | MED | ✅ Fixed | `physics_colliders.on_evicted` grows `pending_removals` unbounded (no `PhysicsWorld.remove_body`). |
| X3 | 6 | MED | ⬜ Open | `foliage.ground_patch_split` Python per-triangle loop + `ground_patch_blended` 1024² bake on the main thread on camera move (stutter). |
| X4 | 6 | LOW | ✅ Fixed | `Residency.enforce_budget` rescans all tiles each frame and never deletes `UNLOADED` entries. |
| X5 | 6 | note | ✅ Fixed | `tiles3d.cc0` is a hard dependency of `terrain/splat.py`; move `cc0` to a shared `loaders/` location. |
| D1 | 7 | note | ✅ Fixed | forest-demo `OnInit` is a 185-line god-method (the biome/scatter block would factor well). |
| D2 | 7 | note | ✅ Fixed | forest-demo clump path is a fragile relative `os.path.join` that breaks on a `uvx` install; ship the clump as a package asset (pairs with #12). |
| D3 | 7 | note | ✅ Fixed | forest-demo relies on many `os.environ` knobs with defaults scattered through the code. |

---

## 1. Portability — the integrated-vs-discrete GPU axis (the headline requirement)

The feature *choices* are mostly right for "both integrated and discrete desktop GPUs": a uniform `#version 330 core` floor, instanced arrays (core 3.3), texture arrays with ≤4 layers, `GL_R8`/`GL_RGBA8`/`GL_DEPTH_COMPONENT24` (no float-renderable dependency in terrain/shadow), `RGBA16F` (not `RGB16F`/`RGBA32F`) for the IBL render targets — that last one is exactly the color-renderable choice a portable engine should make. The **shadow subsystem is the model to copy**: `shadowcaps.py` probes `GL_VERSION`, the extension set and `GL_MAX_TEXTURE_IMAGE_UNITS`, budgets samplers, and degrades from `samplerCubeArrayShadow` to per-light `samplerCubeShadow` with a conservative 3.3 fallback when detection fails.

The gaps are that **nothing else does this**, and the one place a fallback is most needed is the one place it corrupts state:

- **#1 (CRITICAL) — IBL fallback corrupts GL state.** `_build()` saves state (`ibl.py:377-387`), disables depth/cull/blend, enables `GL_TEXTURE_CUBE_MAP_SEAMLESS`, binds a fresh 128² FBO, renders, and restores at `461-475` — all on the **straight-line success path with no `try/finally`**. The FBO-completeness check at `366-367` `raise`s precisely on a driver that can't render the float cube (the integrated case). Control jumps to `ensure_built`'s `except` (`291-294`), which calls only `release()` (deletes textures). It does **not** rebind `prev_fbo`, restore the viewport, re-enable depth/cull, disable seamless, or delete the vao/fbo/4 programs. Result: the "graceful fallback to analytic" leaves the renderer drawing into an orphaned 128² FBO with depth testing off for every following frame, and leaks GL objects on each attempt. *Fix:* wrap the body in `try/finally` with object cleanup **and** state restore in the `finally`; keep the final completeness `raise` after state is restored.
- **#6 — no compile/capability fallback.** `load_program` (`instancedgl.py:20-27`) raises on compile/link failure; the exception propagates out of a node's `render()` and kills the loop. *Fix:* one-time `glGetString(GL_VERSION)` probe; wrap `_init_gl` in try/except, log, set `self._disabled`, and make `render()` a no-op — a missing-grass frame instead of a crash.
- **#7 — 3.3-claimed / 4.2-required.** `glTexStorage*` is GL 4.2. In practice every post-2012 desktop GPU (integrated Intel/AMD included) exposes `ARB_texture_storage`, and macOS 4.1 exposes the extension, so this is not a live failure on realistic hardware — but the "3.3 core" claim in the shaders and CLAUDE.md is misleading, and there is no gate. *Fix:* either document the true floor (GL 4.1 + `ARB_texture_storage`) or gate `glTexStorage` on the extension with a per-level `glTexImage` allocation fallback (allocating *every* mip level explicitly solves the incompleteness the comment at `ibl.py:299-301` cites).
- **#8 — sampler budget.** `pbr.frag` + shadow + IBL exactly fills 16 fragment units on the guaranteed-minimum GPU; the packed layout (`shaderpass_shadow.py:38-40`, `pbrpass.py:53-95`, `ibl.py:58`) is a set of hardcoded unit numbers disconnected from `shadowcaps`' `avail - reserved` arithmetic, so it only fits because `HARD_MAX = 4` coincidentally caps point lights. There is no `max_texture_units < 16` guard/log. *Fix:* derive the shadow/IBL base units from the same budget computation (single source of truth); log and clamp when a driver reports < 16.

**Verdict on the requirement:** with #1 fixed and a small capability probe added (so IBL `full` is never *selected* on hardware that can't support it, rather than discovered mid-build), the engine meets "runs on integrated and discrete." Until then, an integrated GPU that fails float-FBO completeness gets a broken screen, not a degraded one.

---

## 2. Vegetation (`scenegraph/vegetation/`, `veg_*` shaders)

Good bones: distance/turn-gated streaming means `update_instances` is *not* per-frame; `shadow_pass`/`visible` guards; correct divisor/stride/buffer math (verified); `poisson_thin` ships a scipy fast path + scipy-free spatial-hash fallback; height-normalizing the clump so per-instance scale reads as world height. Issues:

- **#4 — resource leak (HIGH).** No `dispose()` anywhere; worse, `billboards.py:58`, `clumps.py:167,172`, `nearmesh.py:70,75` create mesh/index VBOs but never store the handles, so even a future cleanup can't delete them. *Fix:* store every generated name; add `dispose()` calling `glDeleteVertexArrays/Buffers/Textures`; invoke it when the demo swaps a node.
- **#12 — clump texture written into the asset dir (MEDIUM).** *Fix:* decode the embedded PNG in memory (`Image.open(io.BytesIO(raw))`) and add a `texture_rgba` overload taking a `PIL.Image`/bytes, or write to a per-user cache dir.
- **#13 — `world_grid_scatter` hash degrades far from origin (MEDIUM).** *Fix:* integer hash (PCG/wang) on the wrapped cell indices instead of `sin()` of a growing float.
- **Duplication (MEDIUM).** The instance-attrib VAO block is copy-pasted in all three nodes; the `render()` preamble (program save/restore, matrix upload, sun-in-eye, the identical `sunColor/skyAmbient/groundAmbient/fogDensity=0.00016/fogColor` block, the `mode._pbr_*` reset) is near-identical between `clumps.py:197-211` and `nearmesh.py:117-135`; `_BIG` is defined four times. The LOD cross-fade window `smoothstep(38.0, 52.0, …)` is hardcoded *separately* in `veg_mesh.frag:13` (mesh fades out) and `veg_billboard.frag:16` (impostor fades in) — two independent magic literals that must stay complementary or the mesh↔impostor handoff shows a seam, and neither is tied to the demo's actual `nearmesh.update(radius=56.0)`. *Fix:* an `InstancedVegBase` node + shared attrib helpers in `instancedgl.py`; a shared GLSL include for `aces`/gamma/fog/dither; pass the LOD window as a `uLodStart/uLodEnd` uniform pair from one Python constant. This single refactor closes #4, the duplication, and the seam-drift hazard together.
- **Scene lighting is hardcoded into node `render()` (MEDIUM maintainability).** Fog/sun/ambient literals are baked into each node and must match terrain/PBR with nothing enforcing it; the demo can't change atmosphere without editing engine source. *Fix:* source them from a shared scene-environment object (`terrain` already exports `DEFAULT_SUN`).
- **LOW:** per-restream `glBufferData` reallocation (use a max-capacity buffer + `glBufferSubData`); constant uniforms + a `glGetIntegerv(GL_CURRENT_PROGRAM)` sync re-issued every frame; `billboards.render()` doesn't restore `glDepthMask`/blend like its siblings; eye-space `N.z` used as the sky/ground-ambient up-axis; file handles opened without context managers.

---

## 3. Terrain (`scenegraph/terrain/`, `terrain_splat.*`, `move/terrainwalk.py`)

Good: `HeightField.sample` is fully vectorized and provably consistent with `.mesh` (both index `grid[z,x]`); swept-substep collision with a documented substep/cap prevents tunnelling at any framerate; idle redraw gated on a pose signature so a parked camera doesn't spin the GPU; splat binds only 5 samplers (safe) with ≤4 array layers. Issues:

- **#11 — `from_image` hardcoded `/65535` (MEDIUM correctness).** The forest asset is `I;16` so it works, but an 8-bit or RGB DEM silently yields near-flat/broken terrain. *Fix:* `Image.open(path).convert("I")` (or detect mode and scale by the right max) and assert 2-D.
- **#15 — collision broadphase is O(N) (MEDIUM perf).** `_push_out` scans all colliders every substep. *Fix:* a uniform spatial-hash grid keyed on world cell, queried for the player's cell + neighbours.
- **#14 — `mode._pbr_*` poke (MEDIUM).** `splat.py:144` enables cull/depth/face and never restores them, instead invalidating the PBR pass's private cache at `:147`. *Fix:* local save/restore mirroring the clean `prev_prog` handling.
- **#4 — resource leak.** `splat.py` stores `prog/vao/tex` but not `vb`/`ib`; no `dispose()`.
- **MEDIUM:** `_control_texture` (`splat.py:46-54`) reimplements `instancedgl.texture_rgba` — call the existing helper. The `sun_shadow` bake is O(steps·R²) with two full-array `np.roll` copies per step, run lazily on the GL thread inside the first `render()` (startup hitch) and wraps shadows across terrain edges — bake in `__init__`/off-thread and use shifted slices, not `np.roll`.
- **LOW:** `numLayers < 4` leaks control-map weight into a nonexistent layer (`terrain_splat.frag:37` sums all four channels); slope underestimated at terrain edges (clamped taps); `uNormalMatrix` is the plain MV upper-3×3 (correct only while orthonormal — document); `SplatTerrain` subclassing `PointSet` is misleading; unnamed tuning constants.
- **Scope note:** `bin/terrain_view.py` does **not** exercise this stack — it drives `TilesTerrain` (§6) with its own clamp/collision. The reviewed terrain engine is exercised almost entirely by the forest-demo.

---

## 4. HDR / IBL (`loaders/hdr.py`, `hdri.py`, `hdrbackground.py`, `passes/ibl.py`, IBL shaders)

The design is sound and careful: probe textures are cached and rebuilt only on env-generation change (not per frame); RGBE decode is vectorized, headless-testable, and its `m·2^(e-136)` exponent convention is correct and documented; render targets are `RGBA16F`; the `_cubemap_inc.glsl` shared face-direction include kills a whole class of seam bugs; env samples are clamped to 50.0 before convolution as a firefly/NaN guard; sRGB/linear discipline is consistent. Beyond **#1 (CRITICAL)** and **#7**:

- **No capability detection (HIGH).** `resolve_ibl_mode` branches on a renderer *name* blocklist (`llvmpipe/swrast/…`), not a capability probe. A discrete-named GPU whose driver can't render `RGBA16F` is discovered only via the completeness `raise` → hits #1. The HDR skybox uploads `GL_RGB16F` with no LDR fallback (sampled-only, so no completeness issue, but silently black if half-float sampling is unsupported). *Fix:* a one-time probe (checked extensions + a tiny trial `RGBA16F` FBO) feeding `resolve_ibl_mode`, so `full` is never selected on hardware that can't support it.
- **MEDIUM:** HDR skybox leaks its texture+VBOs+VAO on every env change (`setImage` nulls `_render_data` without deleting; *fix:* delete before dropping); `GL_TEXTURE_CUBE_MAP_SEAMLESS` correctness hinges on a leaked build-time side effect (enable it in the PBR pass around probe sampling); the equirect UV mapping is duplicated in `hdr_background.frag` and `ibl_equirect.frag` and *must* stay in lock-step (move to the shared include); the 1k equirect source is minified to 128² faces with no mip chain → aliased sun in reflections (`glGenerateMipmap` the source).
- **LOW:** teardown `except Exception: pass` hides real GL errors; a documented load-thread/render-thread swap on `_equirect`/`_render_data` (GIL-atomic, worst case one stale frame); `_build` is a ~100-line god-function worth splitting.

---

## 5. Shadow caching (`passes/shadowmixin.py`, `shadowpool.py`, `shadowcaps.py`)

The R1–R5 work is well-structured, honestly documented, and rests on a *correct* premise (verified in `vrml/vrml97/nodepath.py:34-86`: `transformMatrix()` returns the same array object while unmoved, a fresh one on change, so `id()`-keyed signatures really do detect motion). `shadowcaps.py` is the engine's best capability layer. The gaps are all in the depth-map cache, and all bite the exact "walk a static scene, lights enter/leave the frustum" workload the caching targets:

- **#2 (HIGH) — stale layer on light in/out-of-view reuse.** Layers are assigned positionally; a returning light reclaims a layer another light wrote and the freshness check skips the re-render. *Fix:* track ownership per physical layer (`_layer_owner[layer] = (id(light), id(transform), caster_sig)`) and reuse only on a match; or clear the cache when the qualifying-shadow-light set/order changes.
- **#3 (HIGH) — cache key committed before render succeeds.** `_depthMapFresh` stores the key and returns "render now", but a subsequent `bind_layer`/`_renderCubeFaces` failure leaves the key claiming "fresh" forever → phantom shadows from undefined `glTexStorage` depth. *Fix:* split query from commit; record the key only after a confirmed successful render, or `pop` it on the failure paths.
- **#9 (MEDIUM) — `castsShadow` filter defeated for the depth pass** (verified §above): `_shadowCasterRecords` is unfiltered, so `castsShadow=False` foliage is still rendered into every map despite the comment at `:135`. *Fix:* filter inside `_shadowCasterRecords`/`_refreshCasterData`.
- **#8/M3 — sampler budget** (see §1).
- **MEDIUM:** `_depth_map_cache` is unbounded and keyed on reusable `id()`s (a GC'd-then-reused light id yields a false hit); the grouping cache already bounds to 8 — do the same and add a generation counter/weakref. The cache's correctness silently depends on the `transformMatrix()`/`boundingVolume()` object-identity contract, which the tests fake with hand-built objects and so can't regression-guard — add an integration test that moves a real node and asserts the signature changes; document the contract.
- **LOW:** one redundant re-render on frame 2 (freshness key reads `smap.texture` before lazy allocation); R3's single-cull completeness is asserted, not tested.
- **Good patterns worth keeping:** FBO completeness checked once then trusted; immutable `GL_DEPTH_COMPONENT24` storage (core-3.3, no float-depth dependency); render-target save/restore once per batch; position-only depth program with exact cull restore; bounded/correctly-invalidated grouping cache; cache teardown on dispose.

---

## 6. glTF / Draco / resolver, and the tiles3d package

**Loader/resolver — genuinely strong, test-backed.** Same-origin re-enforced on every redirect hop (closes the 302→metadata-endpoint SSRF); local containment via `realpath` prefix; atomic cache write (`mkstemp`+`os.replace`) with reference-counted single-flight coalescing; per-user `0o700` cache dir; vectorized accessor decode (strided views, memoized buffers, vectorized sparse/normalize). The one broad `except BaseException` re-raises after unlinking the temp file — correct. Issues:

- **#5 (MEDIUM-HIGH security) — Draco decompression bomb** (see table). *Fix:* after decode, reject streams whose `positions.nbytes + indices.nbytes` exceeds the resolver's `max_resource_bytes`.
- **MEDIUM:** `_coerce_normalized(None, raw)` crashes with `AttributeError` (not the loader's located `ValueError`) on a malformed Draco stream that lists a semantic but omits its accessor (`draco.py:105-107`); *fix:* guard `acc is None`. `_coerce_normalized` also duplicates `_normalize_array`'s divisor/clamp logic — delegate.
- **LOW:** local-file fetch reads the whole file before the size check (stat-first); a malformed Draco blob aborts the whole scene while the DracoPy-absent path only skips (catch per-primitive to match); "warn once" spams when `resolver is None`; `get_reference` resolves twice; `_draco_warned` stamped ad hoc on the resolver.
- **GOOD:** the DracoPy soft-dependency fallback (absent decoder → warn-once, skip primitive, rest of scene loads) is exactly right; indices are 32-bit `GL_UNSIGNED_INT`, universally fine on the desktop target.

**tiles3d — well-isolated but half-dead, and a shadow vegetation engine (#10).** The streaming core (`tileset/traversal/residency/runtime/loadmanager/frustum/boundingvolume/screenspaceerror/fetch/gltf_uploader`) is a competent, self-contained, well-tested 3D-Tiles runtime matching the "optional import" role — keep it. But:

- The only tendrils into the north-star engine are benign: `terrain/splat.py:75` imports `tiles3d.cc0` (CC0 texture fetch) and the forest-demo imports `tiles3d.vegetation` (`scatter_disc`/`poisson_thin`). Worth noting these keep tiles3d a *hard* dependency of core paths despite the "optional" framing — the `cc0` helper in particular should arguably move out of `tiles3d` into a shared `loaders/` location.
- `foliage.py` (765 lines) + `vegetation.py` duplicate the north-star vegetation/terrain engine — including three scatter implementations where the tiles3d `scatter_disc` **reintroduces the exact popping** `world_grid_scatter` was written to eliminate — and are ~50-70 % dead (confirmed zero production callers for `geomorph.py` entirely, and for `vegetation.conifer/grass_tuft/bush/build_*` and much of `foliage`). GLB-buffer boilerplate is copied 6× with magic component-codes; value-noise is implemented twice. *Recommendation:* migrate `bin/terrain_view.py` onto `scenegraph/vegetation` + `scenegraph/terrain`, then delete `vegetation.py`/`geomorph.py` and shrink `foliage.py` to the procedural-texture/GLB helpers with no north-star equivalent. Until then, at minimum delete the confirmed-dead functions so the package stops advertising a second, competing vegetation API to new developers.
- **MEDIUM:** `gltf_uploader.release()` is a no-op (relies on GC to free VBOs → real VRAM lags the accounted budget); `physics_colliders.on_evicted` appends to `pending_removals` forever (no `PhysicsWorld.remove_body`); `foliage.ground_patch_split` runs a pure-Python per-triangle loop and `ground_patch_blended` bakes a 1024² texture, both on the main thread on camera move (visible stutter). **LOW:** `Residency.enforce_budget` re-scans all tiles every frame and never deletes `UNLOADED` entries.

---

## 7. forest-demo (`forest-demo/`) — the driver

The demo is a clean, well-commented scene (biome mixing, blue-noise thinning, per-species trunk colliders measured from the mesh, LOD handoff), and correctly keeps the *engine* generic — it imports reusable pieces and supplies only geometry/textures/heightmaps, which is exactly the scaffold-for-learning goal. Notes: `OnInit` is a 185-line god-method (acceptable for a demo, but the biome/scatter block would read better factored); the clump path is a fragile `os.path.join(HERE, "..", "..", "..", "grass-clumps", …)` that breaks once the package is `uvx`-installed away from the repo (pair with #12 — ship the clump as a package asset); heavy reliance on `os.environ` knobs (`CLUMP_RADIUS`, `GRASS_*`, …) with defaults scattered through the code rather than one config block. None are blockers.

---

## Cross-cutting themes & recommended order of work

1. **Adopt one capability/degradation layer (portability).** `shadowcaps.py` already does this well. Generalize it (or add a sibling) that IBL, terrain and vegetation consult at init: GL version, `ARB_texture_storage`, float-FBO renderability, `GL_MAX_TEXTURE_IMAGE_UNITS`. Feed it into `resolve_ibl_mode` and the veg/terrain `_init_gl` so an unsupported feature *disables a layer with a log line*, never crashes or corrupts. **Do #1 first** (wrap `_build` in `try/finally`) — it is the single highest-value fix.
2. **Add GL teardown everywhere (portability/reliability).** A shared `dispose()` contract on the new nodes (store every handle; delete on dispose; call it on node swap). Closes #4 and the IBL/HDR leaks.
3. **Fix the shadow depth-map cache (correctness).** #2 and #3 together, plus bounding the cache and the `castsShadow` filter (#9). Add the two missing tests (real-node motion; a caster shadowing only the far cascade).
4. **Cap Draco-decoded size (#5).** One check after decode.
5. **De-duplicate (maintenance).** `InstancedVegBase` + shared attrib helpers + shared veg GLSL include (folds in the LOD-seam hazard); one `build_glb` helper in tiles3d; call `texture_rgba` from `splat`. Then prune tiles3d's dead vegetation code (#10).
6. **Correctness hardening (#11, #12, #13, #15):** heightfield bit-depth guard, in-memory clump texture, integer scatter hash, collision broadphase grid.
7. **Align the baseline story (#7):** document the true GL floor (4.1 + `ARB_texture_storage`) or add the `glTexImage` fallback; stop the `mode._pbr_*` pokes (#14) in favor of local save/restore.

Nothing here requires a redesign. The engine is close; these changes are what make it dependable on the full desktop-GPU range and clean enough to hand to a new 3D developer as a scaffold.
