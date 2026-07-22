# PR Review — `feature/pbr-rendering-experiment`

- **Date:** 2026-07-04
- **Branch under review:** `feature/pbr-rendering-experiment` (12 commits ahead of `master`)
- **Size:** ~15,900 insertions / ~421 deletions across 93 files
- **Reviewer verdict:** **Request changes — not mergeable as a single unit.**

---

## 1. Executive summary

This branch contains a large amount of genuinely capable work: a metallic/roughness
PBR pass, a glTF/GLB loader with broad KHR-extension coverage, a shadow-mapping
subsystem (spot / directional-CSM / omni-cube with PCF/PCSS), transmission, a
GLU-free NURBS teapot, and an automated pytest/visual-regression framework. The
matrix and coordinate-system reasoning is, in most places, careful and correct, and
the code is unusually well commented.

It is **not production-ready and cannot be merged as presented.** The reasons fall
into three buckets:

1. **Scope & process.** One branch named `…-experiment` bundles at least seven
   independent features plus unrelated bug-fixes, with commits literally labelled
   `WIP`, `CHECKPOINT`, and *"performance is pretty bad."* The working tree has also
   drifted **ahead of the committed branch tip** (see §2.1) — so "the PR" is not even
   a well-defined artifact right now.
2. **Correctness blockers that break the default/baseline paths.** The lit shader
   over-subscribes fragment texture units and will fail to link on minimum-spec
   GL 3.3 drivers; shadows default ON with no real depth shader; cube shadows sample
   undefined memory; the glTF loader silently corrupts common conformant models; and
   the flagship "visual regression" test asserts nothing.
3. **Maintainability debt in core files.** `_flat.py` — a permanently-maintained hot
   path — absorbed ~700 lines of a selection subsystem *plus* ~600 lines of dead
   code, and the generic render-pass dispatcher now hard-depends on the experimental
   PBR module.

**Recommendation:** split this into reviewable feature branches, fix the blockers
per subsystem, reconcile the working tree with the commits, then re-review each piece
against the Khronos sample models and the (fixed) regression suite. Detailed,
prioritized findings follow. Line numbers cite the **working-tree** contents the
reviewers read; several differ from the committed tip and must be reconciled first.

### Fairness note — what is good here

- `passes/shadowmath.py` eye-space matrix math, ortho/perspective conventions and CSM
  fit are careful and largely correct.
- glTF handedness, sRGB-flag handling, column-major matrices and metallic/roughness
  defaults are correct; KHR-extension coverage is impressively broad.
- The PBR pass plumbing (per-program uniform value-cache, VAO caching, capability-gated
  transmission) is thoughtfully structured and well documented.
- The **hand-written** GL tests (`test_pbr_rendering.py`, `test_shadow_rendering.py`)
  are genuinely good — they assert real behavior (channel dominance, alpha overlap,
  transmission on/off divergence, per-light shadow fraction, occluder invariance).
- `teapot_nurbs_data.py` uses the public-domain Newell dataset, correctly attributed.
- `scenegraph/transform.py` `MatrixTransform` row-vector→column-major reasoning is sound;
  `light.effectiveRange` attenuation solve is correct; `appearance.py` alphaMode falls
  back cleanly to legacy `transparency`.

---

## Remediation status (updated 2026-07-04)

Complete index of every finding by ID. Legend: ✅ fixed · ⚠️ partial · ❌ open · 🚫 won't-fix
(accepted) · ⏭️ skipped (process). Verified against the working tree. Fixes so far come from
two sessions — **shadow-sampler packing** (2.3) and **PBR frame-perf / material UBO**. Each ID
below links to the full finding in the section of the same number.

**Score:** ✅ 77 fixed · ⚠️ 0 partial · ❌ 0 open · 🚫 8 won't-fix · ⏭️ 0 skipped (of 85 findings).

### §2 Priority 0 — Blockers
- 🚫 **2.1** working tree vs committed branch — won't-fix (accepted): process/reconciliation handled outside this remediation pass
- 🚫 **2.2** one branch bundles ~7 features — won't-fix (accepted): branch-splitting is a process decision, not a code fix
- ✅ **2.3** shader over-subscribes texture units — VRML97 lit path ≤7 units; PBR path renumbered into units 1–3 + 10–15 (max index 15, was 28), disjoint from the shadow block; locked by `test_pbr_texture_units`
- ✅ **2.4** `VRML97ShaderProgram` now compiles `shadow_depth.{vert,frag}`; `use_depth()` binds the position-only program instead of the full lit+shadow shader (validated headlessly)
- ✅ **2.5** cube shadow faces now always bind + clear all six each frame; only the *draw* is skipped for an occluder-free face, so no face keeps undefined (first frame) or stale (caster left the frustum) depth (`test_shadowmixin.TestCubeFaceClearing`)
- ✅ **2.6** glTF `primitive.mode` — strip/fan expanded to triangle lists, points/lines skipped, `_estimate_normals` reshape guarded
- ✅ **2.7** glTF sparse accessors — index/value scatter applied; no-bufferView + no-sparse now raises `NotImplementedError` (never silent zeros)
- ✅ **2.8** test timeout `_kill_process_tree(os.getpid())` SIGKILLs pytest — fixed: routed through the Popen runner that kills the child tree
- ✅ **2.9** "visual regression" never fails on pixels (no-op gate) — fixed: real percentage-diff gate; `visual_diff` now fails the test
- ✅ **2.10** dead selection code removed from `_flat.py` — `shaderSelectRender`, `_createPickFrustum`/`_filterObjectsForPick`, `read_id_buffer`/`lookup_object_id`/`lookup_depth`/`get_path_at`, the `id_buffer`/`depth_buffer` machinery (~290 lines)

### §3 Priority 1 — Major
- ✅ **3.1** BRDF roughness remap — `alphaR = roughness*roughness` (pbr.frag)
- ✅ **3.2** transparent sorting — shared `material_is_transparent` routes BLEND (and legacy transparency) into the back-to-front pass; `PBRMesh.sortKey` no longer always-opaque. Transmissive OPAQUE glass intentionally stays in the opaque bucket for the dedicated transmission pass (which captures the backdrop and sorts back-to-front) rather than the finding's literal transmission→transparent, which would lose that path (`test_pbr_sortkey`)
- ✅ **3.3** GL calls out of `_MeshGPU.__del__` — the finalizer now hands its VAO id to a per-context pending-delete queue (never touches GL); `PBRMesh.flush_pending_deletes` drains it once per frame with the owning context current (`test_pbrmesh_drawstate.TestFinalizerNeverTouchesGL`)
- ✅ **3.4** partial-compile — separate `_ok` flag; a failed/partial compile nulls every program handle (`_clear_programs`) and all `use*`/`use_depth` refuse to bind; shaders deleted after link (`test_shader_compile_guard`)
- ✅ **3.5** `PBRMaterial.doubleSided` honored — `configure_appearance` publishes it to the mesh cull decision (`_wants_cull`)
- ✅ **3.6** dead duplicate `texture()` removed from `pbrmaterial.py`
- ✅ **3.7** glTF path traversal + SSRF — URL loads confined to the document's exact origin (scheme+host+port; `_same_origin`, blocks file://, cross-host, link-local metadata); local loads realpath-confined under the model dir (`_resolve_local`) rejecting `../`/absolute/scheme URIs (`test_gltf_loader.TestSameOriginFetch`/`TestLocalPathConfinement`)
- ✅ **3.8** glTF resource size cap — every fetched/decoded external resource bounded by `DEFAULT_MAX_RESOURCE_BYTES` (256 MiB, overridable) via `_read_capped`/`_check_size`; accessor `count` already bounds-checked against buffer length (3.11) (`test_gltf_loader.TestResourceSizeCap`)
- ✅ **3.9** glTF OPAQUE/MASK no longer made transparent — transparency derived only for BLEND
- ✅ **3.10** glTF interleaved accessors decoded with a strided view (no per-vertex loop)
- ✅ **3.11** glTF count/range validation — accessor reads bounds-checked against buffer length; index-out-of-range and attribute-count mismatch raise located `ValueError`s (`test_gltf_loader.TestAccessorValidation`)
- ✅ **3.12** glTF node recursion — DFS tracks ancestry and rejects a cyclic node graph with a located error instead of stack-overflowing (`test_gltf_loader.TestNodeCycle`)
- ✅ **3.13** per-light shadow fields — `per_light_shadow_settings` derives the pass bias + map resolution from the casting lights (largest wins; resolution applied pre-alloc to avoid 3.16 realloc); fields no longer dead (`test_shadow_per_light`)
- ✅ **3.14** front-face cull removed from the depth pass — open/single-sided casters now write depth; caller's cull state saved/restored
- ✅ **3.15** shadow FBO/texture teardown — `ShadowMapMixin.disposeShadowMaps()` frees every pool (shared depth array, cube-array, per-slot cubes); wired into the pass-swap path in `renderpass` (runs inside OnDraw, context current) so a scenegraph swap / context loss no longer leaks the maps (`test_shadowmixin.TestDisposeShadowMaps`)
- ✅ **3.16** adaptive-cascade — realloc already gone (fixed-size array); the remaining nondeterminism is now defeatable via `OPENGLCONTEXT_SHADOW_CASCADES`, which pins the rendered cascade count and bypasses the fps probe for reproducible reference-image / CI output (`test_shadowmixin.TestEffectiveCascadesEnvOverride`)
- ✅ **3.17** caps no longer advertise unimplemented tiers — dropped the detected-but-unconsumed `has_geometry_layered`/`has_float_color`(VSM)/`has_seamless_cube`/`has_aniso`/`max_array_layers`/`pcf_kernel` and the phantom `directional_technique=='single'`; the retained fields each gate real code (`test_shadowcaps.TestNoPhantomTiers`)
- ✅ **3.18** selection subsystem extracted to `passes/selection.py` as `SelectionMixin` (+ the two FBO classes); `FlatPass(SelectionMixin, SGObserver)`
- ✅ **3.19** dispatcher no longer hard-depends on PBR — `renderpass._core_flatpass_class()` guards the `pbrpass` import and falls back to the base core `FlatPass` on any PBR-chain import fault (`test_core_pass_dispatch`)
- 🚫 **3.20** MRT picking default — won't-fix (accepted): the one-frame pick latency is acceptable for this codebase's usage
- ✅ **3.21** transparent blend factors — coupling to the shader opacity output documented at the boundary; locked by `test_transparent_blend`
- 🚫 **3.22** default backend GLUT→GLFW — won't-fix (accepted): GLFW is the intended default for core profile
- ✅ **3.23** MRT draw-buffer contract now locked — object-id is reserved to location 1 across every shader, colour to location 0, offscreen IBL passes carry no location-1 output, and the selection FBO supplies attachment 1 + both draw buffers; a new shader can't silently break the contract (`test_mrt_draw_buffer_contract`)
- ✅ **3.24** PCF taps follow the filter radius — hard shadows do a cheap 3×3 instead of a fixed 5×5, soft (PCSS) widens to 5×5; spot and CSM share one `pcfArray` radius function (`test_shadow_sampler_packing.TestPCFBounding`; spliced shader re-validated end-to-end by `test_shadow_rendering`)
- ✅ **3.25** `os._exit()` defeats coverage/cleanup — fixed: `flush_and_exit()` saves coverage before the hard exit
- ✅ **3.26** `run_test` process-tree leak — fixed: weak `run_test` now delegates to the Popen path
- ✅ **3.27** pervasive test-harness duplication (two copies) — fixed: conftest imports `TestResult`/`kill_process_tree`/`build_command`/`EventSender` from the package
- ✅ **3.28** ~700-line event-injection subsystem has no real consumer — fixed: genuine interactive test wired; also fixed a latent bug where the injectors never built valid events
- ✅ **3.29** committed test-run artifacts removed — `git rm` of the generated `teapot_regression_{diff,result,reference}.png` + `debug_test.png` (canonical `teapot_regression.png` kept); `.gitignore` now covers `*_diff/_result/_reference.png`, `debug_*.png`, `regression_output*/`, `report.html`, `benchmark_results/`, `.coverage`/`*.coverage.*`, `*.sock` (`test_packaging_metadata`)
- ✅ **3.30** build-system `requires` bumped to `setuptools>=77` so the PEP 639 SPDX `license = "BSD-3-Clause"` expression is accepted (61-76 reject it) (`test_packaging_metadata`)
- ✅ **3.31** `readme = "readme.txt"` — the PyPI long-description is the readme, not the license (`test_packaging_metadata`)

### §4 Priority 2 — Minor
- ✅ **4.1** PBR tangent handling — transforms by `mat3(modelViewMatrix)`, zero-guarded normalize (no NaN with absent tangent)
- ✅ **4.2** transmission capture reads `COLOR_ATTACHMENT0` (not the MRT object-id buffer), saves/restores the read buffer; linear-FBO assumption documented
- ✅ **4.3** per-draw GL state churn + leaked winding — winding/cull tracked on `mode`, redundant GL calls skipped, `reset_draw_state` restores defaults after the geometry loop
- ✅ **4.4** analytic IBL diffuse divided by PI (irradiance vs raw radiance), matching the prefiltered-probe path
- 🚫 **4.5** per-context caches keyed on `id()` — won't-fix (accepted): acceptable given the caches' lifetime in practice
- ✅ **4.6** object-id attachment — transparent/transmissive passes call `disable_object_id_blend()` (indexed `glDisablei(GL_BLEND, 1)`) so the packed id is never blended when MRT picking is active (`test_object_id_blend`)
- ✅ **4.7** per-shape Python overhead — numpy hoisted, per-material early-out, material UBO
- ✅ **4.8** glTF normalized-integer / signed clamping — gated on `accessor.normalized`, signed clamped to -1 via shared `_normalize_array`
- ✅ **4.9** glTF data-URI parsing — `_decode_data_uri` handles base64 and percent-encoded payloads and raises a located error on a malformed (comma-less) URI instead of IndexError (`test_gltf_loader.TestDataUriParsing`)
- ✅ **4.10** glTF scene roots — `_scene_root_indices` tolerates `scene.nodes=None` (no TypeError) and, with no scenes, roots = nodes not referenced as a child (no double-build) (`test_gltf_loader.TestSceneRoots`)
- 🚫 **4.11** glTF PIL/numpy imports — won't-fix (accepted): PIL is already lazy; numpy is a hard project dependency by design
- ✅ **4.12** glTF non-normalized quaternion — normalized before axis/angle extraction
- ✅ **4.13** glTF quadratic children + un-cached decode — children accumulated into one list; buffer bytes memoised per index
- ✅ **4.14** glTF cache path — fetched assets now cache under the per-user app-data dir (`homedirectory.appdatadirectory()/OpenGLContext/gltf_cache`, mode 0700), not the shared world-writable system temp (`test_gltf_loader.TestCacheDir`)
- ✅ **4.15** shadow spot-frustum math — `_renderSpot` now calls shared `shadowmath.spot_light_view_projection` via `_spotViewProjection`
- ✅ **4.16** shadow cube map — `ShadowMapCube` now uses immutable `glTexStorage2D` (one allocation, fast-clear), matching the array path
- ✅ **4.17** shadow bias constants — named `SHADOW_*` module constants; front-cull dropped so offsets no longer over-stack into peter-panning
- ✅ **4.18** shadow direction transform — examined: upper-3×3 + normalize is correct for a *direction of travel* and matches the lit shader's `transform_direction`; inverse-transpose (as literally suggested) would desync shadows from lighting. Locked with a consistency test.
- ✅ **4.19** `_lightInView` normalized frustum planes — verified `self.frustum` is always built `normalize=1` (rendervisitor + flatcompat); locked with a builder test
- ✅ **4.20** `glUniform1ui` hoisted to the module import; `set_object_id` no longer imports per pick-hot-loop call
- ✅ **4.21** `hasMouseMoveHandlers` asks each event manager via `EventManager.hasReceivers()` (dispatcher lookup encapsulated in the events layer; also fixes a latent always-False bug) (`test_mousemove_handlers`)
- ✅ **4.22** teapot render paths collapsed — the pre-generated-mesh backend (two of the five paths) is gone, leaving NURBS legacy + NURBS shader, with GLUT only as an explicit `useGlut` comparison option; the duplicated size-scale block is extracted to `_with_scaled_matrix` (`test_teapot_nurbs`)
- ✅ **4.23** teapot 1.28 MB fallback removed — `teapot_data.py` `git rm`'d; GLU NURBS tessellation is the sole mesh source (the practical hard dep). Follow-on: a shared distance-LOD (`scenegraph/tessellationlod.py`) now tessellates teapot / Sphere / Cone / Cylinder / NURBS surfaces coarser the further the camera, cached per level; level 0 reproduces the pre-LOD look, `OPENGLCONTEXT_LOD=off` disables it; thresholds tuned against measured on-screen pop (`test_tessellationlod`, `test_teapot_nurbs`, `test_quadric_lod`, `test_nurbs_lod`, `test_lod_transitions`)
- ✅ **4.24** teapot tessellation no longer latches on a transient failure — retries up to `_MAX_TESSELLATE_ATTEMPTS` (3) before giving up, so a first-frame no-context error self-heals (`test_teapot_robustness`)
- ✅ **4.25** teapot bounding volume computed from the tessellated vertices (`_mesh_aabb`, size+center scaled by `size`), eyeballed extents kept only as a pre-tessellation fallback (`test_teapot_robustness`)
- ✅ **4.26** packaging license file — `license-files = ["license.txt"]` names the lowercase file explicitly, so it survives setuptools' case-sensitive default glob; verified the built wheel metadata emits `License-File: license.txt` (`test_packaging_metadata.test_license_file_named_explicitly`)
- ✅ **4.27** packaging — MANIFEST.in now `exclude CLAUDE.md` + `prune plans`, keeping AI-workflow / planning docs out of the sdist (`test_packaging_metadata`)
- ✅ **4.28** packaging — added the 3.14 classifier; `requires-python` raised to `>=3.10` to match the numpy 2.1 floor; stale 3.9 classifier dropped (`test_packaging_metadata`)
- 🚫 **4.29** packaging loose/pre-release pins (won't fix — pins intentional)
- ✅ **4.30** `test_all_scripts.py` ~15 copy-paste classes — fixed: one `SCRIPT_CATEGORIES` table + one parametrized test; script list globbed once
- ✅ **4.31** headless-CI viability (skips on unset `$DISPLAY`) — fixed: EGL/OSMesa offscreen counts as a render target; xvfb/EGL guidance documented
- ✅ **4.32** reference images not reproducible cross-GPU — fixed: percentage-tolerance gate (justified) + llvmpipe/software-renderer guidance for byte-stable CI
- ✅ **4.33** wall-clock timing dependence — fixed: `OPENGLCONTEXT_CAPTURE_DELAY` env override + minimum-frame-count handshake (delay is a floor, not the sole signal)
- 🚫 **4.34** `event_injector` stdin/socket fragility — won't-fix (accepted): test-harness-only, not shipped runtime code
- ✅ **4.35** scratch scripts vs load-bearing helpers not separated — fixed: 3 throwaways deleted; 3 real helpers moved to `tests/helpers/`
- ✅ **4.36** no global `--timeout` backstop — fixed: `timeout = 300` ini key (graceful if pytest-timeout absent)
- ✅ **4.37** `print()` instead of `logging` in shipped package — fixed: module loggers in `event_injector.py` / `framebuffer_comparison.py`

### §5 Priority 3 — Nits
- ✅ **5.1** PBR color pipeline — ACES tonemap (already) + accurate piecewise sRGB EOTF: `sRGBToLinear`/`linearToSRGB` replace the `pow(c,2.2)` decode and `pow(c,1/2.2)` encode, so near-black texels/output aren't crushed (`test_pbr_shader_source.TestSRGBPipeline`; re-validated end-to-end by `test_pbr_rendering`)
- ✅ **5.2** PBR misc — `renderer_is_pbr()` caches the env read; `transmission_mode`/appearance cache are per-instance; `GLASS_MIN_OPACITY` named; `draw_uncached` moved out of the shipped node into the perf harness (`test_pbr_misc`)
- ✅ **5.3** shaders — dead `shadowGather` gone; magic shadow constants named (`PCSS_SEARCH_SCALE`/`PCSS_PENUMBRA_SCALE`/`CUBE_BIAS_SCALE`); desktop-GL-3.3-only intent stated in both frag headers. Both shaders re-validated (compile+link) in a real EGL GL context
- ✅ **5.4** shadow — `_validated` defined on the live map classes; cube-face handedness verified/locked (`test_cube_face_handedness`) and documented; `_renderDepth` already restores the saved cull mode, not a literal `GL_BACK`
- ✅ **5.5** core — `Context.getViewport` aliases `getViewPort` (mixed-case call no longer AttributeErrors); base shadow stubs return None explicitly; docstring casing fixed; FPS string unchanged, no test asserts it (`test_viewport_alias`)
- ✅ **5.6** glTF — magic enum `5126` named `_COMPONENT_FLOAT`; decode helpers type-hinted (`-> np.ndarray`); decode-path + validation covered by `test_gltf_loader`
- ✅ **5.7** testing — fixed: dead `pytest_html` stubs removed; thresholds centralized (`PIXEL_DIFF_THRESHOLD`/`MAX_PERCENT_DIFFERENT`); report references images by path instead of base64-embedding

---

## 2. Priority 0 — Blockers (must fix before any merge)

### 2.1 Process: the working tree does not match the committed branch — the PR is undefined
The committed branch tip and the on-disk working tree diverge materially:

- **Untracked source that committed-tree code paths reach for:** `OpenGLContext/passes/ibl.py`,
  `OpenGLContext/hud.py`, and five `shaders/ibl_*.{frag,vert}` are **untracked** (`git status` = `??`).
  The working-tree `pbrpass.py:41` and `_flat.py:750` `import ... ibl`, but those imports and
  the module itself are **not committed**. A clean checkout of the branch tip is missing this code.
- **Uncommitted edits to 5 core files:** `pbrpass.py`, `_flat.py`, `gltf.py`, `shaderpass.py`,
  `pbr.frag` carry ~174 lines of local, uncommitted modifications. The glTF reviewer observed
  the committed diff still has the naive spec/gloss conversion while the tree has a corrected one.

**Why it blocks:** a reviewer/CI cannot know what is actually being proposed; the committed
code and the code that runs are different. **Fix:** decide the intended scope, commit (or stash
out) everything, and ensure `git checkout <tip> && python -c "import OpenGLContext.passes._flat"`
succeeds from clean before requesting review. IBL is not committed and should be dropped from
this PR or landed as its own branch.

### 2.2 Process: one "experiment" branch bundles ~7 features + unrelated fixes with WIP commits
Commits include `WIP Checkpoint…`, `CHECKPOINT … performance is pretty bad`, `CHECKPOINT glTF …
mostly working`. The diff spans PBR, glTF, shadows, transmission, teapot/NURBS, a testing
framework, packaging, **and** unrelated GLUT-font / GLFW-alpha bug-fixes. **Fix:** split into
`feature/shadow-mapping`, `feature/pbr-materials`, `feature/gltf-loader`, `feature/test-harness`,
etc. Each is independently reviewable, testable and revertible; the font/GLFW fixes should land
first as small standalone PRs.

### 2.3 Shader over-subscribes fragment texture units — breaks ALL lit rendering on baseline GL 3.3 ✅ ADDRESSED
*(Independently reported by both the shadow and shader reviewers — high confidence.)*
`shaders/vrml97_lighting.frag:63-83` declares 16 shadow samplers (`shadow2D_0..3`,
`shadowArr_0..3`, `shadowCube_0..3`, `shadow2Draw_0..3`); `passes/shaderpass.py:429-458`
(`init_shadow_samplers`) binds them to units 4–19, plus the material sampler at unit 0 — up to
**20 distinct fragment texture image units**. GL 3.3 core only guarantees
`GL_MAX_TEXTURE_IMAGE_UNITS >= 16` per stage (llvmpipe/Mesa/Intel report exactly 16). The
program then fails to link/validate → **the main lit shader breaks entirely**, not just shadows.
`ShadowCapabilities.max_shadow_lights()` computes against `GL_MAX_COMBINED_…` and is disconnected
from this per-stage cost. **Fix:** pack spot maps into one `sampler2DArrayShadow` and cube maps
into one cube-array (or gate shadow samplers behind a compile-time define so non-shadowed scenes
stay well under 16), and derive `MAX_SHADOW_LIGHTS` from the real `GL_MAX_TEXTURE_IMAGE_UNITS`.

### 2.4 Shadows default ON for the VRML97 path with no depth shader → full-scene re-render per light ✅ ADDRESSED
`passes/flatcore.py:65` defaults `use_shadows` ON. `VRML97ShaderProgram` never compiles a
`depth_program` (only `pbrpass.py:82` does), so `use_depth()` silently falls back to the **full
lit+shadow fragment shader** as the "depth" pass. Every core-profile VRML97 scene now re-renders
all occluders through the entire Phong+shadow shader, once per shadow-casting light per frame,
into a depth-only FBO where color work is discarded — a large, silent perf regression on the
**default** path. **Fix:** compile `shadow_depth.{vert,frag}` for `VRML97ShaderProgram` too, or
default `use_shadows` OFF for the VRML97 pass (as SHADOW-MAPPING.md §8 originally specified).

### 2.5 Cube shadow faces left holding undefined / stale depth ✅ ADDRESSED
*Fixed:* `_renderPoint` now binds + clears every one of the six faces each frame (each
`bind_face` issues the depth `glClear`), and skips only the *draw* when a face has no
caster — so a face never keeps undefined (first frame) or stale (a caster that left the
frustum) depth. Locked by `test_shadowmixin.TestCubeFaceClearing` (all six faces bound with
zero occluders; six binds + six draws with occluders).

`passes/shadowmixin.py:288-308` (`_renderPoint`) skips bind+clear+draw for cube faces with no
occluders this frame, on the false premise that "a face with no occluders is never sampled."
A receiver samples the cube by the light→fragment direction, which can hit any face. Result:
(a) first frame → skipped faces contain the undefined contents of `glTexImage2D(…, None)`; (b)
after a caster leaves a face frustum, that face keeps last frame's depth → phantom shadows that
never clear. **Fix:** always bind+`glClear` all six faces to depth 1.0; skip only the *draw*.

### 2.6 glTF: primitive `mode` ignored — non-triangle topology silently corrupted / crashes ✅ ADDRESSED
`loaders/gltf.py:449-494` never reads `primitive.mode`; every primitive is drawn as an
independent triangle list. TRIANGLE_STRIP/FAN render scrambled; POINTS/LINES render garbage; and
`_estimate_normals` does `idx.reshape(-1,3)` which raises `ValueError` on any count not divisible
by 3, aborting the whole load. This fails on conformant Khronos samples. **Fix:** read
`primitive.mode`, map to the GL primitive, convert strip/fan to a triangle list (or reject with a
clear error), and guard the reshape on `len(idx) % 3`.

### 2.7 glTF: sparse accessors produce silent all-zero / wrong geometry ✅ ADDRESSED
`loaders/gltf.py:180-194` returns `np.zeros(...)` when `bufferView is None` and ignores
`accessor.sparse` entirely on the normal path. A sparse mesh collapses to origin or renders the
un-overridden base data — **silently wrong**, which is worse than the docstring's "not handled."
**Fix:** implement sparse substitution (scatter `sparse.indices`→`sparse.values`) or raise
`NotImplementedError` naming the accessor. Never return zeros silently.

### 2.8 Test harness: a single test timeout SIGKILLs the whole pytest session ✅ ADDRESSED
`tests/conftest.py:187` — on `TimeoutExpired` the fixture calls `_kill_process_tree(os.getpid())`,
i.e. it kills **pytest itself** (psutil path kills the parent; fallback `os.kill(os.getpid(),
SIGKILL)`). One hung GL script (routine on CI) takes down the entire run with no report; the
inline comment ("This won't work well, but we try") shows it shipped known-broken. **Fix:** kill
the real child via the `Popen`-based `run_test_with_popen` path (`proc.pid`), never `os.getpid()`.

### 2.9 Test harness: "visual regression" never fails on pixels ✅ ADDRESSED
`tests/test_all_scripts.py:459` gates on `max_diff <= 255 and percent_different <= 2.0` — but
`max_diff`'s maximum possible value *is* 255, so the clause is a tautology; and the mismatch
branch at `:374-383` is a literal `pass` ("Don't fail just because images differ"). No code path
fails on a pixel difference. The headline feature is a smoke test in a regression costume — a
black frame or wrong color passes as long as the process exits 0. **Fix:** make
`TestVisualRegression` assert `comparison_stats['is_match']` when a reference exists and
`expect_visual_diff` is false; replace the tautological bound; and decide whether pixel-exact
regression is even viable cross-GPU (see 4.4) — if not, delete the machinery rather than ship a
no-op.

### 2.10 Core: ~600 lines of dead code shipped into the `_flat.py` hot path ✅ ADDRESSED
`passes/_flat.py` retains, with **zero call sites** (grep-verified): `shaderSelectRender` (:1186,
superseded by `…Optimized`), `_filterObjectsForPick` (:1336) + its only caller `_createPickFrustum`
(:1277), `read_id_buffer` (:396), `lookup_object_id` (:470), `lookup_depth` (:497), `get_path_at`
(:521), and the `id_buffer`/`depth_buffer` machinery on `SelectionBufferFBO` (permanently `None`
per the author's own comment at :307-315). This inflates the "1400-line change," hides the real
diff, and will rot. **Fix:** delete all of the above; keep only the on-demand `read_pixel` path
actually used.

---

## 3. Priority 1 — Major (fix before merge; correctness / layering / security)

### PBR
- **3.1** **BRDF roughness remap missing** — `shaders/pbr.frag:195-273,336`. GGX/Smith use perceptual
  `roughness` directly; glTF 2.0 requires `alpha = roughness²` before the NDF/geometry terms.
  Every material renders too glossy and will **not match** the Khronos references PBR-MATERIALS.md
  is measured against. *Fix:* `float a = roughness*roughness;` once, feed `a` to `D_GGX`/`G`/clearcoat;
  keep perceptual roughness only for LOD/LUT.
- **3.2** **`sortKey` always returns opaque** — `scenegraph/pbrmesh.py:228-230`. BLEND and transmissive
  PBR shapes batch with opaques and are never depth-sorted; transmission then samples an incomplete
  backdrop. *Fix:* inspect the material and return the transparent tuple for
  `transparency>0 / alphaMode=='BLEND' / transmission>0`.
- **3.3** **GL calls in `__del__`** — ✅ ADDRESSED — `scenegraph/pbrmesh.py`. The finalizer no longer calls
  `glDeleteVertexArrays`; it appends the VAO id to a per-context pending-delete list (obtained via
  `_pending_delete_queue`, held as a plain list so the GPU object never keeps a context alive).
  `PBRMesh.flush_pending_deletes(mode)` — called once per frame from the `_flat` render loop with the
  owning context current — drains the queue and deletes the ids. `release()` (the explicit,
  context-current path) still deletes directly. Locked by `test_pbrmesh_drawstate.TestFinalizerNeverTouchesGL`.
- **3.4** **Partial-compile leaves program half-populated** — `passes/pbrpass.py:66-94`. On a sub-program
  failure it sets `_compiled=True` but leaves some handles `None`, so later `use()`/`use_depth()`
  bind `None` and raise mid-frame far from the cause; linked shader objects are never deleted.
  *Fix:* null all handles on failure (or a separate `_ok` flag), guard every `use*`, delete shaders
  after link.
- **3.5** **`PBRMaterial.doubleSided` is inert** — ✅ ADDRESSED — `pbrmaterial.py:78` + `pbrpass.py:177-215`. Culling is
  driven only by `PBRMesh.solid`; a hand-built `PBRMaterial(doubleSided=True)` still culls. *Fix:*
  honor `material.doubleSided` in `configure_appearance`, or remove the field.
- **3.6** **Dead duplicate `texture()`** — ✅ ADDRESSED — `pbrmaterial.py:127-128`: a second `def texture(self, channel)`
  sits unreachable inside module-level `uv_transform_matrix` (copy-paste). *Fix:* delete.

### glTF (loader consumes untrusted network/file assets)
- **3.7** **Path traversal + arbitrary-scheme URI fetch (local file read / SSRF)** — `gltf.py:150-162`.
  `open(os.path.join(base_dir, unquote(uri)))` allows `uri="../../../etc/passwd"`; `urljoin` with an
  absolute-scheme `uri` fetches `file:///…` or `http://169.254.169.254/…`. *Fix:* `realpath`-confine
  under `base_dir`; allow-list URL schemes; handle `data:` separately.
- **3.8** **Unbounded memory on fetch/decode** — `gltf.py:155-237`, `_read_accessor:188`. `read()` /
  `b64decode` with no ceiling; `np.frombuffer(count=acc.count*ncomp)` is attacker-driven. *Fix:*
  enforce a max-resource-size and validate `count`/`byteLength` against actual buffer length.
- **3.9** **OPAQUE materials made transparent from baseColor alpha** — ✅ ADDRESSED — `gltf.py:431`. Spec says alpha is
  ignored when `alphaMode==OPAQUE`; here `transparency=1-alpha` unconditionally, wrongly routing the
  shape into the transparent pass. *Fix:* derive transparency only for `BLEND`; force 0 for
  OPAQUE/MASK.
- **3.10** **Interleaved (`byteStride`) accessors decoded with a per-vertex Python loop** — ✅ ADDRESSED — `gltf.py:190-193`.
  Seconds of overhead on large GLBs. *Fix:* `np.lib.stride_tricks.as_strided` / structured-dtype view.
- **3.11** **No count/range validation** — `gltf.py:175-194,453-461`. Mismatched attribute counts and
  out-of-range indices yield opaque numpy errors or crashes. *Fix:* validate up front with located
  messages.
- **3.12** **Node recursion has no cycle guard / depth bound** — `gltf.py:598-612`. A cyclic/deep hierarchy
  stack-overflows. *Fix:* visited-set + explicit stack.

### Shadows
- **3.13** **Per-light `shadowBias` / `shadowMapResolution` node fields are dead** — `shadowmixin.py:400-409`
  hardcodes constants; `scenegraph/light.py:122-123,205-206` fields are never read. The documented
  per-light API is a no-op. *Fix:* read and thread the fields, or remove them and the plan claim.
- **3.14** **Unconditional front-face culling breaks single-sided / open geometry** — ✅ ADDRESSED — `shadowmixin.py:479,491`.
  `glCullFace(GL_FRONT)` on every occluder means a ground quad / leaf card / open mesh writes no
  depth → casts no shadow; restore is a hardcoded `GL_BACK`. *Fix:* honor the VRML `solid`/doubleSided
  flag; save/restore the prior cull value.
- **3.15** **No FBO/texture teardown — maps leak on context loss/resize** — ✅ ADDRESSED — `shadowmixin.py`.
  `disposeShadowMaps()` cleans up the shared depth array, the point cube-array and every per-slot cube
  fallback and nulls the pool refs (the pool classes have no finalizer, by design, so GC never touches
  GL). Wired into `renderpass._defaultRenderPasses`: the outgoing cached pass is disposed before it is
  replaced on a scenegraph swap — inside OnDraw, so the context is current. Locked by
  `test_shadowmixin.TestDisposeShadowMaps` (all pools cleaned + nulled; idempotent).
- **3.16** **Adaptive cascade controller in the render hot path forces mid-frame realloc** — ✅ ADDRESSED —
  `shadowmixin.py`. The realloc itself was already eliminated (the shared array is allocated once at the
  full `MAX_CASCADES` size and never resized; the cascade count only governs how many layers are
  rendered). The residual concern — that the fps-adaptive count made output nondeterministic and so
  untestable via reference images — is closed by `OPENGLCONTEXT_SHADOW_CASCADES`, which pins the count
  and bypasses the fps probe entirely; CI/reference runs set it for reproducible shadows. Locked by
  `test_shadowmixin.TestEffectiveCascadesEnvOverride`.
- **3.17** **`shadowcaps.py` advertises tiers that aren't implemented** — ✅ ADDRESSED — `shadowcaps.py`. The
  detected-but-unconsumed capabilities were removed: `has_geometry_layered`, `has_float_color` (VSM),
  `has_seamless_cube`, `has_aniso`, `max_array_layers`, the `pcf_kernel` property and the phantom
  `directional_technique` (whose `'single'` branch no code path implements). The remaining fields
  (`has_texture_gather`, `has_cube_shadow`, `has_cube_array`, `has_depth_clamp`, `max_texture_units`,
  `total_vram_mb`, `point_technique`) each gate real code. Locked by `test_shadowcaps.TestNoPhantomTiers`.

### Core rendering
- **3.18** **Selection subsystem belongs in its own module** — ✅ ADDRESSED — `_flat.py:19-532` + `:1226-1817`. ~700 live
  lines of `SelectionFBO`/`SelectionBufferFBO`/MRT-pick/screen-space-bbox got inlined into the base
  pass, while shadows and PBR were correctly extracted. *Fix:* move to `passes/selection.py` as a
  `SelectionMixin` (mirroring `ShadowMapMixin`); move transmission bits into a `TransmissionMixin`.
- **3.19** **Generic dispatcher hard-depends on the experimental PBR module** — `renderpass.py:858-867`.
  The `profile=='core'` branch does an unconditional `from …pbrpass import renderer_is_pbr`; `pbrpass`
  imports `pbrmaterial`/`transmission`/`flatcore` at module top with no guard. Any import-time fault
  in the PBR chain breaks core rendering **for every user**, PBR or not. *Fix:* guard the import
  (fallback `renderer_is_pbr = lambda: False`); better, register renderers via a lookup table so
  `renderpass` never names `pbrpass`.
- **3.20** **MRT picking silently becomes the default** — `_flat.py:565` (`use_mrt_selection=True`),
  `:1878-1899`. Introduces one-frame pick latency + an FBO/blit for every existing core-profile app;
  pick-then-act in one event cascade may read last frame's object. *Fix:* default OFF (opt-in) or
  document the latency contract and add a scene-mutation pick-correctness regression test.
- **3.21** **Transparent blend factors swapped** — ✅ ADDRESSED — `_flat.py:773` (`GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA`
  vs master's reverse), coupled to a redefinition of the shader alpha output. A partial revert /
  stale shader cache inverts transparency for **all** legacy VRML97 transparent geometry. *Fix:* add
  a transparent-VRML97 visual-regression assertion and comment the opacity-vs-transparency change at
  the shader boundary.
- **3.22** **Default backend flipped GLUT → GLFW** — `context.py:1002`. Behavioral change to a public entry
  path; may regress GLUT-only/headless environments. *Fix:* call out in release notes; consider GLFW
  only when confirmed importable, else fall back to GLUT.

### Shaders
- **3.23** **All five existing shaders switched to MRT dual-output** — ✅ ADDRESSED — the shaders (now seven:
  lighting/point/unlit/background/vertex_color/line + pbr) each write `layout(location=1) out vec4
  fragObjectId`. The contract is now locked by `test_mrt_draw_buffer_contract`: object-id is reserved to
  location 1 across *every* fragment shader (a new shader can't repurpose that slot and silently lose the
  write on a single-attachment target), colour is always location 0, the offscreen IBL bake passes carry
  no location-1 output (single-attachment FBOs), and the MRT selection FBO creates attachment 1 + enables
  both draw buffers. On the ordinary on-screen non-MRT path, draw buffer 1 is `GL_NONE` per spec, so the
  id write is harmlessly discarded.
- **3.24** **Fixed 5×5 PCF regardless of hardness; `pcfRadius()` ignored on the spot path** — ✅ ADDRESSED —
  `shaders/_shadow_inc.glsl`. `pcfArray` now derives its integer tap radius from the requested filter
  radius (`r = clamp(ceil(radiusTexels*0.5), 1, 2)`), so a hard shadow does a 3×3 (9 taps) and only a
  genuinely soft PCSS shadow widens to 5×5 — instead of a fixed 25 taps regardless of hardness. The spot
  and CSM paths both funnel through this one function (CSM's inline 25-tap loop is gone). The default
  (hard) path drops from 25→9 taps/light. Locked by `test_shadow_sampler_packing.TestPCFBounding`; the
  spliced shader still compiles/links/renders end-to-end (`test_shadow_rendering`).

### Testing framework
- **3.25** **`os._exit()` defeats coverage and cleanup** — ✅ ADDRESSED (`process_exit.flush_and_exit`) — `framebuffer_comparison.py:422-473`,
  `event_injector.py:378`. Skips `atexit`, so coverage.py never flushes — this is *why*
  PROJECT-PLAN reports ~9% coverage. *Fix:* `sys.exit()` (or flush coverage explicitly) except in
  genuine post-fork cases.
- **3.26** **`run_test()` leaks the process tree on timeout** — ✅ ADDRESSED (`run_test` delegates to `run_test_with_popen`) — `subprocess_runner.py:185-208`.
  `subprocess.run` kills only the direct child (the `coverage` wrapper), orphaning the GL grandchild
  → zombie GLFW/GLUT windows accumulate on CI. *Fix:* route all timeout-prone execution through the
  `Popen` path + `kill_process_tree(proc.pid)`; delete the weaker `run_test`.
- **3.27** **Pervasive harness duplication** — ✅ ADDRESSED (conftest imports the package as the single source) — `EventSender`, `_kill_process_tree`, `_build_coverage_command`,
  the image-compare math and the result dataclass each exist in two places (conftest vs the
  `OpenGLContext.testing` package). The `os.getpid()` blocker lives in one copy but not the other —
  exactly how such bugs are born. *Fix:* collapse onto the `OpenGLContext.testing` package as the
  single source; have conftest import it.
- **3.28** **~700-line event-injection subsystem has no real consumer** — ✅ ADDRESSED — `event_injector.py` + the
  `interactive_runner`/`event_sender`/`visual_regression_runner` fixtures are used only by
  `test_testing_infrastructure.py` (tests the infra against itself). *Fix:* wire at least one genuine
  interactive test through it, or delete it.
  *Done:* `tests/test_event_injection_interactive.py` drives a real EventInjectionMixin context end
  to end (socket → injector → event manager → bound handler). Wiring it surfaced a latent bug: the
  injectors passed constructor kwargs the Event API rejects and called managers wrong, so **no
  injected event had ever reached a handler** — fixed to build events attribute-by-attribute and
  dispatch via `ProcessEvent`; keyboard now also raises `keypress`. Fast GL-free unit tests lock the
  dispatch logic; the end-to-end test skips (not fails) only if the GL app can't start.
- **3.29** **Committed test-run OUTPUT artifacts** — `tests/reference_images/teapot_regression_diff.png`,
  `_result.png`, `debug_test.png` are generated outputs, not fixtures; the repo also carries
  `report.html`, `benchmark_results/`, `regression_output*/`. The branch `.gitignore` ignores none
  of them. *Fix:* delete the `_diff`/`_result`/`debug` PNGs, keep one canonical baseline, and add
  `.gitignore` entries for the output dirs / `*.coverage.*` / `*.sock`.

### Packaging
- **3.30** **`license = "BSD-3-Clause"` (SPDX) needs setuptools≥77 but build-system pins ≥61** —
  `pyproject.toml:9` vs `:2`. PEP 639 string form is rejected by setuptools 61–76. This also
  **reverts** deliberate master commit `4a0834d` ("Remove BSD license declaration that makes modern
  pip/uv upset"). *Fix:* bump `requires = ["setuptools>=77","wheel"]`, or use the pre-639 table form;
  coordinate with the maintainer given the prior removal.
- **3.31** **`readme = "license.txt"`** — `pyproject.toml:8` makes the PyPI long-description render the license,
  ignoring the existing `readme.txt`. *Fix:* `readme = "readme.txt"`.

---

## 4. Priority 2 — Minor (should fix; robustness / perf / clarity)

- **4.1** **PBR tangent handling** — ✅ ADDRESSED — `pbr.vert:26`: `normalize(normalMatrix*aTangent.xyz)` NaNs when no
  tangent attribute (loc 3 = 0) and uses the wrong matrix (should be `mat3(modelViewMatrix)`); the
  fragment `length>0` guard survives only because `NaN>0` is false. *Fix:* `hasTangent` flag; correct
  matrix.
- **4.2** **Transmission read-buffer / color-space coupling** — ✅ ADDRESSED — `transmission.py:82-87`: `glCopyTexSubImage2D`
  copies the current read buffer; under MRT nothing forces `COLOR_ATTACHMENT0`, so it may capture the
  object-id buffer. *Fix:* `glReadBuffer(GL_COLOR_ATTACHMENT0)` save/restore; document the non-sRGB FBO
  assumption.
- **4.3** **Per-draw GL state churn + leaked winding** — ✅ ADDRESSED — `pbrmesh.py:193-198` issues `glFrontFace`/cull every
  draw and leaves state changed on pass exit. *Fix:* track state on `mode`, skip no-ops, restore at
  pass end. (Mirror finding in analytic ambient below.)
- **4.4** **Analytic IBL diffuse too bright** — ✅ ADDRESSED — `pbr.frag:379-385`: raw radiance used as pre-integrated
  irradiance (no `/PI`), so `analytic` ≠ `full`. *Fix:* scale/integrate the approximation.
- **4.5** **Per-context caches keyed on `id()`** — `pbrmaterial.py:31-40` (`PBRTexture.cached`): `id()` reuse
  after GC can bind a dead texture; no release path. *Fix:* key on a stable per-context token; release
  through it.
- **4.6** **Blend on the object-id attachment** — `pbr.frag:406-434`: transmissive/BLEND fragments write
  `fragObjectId`; global blend corrupts picking behind transparent PBR. *Fix:* per-attachment blend
  disable, or write id only for opaque fragments.
- **4.7** **Per-shape Python overhead** — `pbrpass.py:137-159`: `import numpy` inside the per-shape method;
  ~19 uniforms re-boxed every shape with no per-material identity short-circuit. *Fix:* hoist the
  import; early-out when the material is unchanged.
- **4.8** **glTF normalized-integer / signed clamping** — ✅ ADDRESSED — `gltf.py:202-222` ignores `accessor.normalized`
  and omits `max(v/MAX,-1.0)` for signed types; logic duplicated across two helpers. *Fix:* gate on
  `normalized`, clamp signed, factor a shared helper.
- **4.9** **glTF data-URI parsing fragile** — `gltf.py:171,237`: `split(',',1)[1]` `IndexError`s on malformed
  URIs; only base64 handled. *Fix:* parse the media-type/`;base64` prefix; handle percent-encoded form.
- **4.10** **glTF empty/duplicate scene roots** — `gltf.py:615-618`: `scene.nodes` may be `None`
  (`TypeError`); the no-scenes fallback builds child nodes twice. *Fix:* default to `[]`; compute true
  roots.
- **4.11** **glTF PIL unguarded, numpy hard at import** — `gltf.py:24,226`: inconsistent with the "optional dep,
  clear error" contract used for pygltflib. *Fix:* guard PIL, or declare numpy/PIL hard deps.
- **4.12** **glTF non-normalized quaternion** — ✅ ADDRESSED — `gltf.py:522-529`: axis/angle wrong for slightly non-unit
  rotations. *Fix:* normalize `q` first.
- **4.13** **glTF quadratic children rebuild + un-cached buffer decode** — ✅ ADDRESSED — `gltf.py:165-172,606-618`. *Fix:*
  accumulate into a local list; cache decoded bytes by buffer index.
- **4.14** **glTF predictable world-writable cache path** — `gltf.py:563-576`: `tempdir/oglc_gltf_cache` sha1
  name, poisonable on multi-user hosts. *Fix:* per-user `~/.cache`; verify + bound.
- **4.15** **Shadow: duplicated spot-frustum math** — ✅ ADDRESSED — `shadowmixin.py:223-227` vs `shadowmath.py:91-109`
  (`spot_light_view_projection` is dead). *Fix:* call the shared function.
- **4.16** **Shadow: `ShadowMap2D` uses mutable `glTexImage2D`** — ✅ ADDRESSED — `shadowmap.py:77-81`, contradicting the
  array's own `glTexStorage3D` fast-clear rationale. *Fix:* `glTexStorage2D`.
- **4.17** **Shadow: bias over-stacking / magic numbers** — ✅ ADDRESSED — `shadowmixin.py:401,405,478` + frag `:141,164,218`
  — constant bias + slope offset + normal offset + front-cull all push the same way → peter-panning.
  *Fix:* name the constants; pick one primary acne control; tune against acne/peter-panning tests.
- **4.18** **Shadow: direction transform ignores non-uniform scale** — ✅ ADDRESSED — `shadowmixin.py:417-421` (upper-3×3).
  *Fix:* inverse-transpose for direction vectors.
- **4.19** **Shadow: `_lightInView` assumes normalized frustum planes** — `shadowmixin.py:358-362`. *Fix:*
  normalize planes (or divide by normal length).
- **4.20** **Core: per-draw `import` in `set_object_id`** — `shaderpass.py`: re-imports `glUniform1ui` every
  call in the warm-pick hot loop. *Fix:* hoist to module scope.
- **4.21** **Core: `hasMouseMoveHandlers` scans the global dispatcher registry** — `context.py:807-826`,
  reaching into pydispatch internals. Cached per-frame, but fragile. *Fix:* query the relevant event
  managers; pin with a unit test.
- **4.22** **Teapot: five near-duplicate render paths + verbatim scale block** — ✅ ADDRESSED — `teapot.py`. The
  two pre-generated-mesh paths are removed with the fallback (see 4.23); the remaining paths are NURBS
  legacy + NURBS shader, plus GLUT kept solely as an explicit `useGlut` comparison option (no longer an
  automatic fallback). The duplicated size-scale-matrix block is extracted to `_with_scaled_matrix`.
  Locked by `test_teapot_nurbs` (render-dispatch cases rewritten for the new chain).
- **4.23** **Teapot: 1.28 MB `teapot_data.py` fallback is dead weight** — ✅ ADDRESSED — `teapot_data.py` was
  `git rm`'d and every `_pregenerated*` / `_pg_*` path deleted; GLU NURBS tessellation is the sole mesh
  source (the practical hard dependency, and it runs end-to-end in this environment).
  *Follow-on (user-requested):* a shared **distance level-of-detail** mechanism,
  `scenegraph/tessellationlod.py`, picks a tessellation resolution from the eye-space camera distance
  normalized by object radius (scale-invariant, no projection/viewport math). It is wired into the
  teapot (GLU U/V step per level), the quadrics Sphere/Cone/Cylinder (angular `phi` per level), and
  NURBS surfaces (`_SurfaceRenderer`, GLU step per level), each caching one mesh per level.
  `OPENGLCONTEXT_LOD=off` (set for the visual-regression capture env) forces full detail for
  deterministic references. Distance thresholds (`tessellationlod.DEFAULT_THRESHOLDS` = 14/26/50
  object-radii) govern *when* a switch happens. Covered by `test_tessellationlod`, `test_quadric_lod`,
  `test_nurbs_lod`, the teapot LOD cases in `test_teapot_nurbs`, and re-validated end-to-end by the
  sphere/nurbs/teapot script tests. A demo, `tests/lod_demo.py`, dollies the camera through the levels
  in wireframe with a console level readout.

  Getting the quadric LOD *quality* right took several rounds against real
  renders and exposed a subtler bug class than the finding:
  - **Off-by-one closure gap** -- coarser levels scaled the angular step (phi) to
    an arbitrary value, so `arange(0, period, phi)` fell short of pi / 2*pi and
    left a missing pole cap / seam wedge that grew with the level. Fixed by
    snapping phi to `period / round(...)` (an exact integer division), so the mesh
    always closes. Guarded precisely by `test_quadric_lod.TestClosure`.
  - **Silhouette pop** -- a UV quadric's outline *is* its slice count, so any
    visible drop reads as the edge turning polygonal (an octagon). The old
    pi/6 default (a 12-gon) was already too coarse to hide any step. Fixed per the
    maintainer's call ("raise base + gentle steps"): the sphere base is now pi/12
    (a smooth 24-gon) and the LOD steps down gently (24->20->16->12-gon) with a
    "stays round" floor (`LOD_MIN_STEPS`, never a tetrahedron). Measured
    object-pop dropped from ~75% (a mesh-halving schedule) to ~2% near / ~14% at
    the farthest switch.
  - **Ineffectual pop test** -- the first `test_lod_transitions` measured the jump
    as a fraction of the whole frame at the (tiny) threshold distance, so it
    couldn't tell a smooth coarse sphere from one with a hole. Rewritten to
    measure the fraction of the *object's own pixels* that change, rendered large,
    from side AND end-on views (the objects aren't viewpoint-aligned, so the pole
    / end-cap gaps only show axis-on), with the light pinned to a fixed eye-space
    frame (a stale-modelview light had been injecting lighting noise into the
    metric). It now fails loudly on a mesh-halving schedule and on a sphere gap.
- **4.24** **Teapot: tessellation failure latched permanently** — a transient no-current-context error at first
  render disables NURBS process-wide. *Fix:* don't latch on transient exceptions; retry next render.
- **4.25** **Teapot: eyeballed / swapped bounding volume** — `teapot.py:418-430` (`[2.0,1.55,3.15]`→
  `[3.0,1.6,2.0]`), risks frustum-culling the visible teapot. *Fix:* compute the AABB from the
  tessellated vertices (already in memory).
- **4.26** **Packaging: license file omitted from wheel metadata** — ✅ ADDRESSED — `pyproject.toml` now sets
  `license-files = ["license.txt"]` (PEP 639), naming the lowercase file that setuptools' case-sensitive
  default `LICEN[CS]E*` glob would otherwise skip. Confirmed against the actual build backend: the
  generated `*.dist-info/METADATA` emits `License-File: license.txt`. Locked by
  `test_packaging_metadata.test_license_file_named_explicitly`.
- **4.27** **Packaging: AI-workflow docs in the sdist** — top-level `CLAUDE.md` + `plans/` ship in the source
  tarball. *Fix:* prune via MANIFEST.in, or move under a dev-only path.
- **4.28** **Packaging: classifiers stop at 3.13 despite a 3.14 fix; `requires-python>=3.9` vs `numpy>=2.0`**
  (numpy 2.1 dropped 3.9). *Fix:* add the 3.14 classifier; align the Python floor with the
  modernization plan and the numpy floor.
- 🚫 **4.29** **Packaging: loose/pre-release pins** — PyVRML97/pydispatcher/simpleparse unbounded; `TTFQuery>=2.0.1a1`
  pins an alpha. *Fix:* add minimum versions; confirm the alpha is intentional/reachable.
  *Won't fix (accepted):* the unbounded/pre-release pins are intentional — these are co-developed
  sibling packages tracked at their latest, and the TTFQuery alpha is the reachable release.
- **4.30** **Testing: 1285-line `test_all_scripts.py` is ~15 copy-paste classes** — ✅ ADDRESSED (one `SCRIPT_CATEGORIES` table + one parametrized `TestScriptCategories`; list globbed once) — re-globbing per parametrize,
  with a hardcoded allowlist. *Fix:* single category→scripts→timeout table + one parametrized test;
  compute the script list once.
- **4.31** **Testing: headless-CI viability** — ✅ ADDRESSED (EGL/OSMesa offscreen recognized as a render target; xvfb/EGL guidance in CLAUDE.md) — the whole visual suite skips when `$DISPLAY` is unset
  (`test_all_scripts.py:626`); no xvfb/EGL guidance → green-because-skipped. *Fix:* require xvfb-run /
  offscreen EGL in CI.
- **4.32** **Testing: reference images not reproducible** — ✅ ADDRESSED (percentage-tolerance gate + documented llvmpipe/software-renderer path for byte-stable CI) — captured from the submitter's GPU via
  `glReadPixels`; cross-vendor rasterization/AA/gamma differ. *Fix:* pin a software renderer (llvmpipe)
  in CI, or use a perceptual/SSIM metric with a justified tolerance, or structural assertions.
- **4.33** **Testing: wall-clock timing dependence** — ✅ ADDRESSED (`OPENGLCONTEXT_CAPTURE_DELAY` env override + minimum-frame-count handshake; interactive test retries injection over a window) — `DEFAULT_CAPTURE_DELAY=0.5s`, fixed-`wait` event sends.
  *Fix:* prefer frame-count/readiness handshakes; make delays configurable/generous on CI.
- **4.34** **Testing: `event_injector` stdin/socket fragility** — nonblocking `sys.stdin.read`, deprecated
  `tempfile.mktemp`, AF_UNIX path-length. *Fix:* `os.read` + decode; `mkdtemp()` + short socket name.
- **4.35** **Testing: scratch scripts** — ✅ ADDRESSED (3 throwaways deleted; `_pbr_capture`/`_pbr_perf_harness`/`_shadow_capture` moved to `tests/helpers/`) — `_demo_perf.py`, `_pbr_profile.py`, `_shadow_perf.py` are referenced
  by nothing; `_pbr_capture.py`/`_pbr_perf_harness.py`/`_shadow_capture.py` ARE load-bearing subprocess
  helpers. *Fix:* delete the three throwaways; move the three real helpers to `tests/helpers/` (outside
  the `test_*` glob).
- **4.36** **Testing: `pytest-timeout` declared but no global `--timeout`** — ✅ ADDRESSED (`timeout = 300` ini key; graceful when the plugin is absent) — *Fix:* add a backstop timeout in
  `addopts` so a hang can't wedge the session regardless of the custom runner.
- **4.37** **Library uses `print()` instead of the project's `logging` convention** — ✅ ADDRESSED (module loggers in `event_injector.py`/`framebuffer_comparison.py`; `subprocess_runner.print_summary` kept as a deliberate console reporter) — 9 `print()` in the shipped
  `OpenGLContext.testing` package (e.g. `event_injector.py`, `framebuffer_comparison.py`,
  `report_generator.py`); the project already standardizes on `logging.getLogger` elsewhere. *Fix:*
  use module loggers.

---

## 5. Priority 3 — Nits (address opportunistically)

- **5.1** **PBR color pipeline** — ✅ ADDRESSED — `pbr.frag`. The ACES tone-map was already in place (replacing
  Reinhard); this adds the accurate piecewise sRGB transfer functions `sRGBToLinear` / `linearToSRGB`,
  used for texture decode (`toLinear` now routes through `sRGBToLinear`) and the final frame encode
  (replacing both `pow(c,2.2)` and `pow(c,1/2.2)`). The piecewise curve has the correct linear toe near
  black, so dark base-colour/emissive texels and dark output aren't crushed the way the gamma-2.2
  shortcut crushes them. Locked by `test_pbr_shader_source.TestSRGBPipeline`; re-validated end-to-end by
  `test_pbr_rendering`.
- **5.2** **PBR misc** — `renderer_is_pbr()` re-reads the env var each call; `transmission_mode` is a mutable
  class attribute; `draw_uncached` (test-only) ships in the production node; several methods lack
  docstrings; magic constants (`300.0/3000.0`, `0.08`, `1e-3`). *Fix:* cache env; instance attribute;
  fence test code; docstrings; name constants.
- **5.3** **Shaders** — dead `uniform bool shadowGather` (`vrml97_lighting.frag:63`); magic shadow constants
  (`300.0/3000.0`, `shadowBias*2.0`); desktop-only `#version 330 core` with no GLSL-ES path (fine if
  intended — state it).
- **5.4** **Shadow** — cube-face view handedness unverified vs GL's left-handed cube convention
  (`shadowmath.py:201-215`); `ShadowMap2D._validated` referenced in `cleanup()` but never defined;
  `_renderDepth` restores a literal `GL_BACK` rather than the saved value.
- **5.5** **Core** — `getViewport` vs `getViewPort` both used in one method (typo trap); `renderShadowMaps`/
  `bindShadowUniforms` base stubs have empty bodies (add `return None` + a comment); framecounter FPS
  string changed `fps avg:`→`fps:` (flag to any test asserting the exact string).
- **5.6** **glTF** — magic GL enum `5126` compared inline; missing decode-path unit tests (CLAUDE.md mandates
  coverage); absent type hints/docstrings on decode helpers.
- **5.7** **Testing** — ✅ ADDRESSED (dead `pytest_html` stubs removed; thresholds centralized in `test_all_scripts`; report references images by path, not base64) — `report_generator.py:482-489` dead `pytest_html` stubs; four different "different-pixel"
  thresholds (`0.02` vs `5`) — centralize one constant; base64-embedded images balloon `report.html`.

---

## 6. Recommended path forward

1. **Reconcile the tree with the commits** (§2.1): commit or drop the untracked IBL/HUD work; ensure a
   clean checkout imports and the committed diff *is* the proposal.
2. **Split the branch** (§2.2) into: `font/GLFW fixes` (land first), `test-harness`, `shadow-mapping`,
   `pbr-materials`, `gltf-loader`, `teapot-nurbs`, `packaging`. Review and merge independently.
3. **Fix the P0 blockers per subsystem**, then re-validate:
   - Shaders/shadows: the 16-unit budget (2.3) and cube-clear (2.5) on a real 16-unit driver
     (llvmpipe) before anything else.
   - glTF: primitive mode (2.6) + sparse (2.7) against the Khronos sample set.
   - Test harness: the timeout-kill (2.8) and the tautological gate (2.9) — until fixed, the suite
     cannot gate merges.
4. **Delete the dead code** (2.10) and **extract the selection/transmission mixins** (§3 core) so
   `_flat.py` shrinks back to an orchestration file, and **guard the `renderpass`→`pbrpass` coupling**.
5. **Decide the regression strategy** (4.4): a pinned software renderer or a perceptual metric — do
   not rely on byte-committed GPU-specific references.

Once the P0s are closed and P1s addressed per split PR, this is strong, mergeable work.

---

*Reviewers: six parallel subsystem passes (PBR core, glTF, shadows, core rendering, test harness,
shaders/teapot/packaging), synthesized 2026-07-04. The 16-unit texture blocker (2.3) was reported
independently by two passes. Add an entry for this file to `plans/PROJECT-PLAN.md` per project
convention.*
