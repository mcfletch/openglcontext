# OpenGLContext Critical Code Review

**Date:** 2026-07-13
**Scope:** Shaders, rendering passes, geometry & material classes (VRML97 + glTF/PBR), the glTF/asset loaders, and the test suite.
**Method:** Five parallel per-area analyses synthesized and then independently re-verified against source. Every headline claim below was checked by reading the cited lines; findings that could not be confirmed were dropped.

This review deliberately supersedes the January 2026 review's focus on tooling/CI/packaging (most of which — `pyproject.toml`, CI, ruff — is now in place) and goes to the code itself.

---

## Remediation progress (2026-07-13)

Two tables track **every** finding in this review. First: the ranked top issues (0–12) — all fixed, one theme (≈ one "Area") per branch, Red/Green TDD, off-screen GL; each row links to its per-finding writeup. Second (**All other findings**): every additional item raised in the §2–§7 narrative, with status — mostly ⬜ Backlog, a couple 🟡 Partial, and ℹ️ Info for the "not-a-problem" notes; each row links to the section that discusses it.

| # | Severity | Area | Finding | Status | Branch | Details |
|---|----------|------|---------|--------|--------|---------|
| 0 | **CRITICAL** | correctness | Python-2 `long()`/`cmp()` remnants crash the transparent/pick path | ✅ Done | `fix/passes-py2-remnants` | [details](#finding-0) |
| 1 | **CRITICAL** | security | `loader.py` unrestricted URL fetch + arbitrary local-file open (SSRF / disclosure / disk-DoS) | ✅ Done | `fix/loaders-security` | [details](#finding-1) |
| 2 | **CRITICAL** | security | `gzpickle.py` `pickle.load` on scene data = RCE | ✅ Done | `fix/remove-gzpickle` | [details](#finding-2) |
| 3 | **HIGH** | perf | `shadergeometry.py` per-frame VAO gen+delete (IFS/Sphere/Cone/Cylinder/Box/gear) | ✅ Done | `fix/geometry-gpu-churn` | [details](#finding-3) |
| 4 | **HIGH** | perf | `PointSet` rebuilds & re-uploads its GPU buffer every frame | ✅ Done | `fix/geometry-gpu-churn` | [details](#finding-4) |
| 5 | **HIGH** | perf | `IndexedLineSet` gen/upload/delete a VBO per polyline per frame | ✅ Done | `fix/geometry-gpu-churn` | [details](#finding-5) |
| 6 | **HIGH** | correctness | `IndexedPolygons` has no shader path (silently blank under core profile) | ✅ Done | `fix/geometry-gpu-churn` | [details](#finding-6) |
| 7 | **HIGH** | correctness | VRML97 two-sided lighting flip + attenuation divide guard missing | ✅ Done | `fix/shaders-twosided` | [details](#finding-7) |
| 8 | **HIGH** | correctness | `obj.py` material/texture path broken on Python 3 (`md5(str)`, `basejoin`) | ✅ Done | `fix/loaders-security` | [details](#finding-8) |
| 9 | **HIGH** | perf/CPU | `indexedfaceset.py` double tessellation (first result discarded) | ✅ Done | `fix/geometry-gpu-churn` | [details](#finding-9) |
| 10 | **HIGH** | test | ~114 GL scripts launched as subprocesses 2–3× per pytest run | ✅ Done | `fix/test-suite-dedup` | [details](#finding-10) |
| 11 | **HIGH** | test | Drifted `_check_display_available` → visual regressions false-skip (green) on headless CI | ✅ Done | `fix/test-suite-dedup` | [details](#finding-11) |
| 12 | **MEDIUM** | security | glTF same-origin check bypassable via HTTP redirect | ✅ Done | `fix/gltf-redirect-ssrf` | [details](#finding-12) |

### All other findings (§2–§7 narrative)

Beyond the ranked table above, the review body raises these. None are yet fixed except where noted; refs link to the section that discusses them.

| Ref | Severity | Area | Finding | Status | Section |
|-----|----------|------|---------|--------|---------|
| §1a | — | perf | Hoist ~16 in-function `numpy`/`ctypes` imports out of hot paths | ✅ Done | [§1](#sec-1) |
| §2a | MEDIUM | shaders | `vrml97_vertex_color.frag` duplicates the lighting model (and has **no shadow support**); fold onto `_lights_inc.glsl` | ✅ Done (shared `_vrml97_lighting_inc.glsl`; vertex-colour geometry now receives shadows) | [§2](#sec-2) |
| §2b | MEDIUM | shaders | `encodeObjectId` hand-inlined in 4 shaders; use the shared helper | ✅ Done | [§2](#sec-2) |
| §2c | MEDIUM | docs | Stale std140-size comments (`pbr.frag:72`, `pbrpass.py:141,617` say 192 B; actual 224 B) | ✅ Done | [§2](#sec-2) |
| §2d | LOW | dead-code | `shaders/generator.py` dead & broken (`KeyError` template); delete | ✅ Done | [§2](#sec-2) |
| §2e | LOW | perf | Per-vertex 4×4 `inverse` in `pbr.vert`/`vrml97_lighting.vert`; use cheaper normal matrix | ✅ Done | [§2](#sec-2) |
| §3a | **CRITICAL** | correctness | `OverallPass.__call__` can `AttributeError` on `self.visibleChange`; add class default | ✅ Done | [§3](#sec-3) |
| §3b | **CRITICAL** | correctness | `addTransparent` is a silent no-op that **drops** transparent geometry (`_flat.py:1353`) | ✅ Done | [§3](#sec-3) |
| §3c | **CRITICAL** | perf | NURBS per-frame VAO/VBO churn (`nurbs.py:490-544`) — same anti-pattern as #4/#5 | ✅ Done | [§3](#sec-3) |
| §3d | **HIGH** | correctness | Spot/point shadow near-far fit uses the camera-culled occluder set → shadow pops | ✅ Done | [§3](#sec-3) |
| §3e | **HIGH** | robustness | One shared `try/except` around six shader compiles takes down the whole shader system | ✅ Done | [§3](#sec-3) |
| §3f | **HIGH** | observability | Silent per-frame exception swallowing to stderr (`renderpass.py:677`); route to logging | ✅ Done | [§3](#sec-3) |
| §3g | **HIGH** | correctness | Class-attribute mutation (`frustumCulling`) leaks across contexts; use instance attr | ✅ Done | [§3](#sec-3) |
| §3h | **HIGH** | dead-code | `_flat.py` legacy fixed-function path broken/dead (~300 lines); delete or restore | ⬜ Backlog | [§3](#sec-3) |
| §3i | **HIGH** | correctness | FBO/scissor state can leak across frames on a mid-pick exception (`selection.py`) | ✅ Done | [§3](#sec-3) |
| §3j | MEDIUM | dedup | flat/select layer duplication with **diverging** id encodings; consolidate | ✅ Done | [§3](#sec-3) |
| §3k | MEDIUM | perf | Redundant per-frame GL work (samplers set 2×/frame; no bind cache; GL round-trips) | ✅ Done | [§3](#sec-3) |
| §3l | MEDIUM | correctness | `glClientWaitSync` status discarded; overflow-drain can block the render thread ~1s | ✅ Done | [§3](#sec-3) |
| §3m | LOW | dead-code | Misc dead code / unused imports / collapsible `_set_uniform*` + texture-transform helpers | ✅ Done | [§3](#sec-3) |
| §3n | maint | — | God classes/methods (`_flat.Render`, `VRML97ShaderProgram`, `ShadowMapMixin`, `SelectionMixin`) | ✅ Done (all four decomposed along cohesive seams; see [GOD-OBJECT-DECOMPOSITION.md](GOD-OBJECT-DECOMPOSITION.md)) | [§3](#sec-3) |
| §3o | note | design | `PBRMaterial` in-place mutation could serve a stale UBO; add `__setattr__` bump or convention | ✅ Done | [§3](#sec-3) |
| §4a | **HIGH** | dead-code | `shadershape.py` dead with a broken import; delete it and its skipped test | ⬜ Backlog | [§4](#sec-4) |
| §4b | **HIGH** | dead-code | `DisplayListCompiler` unreachable, latent `NameError`; delete | ⬜ Backlog | [§4](#sec-4) |
| §4c | MEDIUM | dedup | Three parallel material→uniform paths with no shared source of truth; centralize | ✅ Done | [§4](#sec-4) |
| §4d | MEDIUM | perf | `IFSCompiler.polygons()` builds a dict+`Vertex` per vertex-use; vectorize | ⬜ Backlog | [§4](#sec-4) |
| §4e | MEDIUM | correctness | Winding/cull setup duplicated; VRML97 renders wrong winding under mirrored transforms | ✅ Done | [§4](#sec-4) |
| §4f | LOW | dead-code | `Material.sortKey` empty stub (caller commented out); delete or implement | ✅ Done | [§4](#sec-4) |
| §5a | **HIGH** | security | `gltf.py` no size cap on the **primary** document (`bytes`/local path, inline `data:`) | ✅ Done | [§5](#sec-5) |
| §5b | MEDIUM | security | `loader.py` unbounded `urlretrieve` disk-DoS | ✅ Done (capped in #1) | [§5](#sec-5) |
| §5c | MEDIUM | correctness | glTF accessor `componentType`/`type` raise bare `KeyError` instead of located `ValueError` | ✅ Done | [§5](#sec-5) |
| §5d | MEDIUM | maint | `_build_material`/`_build_scene` god functions; per-extension table + `_NodeBuilder` | ✅ Done | [§5](#sec-5) |
| §5e | info | security | Pillow `MAX_IMAGE_PIXELS` decompression-bomb guard intact — **not a problem** | ℹ️ Info | [§5](#sec-5) |
| §6a | MEDIUM | dedup | `rendering_regression.py` fourth parallel report framework; retire + drop redundant runs | ✅ Done | [§6](#sec-6) |
| §6b | LOW | dedup | `TestReportGenerator` tested in two files; two unit-test roots — consolidate | ✅ Done | [§6](#sec-6) |
| §6c | info | — | `shader_*.py` tutorials / `test_gltf_*.py` — **correctly leave alone** | ℹ️ Info | [§6](#sec-6) |
| §7a | — | observability | 173 `except Exception: pass` + 11 bare `except:`; audit / `log.debug(exc_info=True)` | 🟡 Partial (bare-except narrowed; 173-site logging audit deferred) | [§7](#sec-7) |
| §7b | — | py2 | Remnant sweep: `iteritems`/`itervalues`, 19 `from __future__`, 72 `print()`→logging | ✅ Done (iter* fixed; `from __future__` correctly kept) | [§7](#sec-7) |
| §7c | maint | — | Split god objects (`gltf`,`_flat`,`shaderpass`,`context`,`nurbs`,`selection`,`indexedfaceset`) | ✅ Done (all seven split; `gltf` now a package with resolver+samples extracted, accessors/materials/scene remain in `__init__`) | [§7](#sec-7) |
| §7d | maint | — | ~12 trivial context-class glue files; replace with a small factory | ⬜ Backlog | [§7](#sec-7) |
| §7e | info | — | Only one `eval`/`exec` in the tree (`gltest.py`) — expected/fine | ℹ️ Info | [§7](#sec-7) |


<a id="finding-0"></a>
### Issue 0 — `long()`/`cmp()` remnants ✅

**Finding refined during fix:** the three `long()` sites (`flatcompat.py:277`, `_flat.py:1406`, `renderpass.py:512`) do **not** actually crash today — `from OpenGL.GL import *` / `from OpenGLContext.arrays import *` silently re-export a `long` symbol (bound to `int` / `numpy.int64`) into those module namespaces, masking the Python-2 remnant. They were still replaced with `int()` so the code no longer depends on that fragile star-import side effect. The genuinely-crashing site is **`cmp()` at `renderpass.py:291`** (`cmp` is *not* re-exported → `NameError`), which took down `TransparentRenderPass.__call__` the instant it had transparent geometry to draw.

**Changes:**
- `renderpass.py`: extracted the transparent depth sort into a testable `TransparentRenderPass.depthSort()` staticmethod (`sorted(..., key=…, reverse=True)`), replacing the `cmp` comparator; `long(name)` → `int(name)` in the select readback.
- `flatcompat.py` / `_flat.py`: `long(pixel…)` → `int(pixel…)`.

**Tests (TDD):**
- `tests/test_transparent_depth_sort.py` — pure-Python unit tests for `depthSort` (Red: `AttributeError`; Green: pass).
- `tests/test_compat_pick_gl.py` — off-screen GLFW driver that renders a Box in the **default/compatibility** profile and injects a centre-of-viewport pick, asserting the pick path runs without crashing (guards the `flatcompat.selectRender` `int()` readback).

<a id="finding-7"></a>
### Issue 7 — VRML97 two-sided lighting + attenuation guard ✅

**Changes (both `vrml97_lighting.frag` and `vrml97_vertex_color.frag`):**
- Added `if (!gl_FrontFacing) normal = -normal;` in `main()` so `solid=FALSE` geometry is lit on its back faces (matching `pbr.frag` and the fixed-function `GL_LIGHT_MODEL_TWO_SIDE` path).
- Clamped the attenuation denominator with `max(..., 1e-4)` so a zero-constant light near a fragment can't divide by zero into Inf/NaN.

The broader MEDIUM cleanup (folding `vrml97_vertex_color.frag` onto `_lights_inc.glsl`, shared `encodeObjectId`) is out of scope for issue 7 and left for the backlog.

**Test (TDD):** `tests/test_twosided_lighting_gl.py` — off-screen core-profile driver renders a single quad wound so only its **back** face is visible, lit head-on by a directional light, then reads the centre-pixel luminance. Verified Red (both `material` and `vertexcolor` scenarios render near-black without the flip) → Green (bright with it).

<a id="finding-1"></a>
### Issue 1 — `loader.py` unrestricted fetch / arbitrary local open ✅ (CRITICAL security)

Mirrored the glTF loader's containment (`gltf._Resolver`) in `loaders/loader._Loader`. New module helpers `_origin`/`_same_origin` and `_reference_target(joined_url, baseURL)` enforce the untrusted-asset policy for every **reference** resolved against a document's baseURL:
- **local document** → references confined to its own directory (realpath containment; `../` traversal, absolute paths and `file://` escapes all rejected);
- **http(s) document** → same-origin http(s) references only (blocks `file://` reads and `169.254.169.254` metadata SSRF).

The policy is checked *before* any disk/network access. `download()` now permits **http(s) only** (no `file://`/`ftp://`) and **caps the body** at `DEFAULT_MAX_RESOURCE_BYTES` (256 MiB) to close the disk-DoS. Top-level (no-baseURL) loads — the trusted, user-initiated entry — keep opening local paths and `res://` resources directly.

**Test (TDD):** `tests/test_loader_security.py` — 11 pure-Python tests (no network) covering sibling-allowed, traversal/absolute/`file://` escape blocked, cross-origin/link-local SSRF blocked, and end-to-end `_Loader(...)` enforcement. Verified Red (`_reference_target` absent → import error) → Green.

<a id="finding-8"></a>
### Issue 8 — `obj.py` broken on Python 3 ✅

- `md5(baseURL)` → `md5(baseURL.encode('utf-8'))` (Py3 `TypeError` on the first parse line).
- `urllib.basejoin` → `urllib.parse.urljoin` (absent in Py3; the `AttributeError` was swallowed, so textured OBJs silently lost their textures).
- Narrowed the bare `except:` around material parsing to `except Exception as err:` **with logging**.
- Also decode loader bytes to text before parsing the `.mtl` (`file.read()` is `bytes`), and fixed a latent unbound-variable crash when the first `mtllib` fetch fails and the URL has no `/`.

**Test (TDD):** `tests/test_obj_loader_py3.py` — parses a minimal OBJ (guards the `md5` fix) and asserts `map_Kd` attaches an `ImageTexture` with a correctly joined URL (guards the `urljoin` fix). Verified Red (`TypeError`) → Green.

<a id="finding-3"></a>
<a id="finding-4"></a>
<a id="finding-5"></a>
<a id="finding-6"></a>
<a id="finding-9"></a>
### Geometry theme — issues 3, 4, 5, 6, 9 ✅ (branch `fix/geometry-gpu-churn`)

**Issue 9 — double tessellation.** Deleted the discarded first `self.tessellate()` in `IndexedPolygonsCompiler.compile` (`indexedfaceset.py`); the second call with `sources` is the one that's used. *Test:* `tests/test_ifs_double_tessellation.py` spies on `tessellate` and pins the call count to 1 (Red: 2 → Green: 1).

**Issue 3 — per-frame VAO churn.** `shadergeometry.render_shader_arrays`/`render_shader_interleaved` now accept `owner=` and cache the VAO on the node via a new `_get_or_build_vao` helper, keyed by shader program (attribute locations are program-specific) + VBO identity (a data-driven VBO replacement rebuilds it). Wired `owner=self` into `ArrayGeometry`, `Box`, `Quadric` (Sphere/Cone/Cylinder), and `gear`. *Test:* `tests/test_shader_vao_caching_gl.py` renders a Sphere for 12 frames and asserts VAO-generation reaches steady state (Red: 6→12 → Green: 1).

**Issue 6 — IndexedPolygons had no shader path.** Added `IndexedPolygons._render_shader` (mirrors ArrayGeometry/Quadric: cached VAO, cached element-array index VBO, `glDrawElements(GL_TRIANGLES, …, GL_UNSIGNED_INT)`); triangles only (core has no `GL_QUADS`; the IFS compiler always emits triangles). Without it, per-vertex-normal IFS (which `IndexedFaceSetCompile` routes here at weight 1.05) silently rendered nothing under core. *Test:* `tests/test_indexedpolygons_shader_gl.py` renders such an IFS under core and asserts a lit region (Red: 0 nonblack → Green: ~23k).

**Issue 4 — PointSet per-frame buffer rebuild.** Rewrote `PointSet._render_shader` to keep a persistent VBO on the node and re-upload via `set_array` only when coord/color change (tracked through `mode.cache` field dependencies), with per-program cached VAOs; hoisted the in-loop `numpy`/`ctypes` imports to module scope. *Test:* `tests/test_pointset_vao_caching_gl.py` (Red: 6→12 VAOs → Green: 1); dynamic re-upload verified separately (moving points changes the frame).

**Issue 5 — IndexedLineSet per-polyline VBO churn.** Rewrote `IndexedLineSet._render_shader` to concatenate all polylines into one persistent, version-keyed VBO drawn as per-polyline `GL_LINE_STRIP` ranges with a single cached VAO (was: one VAO/frame + gen/upload/delete a VBO per polyline per frame + per-polyline Python list-comprehension); hoisted imports to module scope. *Test:* `tests/test_indexedlineset_vao_caching_gl.py` (Red: 6→12 → Green: 1).

**Cross-checks:** `test_shader_all_geometry`, `test_gltf_loader` (83), and a direct Box+Sphere+Cylinder render all still pass/render on this branch.

<a id="finding-2"></a>
### Issue 2 — `gzpickle.py` `pickle.load` RCE ✅ (branch `fix/remove-gzpickle`)

Deleted `loaders/gzpickle.py` outright (it `pickle.load`-ed `.pkl`/`.pkl.gz` scene data = arbitrary code execution on untrusted input) along with `loaders/vrml2pklgz.py`, its only user (a standalone converter that *wrote* those files). Verified first: **neither was registered as a loader** for any extension (no `.pkl` entry point in `entry_points.txt`; `plugins.py` registers nothing for it), and nothing imports `vrml2pklgz`, so removal is complete rather than sandboxed. If a gzipped-scene cache is ever wanted again, it should use a data format (JSON/msgpack) or a restricted `Unpickler`, never bare `pickle` across a trust boundary.

**Test (TDD):** `tests/test_gzpickle_removed.py` — asserts both modules are no longer importable (`ModuleNotFoundError`) and the loaders package still imports. Verified Red (both importable) → Green.

<a id="finding-12"></a>
### Issue 12 — glTF same-origin check bypassable via redirect ✅ (branch `fix/gltf-redirect-ssrf`)

The same-origin guard validated only the pre-request URL; `urllib.request.urlopen` then followed 3xx redirects without re-validating, so a same-origin URL that 302s to `169.254.169.254` defeated it. Added `_OriginLockedRedirectHandler` (a `HTTPRedirectHandler` that re-applies the scheme + same-origin policy on **every** hop, raising `HTTPError` on a cross-origin/`file://` target) and `_urlopen_same_origin`, and routed both fetch sites through it — `_Resolver.fetch` (external references, the flagged path) and `_fetch_url` (top-level document, defence in depth: a redirect leaving the requested URL's origin is refused).

**Tests (TDD):** `tests/test_gltf_redirect_ssrf.py` — 4 no-network tests driving the handler directly (cross-origin, cross-host, `file://` downgrade refused; same-origin redirect allowed). Verified Red (handler absent → import error) → Green. Two existing `test_gltf_loader.py` fetch tests were updated to patch `build_opener` (the new fetch seam) instead of `urlopen`; full file 87 passed.

<a id="finding-11"></a>
### Issue 11 — drifted `_check_display_available` (headless false-skip) ✅ (branch `fix/test-suite-dedup`)

The visual-regression copy of `_check_display_available` checked only `DISPLAY`/`WAYLAND_DISPLAY` and omitted the EGL/OSMesa offscreen case the other copies had, so on a headless runner with `PYOPENGL_PLATFORM=egl` the visual suite **silently skipped and read green**. Added a single source of truth — `OpenGLContext/testing/display.py` (`display_available(env=None)` + `OFFSCREEN_GL_PLATFORMS`) — and routed `test_visual_regression.py`, `test_all_scripts.py`, and `conftest.py` through it (removing three copies). **Test:** `tests/test_display_check_shared.py` — shared-helper cases + the exact-bug regression (visual-regression copy must count EGL); Red (helper missing / visual copy `False` on EGL) → Green. `test_headless_ci.py` (which already guarded the correct copy) still passes.

<a id="finding-10"></a>
### Issue 10 — triple-run script runner collapse ✅ (branch `fix/test-suite-dedup`)

`TestScriptCategories` (hand-maintained table), `TestAllScripts` (glob), and `TestVisualRegression` (glob, with capture) each independently subprocess-launched nearly the same ~114 scripts, 2–3× per session. Collapsed to **one** `TestScripts` runner over the single glob list: each script runs **once**; visual scripts (not in `NON_VISUAL_SCRIPTS`) go through the image-capturing regression path, non-visual scripts are just run for tracebacks. Slow-marking is derived from `SLOW_SCRIPTS` ∪ the `slow` categories in `SCRIPT_CATEGORIES` (kept only as the slow-source); skip/timeout logic is unchanged (`should_skip_script`/`get_script_timeout`). Collection dropped from **~408 → 145** items (one launch per script). Removed the now-dead `TestScriptCategories`/`TestAllScripts`/`TestVisualRegression`, `_category_test_params`, and `get_visual_test_scripts`/`_VISUAL_TEST_SCRIPTS`. Verified: file collects (145), imports clean, and both the non-visual (`glget.py`) and visual (`nehe2.py`) paths pass through the new runner.

---

### Batch 2 — `fix/passes-robustness` (§3a, §3b, §3e, §3f, §3g, §3o) ✅

Render-pass correctness/robustness fixes, all Red/Green TDD (pure-Python except the off-screen compat-transparent smoke):
- **§3a / §3f** (`renderpass.OverallPass.__call__`): added class-level `visibleChange = 0` (no more `AttributeError` when the first sub-pass raises), and routed the swallowed per-frame exception through `log.exception` (traceback now reaches logging) — dropped the now-unused `traceback`/`sys` imports.
- **§3g** (`renderpass.VisitingRenderPass`): frustum-culling detection extracted to `_detectFrustumCulling` + `_frustumCullingMode`, cached on the **context** instead of writing the shared class attribute (no cross-context leak).
- **§3b** (`_flat`/`flatcompat`): implemented the transparent deferral — `addTransparent` records `(matrix, path, shape)` and `_renderDeferredTransparent` replays them via `RenderTransparent`, drained at the end of both `renderTransparent` paths; a runtime-transparent shape no longer vanishes for the frame.
- **§3e** (`shaderpass.compile`): each of the six programs now compiles via `_compile_one` in isolation; one broken shader degrades only its feature, and only a failed **lit** program makes the system report not-ok (was: one failure `_clear_programs()`-ed everything).
- **§3o** (`PBRMaterial`): `__setattr__` bumps `_ubo_version` on any UBO factor edit, so the PBR pass re-packs instead of serving a stale std140 block.

Tests: `test_renderpass_robustness.py`, `test_deferred_transparent.py`, `test_shader_compile_isolation.py`, `test_pbrmaterial_ubo_version.py` (19 total); gltf loader 83 still green; off-screen compat transparent render verified.

---

### Batch 3 — `fix/shaders-cleanup` (§2b, §2c, §2d, §2e, §2a ✅) ✅

- **§2b**: extracted `encodeObjectId` into `_objectid_inc.glsl`; `_lights_inc.glsl` and the four non-lit shaders (`vrml97_unlit/point/line/vertex_color.frag`) now `#include` it instead of hand-inlining the RGBA8 bit-unpack. The four are now assembled through `preprocess_shader` (which resolves `#include`), where the base `compile()` used raw reads.
- **§2c**: corrected the stale "192 bytes / 48 words" material-block comments in `pbr.frag` and `pbrpass.py` to 224 B / 56 words (73 materials).
- **§2d**: deleted the dead/broken `shaders/generator.py`.
- **§2e**: the instancing branch of `pbr.vert`/`vrml97_lighting.vert` now uses `transpose(inverse(mat3(mv)))` (exact for affine `mv`, ~4× cheaper) instead of `mat3(transpose(inverse(mv)))`.
- **§2a**: completed in full.
  - **Shared math**: extracted the attenuation / spot-cone / per-light `calcLight` functions into `shaders/_vrml97_lighting_inc.glsl`, now `#include`d by both `vrml97_lighting.frag` and `vrml97_vertex_color.frag`, so the two lighting paths can no longer drift. `calcLight` takes a per-light `shadowFactor`.
  - **Shadows on per-vertex-coloured geometry**: `vrml97_vertex_color.frag` now `#include`s `_lights_inc.glsl` + `_shadow_inc.glsl`, declares `eyeToWorld`, and calls `resolveShadows()` — so NURBS surfaces and per-vertex-coloured `IndexedFaceSet`s finally receive shadows. Compiled through `_compile_shadow_frag` (shadow defines) in both `shaderpass.py` and `pbrpass.py`.
  - **Uniform wiring**: rather than thread a `program=` arg through the ~15 shadow setters, added a single `_shadow_program` context attribute (with a `_shadow_prog` property) that those setters target, plus `shadow_receiver_programs()`. `shadowmixin.bindShadowUniforms` now loops over the lit **and** vertex-colour programs, binding each, while the depth textures bind once as shared GL state. `init_shadow_samplers`' per-frame skip guard became a `set` so two receiver programs don't ping-pong the sampler upload.

Tests: `test_vertex_color_shadows.py` (3 source-structure + 1 off-screen differential: a per-vertex-coloured wall is measurably darker where a caster shadows it). Plus `test_shader_cleanup_sources.py` (13 structural) + `test_shader_cleanup_gl.py` (off-screen: all five VRML97 programs compile; lit/vertex-colour/point/line all render); existing `test_shader_includes`/`test_shader_compile_guard`/`test_pbr_shader_source` still green (28); all 65 shadow tests still green.

---

### Batch 4 — `fix/passes-dedup-perf` (§1a, §3j, §3k, §3m ✅)

- **§1a** ✅: hoisted the in-function `import numpy as np` / `import ctypes` out of the hot paths in `indexedfaceset.py`, `quadrics.py`, `_flat.py`, `instancing.py` (and confirmed `pbrpass.py`) to module scope (`from __future__` kept first). PointSet/IndexedLineSet were already hoisted on `fix/geometry-gpu-churn`.
- **§3m** ✅: removed the verified-dead `_flat.renderGeometry` (no callers) and `selection.read_depth` (no callers) and the redundant local `import os` in `_flat`. Then completed the helper collapse in `shaderpass.py`:
  - The five near-identical `_set_uniform{1i,1f,2f,3f,4f}` methods (each duplicating the unchanged-check → `_get_location` → guard → `glUniform*` body) now normalize their value and delegate to one shared `_set_uniform(name, value, program, upload)`; the vector variants share module-level `_UPLOAD_{2,3,4}FV` uploaders. Behaviour (normalization, change-cache key, invalid-location skip) is unchanged.
  - The five hand-built 3×3 texture-transform matrices in `set_texture_transform` (three of them near-identical translations) collapse into pure module-level `_affine2d_{translate,scale,rotate}` builders composed by a new pure `texture_transform_matrix(node)` — now callable and unit-testable without a GL context, which the old code was not.

  Tests: `test_shaderpass.py` rewritten `TestTextureTransformMatrix` (identity, an independent five-matrix oracle across 6 field combinations, center-pivoted rotation, affine builders) + new `TestSetUniformCollapse` (normalization, change-cache skip, absent-location skip); `test_gltf_texture_transform.py` (21) and `test_material_ubo.py` still green; VRML97 (13977) / PBR (23760) renders unchanged.
- **§3j** ✅ (completed later): the two `selectRender` copies now share a module-level `_flat._color_select_render(pass_obj, mode, toRender, events, *, id_shift, read_format, setup_fixed_function, require_pick_enabled)`. `FlatPass.selectRender` (core, 12-bit id shift, RGBA) and `flatcompat.selectRender` (compat, RGB, fixed-function) both delegate; the shared body also fixes an event-set iteration bug the two copies had drifted on. The diverging id encodings are preserved as explicit per-profile arguments rather than merged. Tests: `test_select_render_shared.py`.
- **§3k** ✅ (completed later): `shaderpass` now tracks the active program through `_bind_program`/`_program_for_default` and `init_shadow_samplers` is guarded per program (a `set`), so the shadow samplers aren't re-uploaded 2–3× per frame. A `glUseProgram`-**skip** cache was deliberately *not* added — the IBL/bloom/transmission passes bind programs mid-frame outside this class, so a skip cache would go stale and drop uniforms (verified: it broke IBL setup with `GL_INVALID_OPERATION`); `_bind_program` always binds and only tracks. Documented in-code. Tests: `test_shaderpass_state_caching.py`.

Verified: touched modules import; off-screen multi-geometry render unchanged (23,882 non-black px).

---

### Batch 5 — `fix/gltf-hardening` (§5a, §5c, §5d) ✅

- **§5d** ✅ (completed later): the `_build_material` / `_build_scene` god functions were decomposed. Material extensions now go through a `_MATERIAL_EXT_HANDLERS` table (one small `_ext_*` handler per KHR extension) + `_MATERIAL_EXT_DEFAULTS`, driven by `_read_material_extensions`, and a `_TextureCollector`; `_build_material` just collects and splats `**ext_kwargs`. Scene construction moved into a `_SceneBuilder` class (`mesh_shapes`/`build`/`run`) with `_build_scene` a thin wrapper. Tests: `test_gltf_loader.py` (83) stays green; extension round-trips unchanged.
- **§5a**: `load_gltf` now size-caps the **primary** document — `_check_size(len(data), …)` for a bytes upload and `os.path.getsize` for a local path — *before* handing it to `pygltflib`, so a huge `.glb`/`.gltf` (or its inline `data:` buffers) can't be parsed unbounded. `max_resource_bytes` previously bounded only external references.
- **§5c**: unknown accessor `componentType`/`type` now raise a located `ValueError` (`_component_dtype`/`_type_count`) with the expected-values list, matching the rest of the loader, instead of a bare `KeyError`.

Tests: `test_gltf_hardening.py` (6, incl. a check that the size cap trips before parsing); `test_gltf_loader.py` 83 still green.

---

### Batch 6 — `fix/geometry-followups` (§4e, §4f, §3c, §4c ✅; §4d deferred)

- **§4f** ✅: deleted the dead `Material.sortKey` empty stub and its commented-out caller in `appearance.py`.
- **§4e** ✅: added `scenegraph/winding.py` (`front_face`, `apply_winding_cull`) with the mirror-aware (negative-determinant) front-face flip that only `pbrmesh` had, and wired it into `ArrayGeometry` (legacy + shader paths) and `IndexedPolygons` (legacy). VRML97 solid geometry no longer culls the wrong side under a mirrored transform. Tests: `test_winding_mirror.py` (5, incl. single/triple mirror flips); off-screen compat IFS + core multi-geometry renders verified.
- **§3c** ✅ (completed later): `NurbsSurface._render_shader` now reuses a VAO cached per `(program, VBO)` through the shared `shadergeometry._get_or_build_vao(self, program, (shader_vbo,), _bind_attributes)`, dropping the per-frame `glGenVertexArrays`/`glDeleteVertexArrays` + attribute re-bind. Test: `test_nurbs_vao_caching_gl.py` (off-screen, asserts VAO generation reaches steady state).
- **§4c** ✅ (completed later): added `scenegraph/material_fields.py` — a `MaterialFields` namedtuple + `read_material_fields(node)` — as the single source of truth for reading VRML97 material fields with their defaults. `material.py`, `pbrmaterial.py`, and `shaderpass.configure_material_from_node` all route through it, so the three material→uniform paths no longer each hard-code the field list/defaults. Test: `test_material_fields.py`.
- **§4d** ⬜ deferred (documented): vectorising `IFSCompiler.polygons()` would rewrite the `Vertex`/`indexKey`/tessellation pipeline — correctness-sensitive, only hit on cache invalidation, high risk of subtly changing tessellation. Left rather than shipped unverified.

---

### Batch 7 — `fix/code-health` (§7b ✅, §7a 🟡)

- **§7b** ✅: fixed the two genuine Python-3 crashers — `_displayLists.itervalues()` → `.values()` (`wglfont.py`) and `pointSet.iteritems()` → `.items()` (`shadow/edgeset.py`). Note: the review's suggestion to drop the 18 `from __future__ import annotations` is **wrong** and was *not* done — `annotations` still changes annotation evaluation on 3.12 and guards the `TYPE_CHECKING` forward-references these modules rely on; removing it would break imports. The `print()`→`logging` conversion (72 sites, cosmetic) is left as low-priority follow-up. (`cmp`/`basejoin`/`long` remnants are handled on their theme branches.)
- **§7a** 🟡: narrowed the bare `except:` → `except Exception:` in `visitor.py` (5), `wglfont.py`, `pygamefont.py`, `glfwinteractivecontext.py`, `font.py` — bare except swallowed `KeyboardInterrupt`/`SystemExit`. The broader 173-site `except Exception: pass` logging audit is judgment-heavy per-site work, left as a documented follow-up rather than a blind mechanical sweep.

Tests: `test_code_health_py2.py` (6) guards against iter\* remnants tree-wide and bare-except regressions in the narrowed files; touched modules import.

---

### Batch 8 — `fix/passes-shadow-selection` (§3i, §3l, §3d ✅)

- **§3l** ✅: `_resolveBatch(block=True)` now honours the `glClientWaitSync` return status — on `GL_TIMEOUT_EXPIRED`/`GL_WAIT_FAILED` it logs and drops the batch instead of reading the PBO and dispatching stale/zero ids. Test: `test_pick_fence_status.py` (timeout drops without reading; signalled proceeds).
- **§3i** ✅: the pick loop's outer `finally` now defensively `glBindFramebuffer(…, 0)` + `glDisable(GL_SCISSOR_TEST)`, so an exception mid-pick-loop can't leak the tiny pick FBO / scissor enable into the next frame. Existing async + unlit pick GL tests still pass.
- **§3d** ✅: the spot and point shadow passes now fit their near/far to the full caster pool, not the camera-visible subset. `renderShadowMaps` caches `self._caster_points = _worldPointsFromRecords(self._toRender_cache)` (the whole renderable set, not camera-culled) once per frame; `_renderSpot`/`_renderPoint` derive near/far from it instead of the `occluder_points` argument, which is now dropped from both signatures. This matches what the directional path already did (its `caster_bounds` come from `_toRender_cache`) and makes the depth range — and thus the shadow — camera-stable: a caster outside the camera frustum but inside the light cone / cube face no longer falls past the near/far planes and pops as the camera moves. Tests: `test_shadowmixin.py::TestSpotUsesCasterPool` (spy confirms `_renderSpot` fits to `_caster_points`) + updated `TestCubeFaceClearing` (point path reads `_caster_points`); the off-camera-caster GL tests `test_shadow_offscreen_caster_gl` / `test_shadow_upsun_caster_gl` and all 65 shadow tests stay green.

---

### Batch 9 — `fix/testsuite-cleanup` (§6b, §6a ✅)

- **§6b** ✅: removed the duplicate `TestReportGenerator` unit tests from `test_visual_regression.py`; `OpenGLContext.testing.report_generator` is now covered in one place (`test_testing_infrastructure.py::TestTestReportGenerator`, 4 tests still green). `test_visual_regression.py` still collects.
- **§6a** ✅ (completed later): retired the 1403-line bespoke `rendering_regression.py` — a fourth parallel run→capture→diff→report framework (its own `TestResult`/`DiffResult`, diff math and baseline dir) duplicating the shared `framebuffer_comparison`/`report_generator`. Deleted the file and the two driver classes it powered in `test_visual_regression.py` (`TestRenderingRegression`'s 5 itemized `--tests` runs + `TestFullRegressionSuite`'s 6th full un-filtered re-run), plus its now-dead entries in `test_all_scripts.py`'s `RUNNER_SCRIPTS` and `run_core_tests.py`'s skip set and the `AUTOMATED_TEST_SCRIPTS`/`SLOW_TEST_TIMEOUT` leftovers. The scenes it re-rendered (basic geometry, lights, materials, transparency, textures, NURBS, text, line/point sets) are already covered by dedicated suite scripts run in both profiles with reference-image diffing, so no coverage is lost — net −~1450 LOC and 6 redundant GL-subprocess launches per full run. Added `TestBespokeFrameworkRetired` (3 guards) so the duplication can't return. `test_visual_regression.py` still collects (10 passed, 2 env-skips).

---

## Executive summary

The newest subsystems in this codebase are genuinely good. The PBR/glTF path, the shadow subsystem, IBL, and the instancing pass are written by someone who understands the GPU: material data lives in a `std140` UBO to avoid per-shape uniform churn; VAOs/VBOs are built once and cached with version-keyed invalidation; the shadow code is cleanly split into pure-math / GL-resource / capability-detection / orchestration modules; the glTF loader has already been through a real security pass (path-traversal containment, an SSRF same-origin check, accessor bounds validation). Credit where due — this is not beginner work.

The problem is that the **older VRML97 shader-geometry paths never caught up to that standard**, and the **older asset loaders never got the security hardening the glTF loader received**. The result is a codebase with two populations: a modern half that is production-grade, and a legacy half that has three classes of objectively serious defect:

1. **Per-frame GPU resource churn** — the single biggest performance problem. Multiple common geometry types create and destroy VAOs/VBOs *every frame*, defeating the entire purpose of a VAO. The correct pattern already exists in the same repo (`pbrmesh._MeshGPU`, `teapot._buffers`, the instancing pass); the legacy nodes simply don't use it.
2. **Security holes in the pre-glTF loaders** — `loader.py`/`obj.py` fetch arbitrary URLs and open arbitrary local paths with no scheme allowlist, size cap, or path containment, reachable from any untrusted `ImageTexture`, `.obj`, or `.wrl` file. This is exactly the bug class the glTF loader was hardened against, but the hardening was never applied here.
3. **Correctness gaps, Python-2 remnants, and dead code** — most seriously, `long()`/`cmp()` remnants that make the *default-profile* mouse-pick path crash the render loop with a `NameError`; plus two-sided lighting silently dropped in the VRML97 shaders, an unguarded divide-by-zero, a double-tessellation that doubles IFS compile cost, a geometry node with no core-profile path at all, and several dead/broken modules (one with a `NameError`, one with an `ImportError`, one crashing on Python 3).

For a library aimed at tens of thousands of users, #1 shows up as poor framerate on ordinary VRML content, #2 is a shippable CVE, and #3 is the kind of thing that erodes trust the first time someone runs `OPENGLCONTEXT_PROFILE=core` on their own model.

---

## Severity-ranked top issues

| # | Severity | Area | Issue | Location |
|---|----------|------|-------|----------|
| 0 | **CRITICAL (correctness)** | passes | Python-2 `long()`/`cmp()` remnants: the **default** compatibility-profile pick readback calls `long()` → any pick event `NameError`-crashes the render loop | `flatcompat.py:277`, `_flat.py:1427`, `renderpass.py:291,512` |
| 1 | **CRITICAL (security)** | loaders | Unrestricted URL fetch + arbitrary local-file open, reachable from untrusted textures (SSRF, local file disclosure, disk-DoS) | `loaders/loader.py:106-142` |
| 2 | **CRITICAL (security)** | loaders | `pickle.load` on `.pkl.gz` scene data = RCE if ever pointed at untrusted input | `loaders/gzpickle.py:53` |
| 3 | **HIGH (perf)** | geometry | Per-frame VAO gen+delete on the main VRML97 shader path (IFS/Sphere/Cone/Cylinder/NURBS) | `scenegraph/shadergeometry.py:231-251, 280-294` |
| 4 | **HIGH (perf)** | geometry | `PointSet` rebuilds & re-uploads its entire GPU buffer every frame (the particle node) | `scenegraph/pointset.py:147-225` |
| 5 | **HIGH (perf)** | geometry | `IndexedLineSet` gen/upload/delete a VBO *per polyline per frame* | `scenegraph/indexedlineset.py:193-260` |
| 6 | **HIGH (correctness)** | geometry | `IndexedPolygons` has no shader path → silently fails under core profile for per-vertex-normal IFS | `scenegraph/indexedpolygons.py:191-256` |
| 7 | **HIGH (correctness)** | shaders | Two-sided lighting normal-flip missing from VRML97 lit shaders (`solid=FALSE` renders wrong) | `shaders/vrml97_lighting.frag`, `vrml97_vertex_color.frag` |
| 8 | **HIGH (correctness)** | loaders | OBJ material/texture path broken on Python 3 (`md5(str)`, `urllib.basejoin`), silently swallowed | `loaders/obj.py:97, 283` |
| 9 | **HIGH (perf/CPU)** | geometry | Double tessellation: first `tessellate()` result computed then discarded | `scenegraph/indexedfaceset.py:651-653` |
| 10 | **HIGH (test)** | tests | Same ~114 GL demo scripts launched as subprocesses 2–3× per pytest run | `tests/test_all_scripts.py:892-1014` |
| 11 | **HIGH (test)** | tests | Drifted `_check_display_available` copy → visual regressions falsely skip (green) on headless CI | `tests/test_visual_regression.py:174` |
| 12 | **MEDIUM (security)** | loaders | glTF same-origin check bypassable via HTTP redirect | `loaders/gltf.py:379-396` |

**Remediation status:** 0–12 ✅ all done. Ranked-table items complete across branches `fix/passes-py2-remnants`, `fix/shaders-twosided`, `fix/loaders-security`, `fix/geometry-gpu-churn`, `fix/remove-gzpickle`, `fix/gltf-redirect-ssrf`, `fix/test-suite-dedup`. (The unranked §3–§7 MEDIUM/LOW cleanups remain as backlog.)

---

<a id="sec-1"></a>
## 1. Performance: per-frame GPU resource churn (the headline problem)

This is the most impactful, most fixable problem in the codebase, and it is real, not hypothetical — it is the current rendering path for the most common VRML97 geometry.

A Vertex Array Object exists to record attribute layout **once** so later frames only pay a cheap `glBindVertexArray`. The legacy shader paths throw it away every frame:

- **`shadergeometry.py:231/251` (`render_shader_interleaved`) and `:280/294` (`render_shader_arrays`)** — `glGenVertexArrays(1)` … `glDeleteVertexArrays(1,[vao])` on every call. These back `ArrayGeometry._render_shader` (every shader-mode `IndexedFaceSet`), `Quadric._render_shader` (every Sphere/Cone/Cylinder), and the NURBS surface renderer. The *VBOs* underneath are correctly cached; only the VAO wrapping them is rebuilt from scratch per shape per frame.

- **`pointset.py:147-225`** — the worst case, and ironically the node whose whole job is dynamic points. Every frame it: builds a fresh `np.empty` interleave in Python, `np.ascontiguousarray`, `glGenBuffers`, full `glBufferData` re-upload, `glGenVertexArrays`, draws, then deletes both. It also does `import numpy` and `import ctypes` *inside the render loop* (lines 161, 187) and calls `glGetUniformLocation` every frame (131, 138) — a documented driver-round-trip stall.

- **`indexedlineset.py:193-260`** — nested churn: one VAO per frame, then inside a per-polyline loop, `glDeleteBuffers`/`glGenBuffers`/`glBufferData` plus a Python list-comprehension array build *for each polyline, every frame*.

**The fix already exists in this repo.** `pbrmesh._MeshGPU`, `teapot._buffers`, and `passes/instancing._build_instance_vao` all cache the VAO+VBO on the node/gpu object and, on the rare frame where data changed, re-upload via `vbo.set_array(...)` instead of destroy/recreate. `_build_instance_vao`'s own docstring states the target: *"every later frame is just: bind the VAO, re-upload the instance VBO, draw — no VAO/VBO gen or delete."* Apply that same discipline to `shadergeometry.py`, `pointset.py`, and `indexedlineset.py`. Cache the VAO alongside the already-cached VBO, keyed on the same field-version the VBO uses.

Also hoist the 16 in-function `import numpy`/`import ctypes` statements in `scenegraph/`/`passes/` hot paths to module scope. They are cheap after the first call but they are noise in a render loop and signal that these paths were written without a per-frame-cost mindset.

**Estimated impact:** for a scene of N shapes at 60fps this removes 60·N VAO create/destroy pairs per second and, for PointSet/IndexedLineSet, 60·N buffer uploads/allocations per second. On many-object scenes this is the difference between CPU-bound and GPU-bound.

---

<a id="sec-2"></a>
## 2. Shaders

The PBR shader (`pbr.frag`, 848 lines) is the strong point: a `std140` `MaterialBlock` UBO (bound once per material instead of ~20 `glUniform` calls), a documented "uniform-valued branches are coherent across a draw, so cheap" strategy, compile-time feature gating against `GL_MAX_TEXTURE_IMAGE_UNITS` (23 samplers is over the 16-unit floor, but `pbrpass.py:329` reads the real budget and drops lobes to fit), and correct handling of `gl_FrontFacing`, sRGB/linear color management, and a dozen KHR extensions. This is good work.

The VRML97 shaders are where the defects are:

- **HIGH — Two-sided lighting dropped.** `pbr.frag:413` flips the normal for back faces (`if (!gl_FrontFacing) Ngeom = -Ngeom;`), but `gl_FrontFacing` appears **nowhere** in `vrml97_lighting.frag` or `vrml97_vertex_color.frag`. The fixed-function path gave `solid=FALSE` geometry automatic two-sided lighting via `GL_LIGHT_MODEL_TWO_SIDE`; the shader path silently drops it, so double-sided VRML shapes render dark/wrong on their back faces. Add `if (!gl_FrontFacing) normal = -normal;` to both.

- **MEDIUM — Unguarded attenuation divide.** `vrml97_lighting.frag:59-63` (and its verbatim copy in `vrml97_vertex_color.frag:51-54`) computes `1.0 / (atten.x + atten.y*d + atten.z*d*d)` with no denominator clamp. `pbr.frag:583` guards the identical formula with `max(..., 1e-4)`. A light at `constant=0` near a fragment produces `Inf`/`NaN` that the final `clamp` turns into implementation-defined output on some GPUs. Apply the same `max(..., 1e-4)`.

- **MEDIUM — Duplicated lighting model that has already drifted.** `vrml97_vertex_color.frag` re-declares the entire light-uniform block and re-implements `calcAttenuation`/`calcSpotEffect`/`calcLight` byte-for-byte from `vrml97_lighting.frag`, instead of `#include "_lights_inc.glsl"` (which exists precisely to keep the two "in lock-step"). The copy has already fallen behind: it has **no shadow support**, so per-vertex-colored / NURBS geometry never receives shadows even when the rest of the scene does. Fold it onto the shared include.

- **MEDIUM — `encodeObjectId` hand-inlined in four shaders.** `_lights_inc.glsl:32` defines the shared RGBA8 id-encode, and `pbr.frag`/`vrml97_lighting.frag` use it — but `vrml97_unlit.frag`, `vrml97_point.frag`, `vrml97_line.frag`, and `vrml97_vertex_color.frag` each re-inline the same 4-line bit-unpack. Include the helper.

- **MEDIUM — Stale std140-size comments.** Comments at `pbr.frag:72` and `pbrpass.py:141,617` say "192 bytes / 48 words" but the code correctly uses 224 bytes / 56 words / 73 materials (I recomputed the layout — the code is right, the comments are stale from before the struct grew). These comments now contradict the line next to them; fix them before they mislead the next editor.

- **LOW — `shaders/generator.py` is dead and broken.** Nothing imports `ShaderGenerator`; assembly goes through `preprocess_shader` in `shaderpass.py`. And `DefaultShaderGenerator.shader()` interpolates `%(light_size)s` against a `%(light_count)s` template (a `KeyError` if ever called) and returns nothing. Delete it.

- **LOW — Per-vertex 4×4 inverse.** `pbr.vert:41` / `vrml97_lighting.vert:32`: `mat3(transpose(inverse(mv)))`. Since `mv` is affine, `transpose(inverse(mat3(mv)))` is exact and ~4× cheaper, and the value is constant per instance — ideally upload the CPU-computed normal matrix (the fast cofactor `normal_matrix()` already exists at `shaderpass.py:140`) as a per-instance attribute rather than reinverting per vertex.

---

<a id="sec-3"></a>
## 3. Rendering passes

The important context first: the pass modules built or refactored for the PBR era — `ibl.py`, `instancing.py`, `multidraw.py`, `bloom.py`, `shadowmap.py`, `transmission.py`, `pbrpass.py`'s UBO caches, and `selection.py`'s FBO/PBO pool — have all genuinely fixed the per-frame-churn anti-pattern: every `glGen*` there is guarded by "build once, resize/rebuild on demand." No `glGetError`/`glFinish`/`glFlush` in any hot pass loop. That work is done well. The defects are concentrated in the older `_flat.py`/`flatcompat.py`/`renderpass.py` layer and in a handful of correctness/leak details.

- **CRITICAL — Python-2 `long()`/`cmp()` crash the render loop.** `flatcompat.py:277` and `_flat.py:1427` call `long(pixel.view('<I')[0])` in the color-based pick readback; `renderpass.py:512` calls `self.selectable.get(long(name))`; `renderpass.py:291` calls `items.sort(lambda x,y: cmp(...))`. `long` and `cmp` do not exist in Python 3 (verified). `flatcompat.FlatPass` is the **default** (compatibility) profile pass and its `Render()` calls `selectRender` whenever there is a pick event, so **processing a mouse pick in the default profile raises `NameError` and propagates out of the draw call** (only `KeyboardInterrupt` is caught around `renderPasses`). The `renderpass.py` copies are in the legacy VRML-browser/shadow-demo shells — narrower blast radius, same bug. Fix: `int()` for `long()`, `items.sort(key=lambda x: x[0])` for the `cmp` sort. This is a one-line fix with an outsized correctness payoff and should ship first.

- **CRITICAL — Per-frame VAO/VBO churn in the scenegraph geometry nodes** (`pointset.py:148-225`, `indexedlineset.py:194-260`, `nurbs.py:490-544`). Same finding as §1/§4 from the passes side — confirming the anti-pattern lives in the geometry nodes, not the modern passes.

- **CRITICAL — `TransparentRenderPass.__call__` always raises** (`renderpass.py:291`, the `cmp` sort above) — dead-on-arrival in the browser/shadow pipeline that uses it.

- **CRITICAL — `OverallPass.__call__` can `AttributeError` on `self.visibleChange`** (`renderpass.py:672-680`): no class-level default, so if the first sub-pass raises, the trailing `if self.visibleChange:` references an unset attribute. Add `visibleChange = 0` as a class attribute.

- **CRITICAL — `addTransparent` is a silent no-op that drops geometry** (`_flat.py:1353-1354`). `shape.py:63` and `shadershape.py:77` call `mode.addTransparent(self)` and `return` (without drawing) when a shape is discovered transparent after being statically classed opaque. Since `addTransparent` does nothing, that shape simply vanishes for the frame. Implement the deferral, or remove the call sites.

- **HIGH — Spot/point shadow near-far fit uses the camera-culled occluder set** (`shadowmixin.py:298, 355-365`), defeating the module's own documented off-camera-caster fix that the directional path honors. A caster outside the camera frustum but inside a spot cone / point cube-face can fall outside the near/far range fit only from camera-visible points → shadow pops. Derive near/far from `_toRender_cache`, not `occluder_points`.

- **HIGH — One shared `try/except` around six shader compiles** (`shaderpass.py:264-373`): a break in any one shader (e.g. `vrml97_line.frag`) runs `_clear_programs()` and nulls *all* already-linked programs, taking down the whole shader system instead of degrading one feature. Compile each in its own try/except.

- **HIGH — Silent per-frame exception swallowing** (`renderpass.py:677-679`): `traceback.print_exc()` to `stderr` (bypassing `logging`) then continues — this is exactly what let the `cmp`/`visibleChange` bugs above go unnoticed. Route through `log.exception` and fail loudly at least once.

- **HIGH — Class-attribute mutation from instance code** (`renderpass.py:156-170`): `self.__class__.frustumCulling = ...` writes the shared class attribute, so in a multi-context process the first context to render permanently decides frustum-culling for every context sharing the pass class. Use `self.frustumCulling = ...`.

- **HIGH — `_flat.py`'s own legacy fixed-function path is broken/dead** (`_flat.py:1248-1295`): `legacyLightRender` has its `Light()`/`glLoadMatrixf` calls commented out and the branch never enables `GL_LIGHTING` (unlike `flatcompat.py`'s working copy). ~300 lines reachable only if `use_shaders=False` on a `flatcore.FlatPass`, which nothing does. Delete it or restore it.

- **HIGH — FBO/scissor state can leak across frames** (`selection.py:846-861` vs `912-915`): the enclosing `try/finally` restores the shader and viewport but not the pick-FBO binding or scissor enable; an exception mid-pick-loop leaves `GL_FRAMEBUFFER` bound to the tiny pick FBO into the next frame. Wrap the per-point bind in its own `try/finally`.

- **MEDIUM — Duplication in the flat/select layer:** ~90 lines of `selectRender` duplicated between `_flat.py:1356-1444` and `flatcompat.py:202-294` **with diverging id encodings** (one shifts the pick id 12 bits and reads `GL_RGBA`, the other reads `GL_RGB` unshifted — the "2**24 objects" docstring is stale for the shifted copy at ~2**20); `legacyBackgroundRender` duplicated verbatim (`_flat.py:1248` / `flatcompat.py:105`) though `flatcompat` already inherits it; near-duplicate world-point extraction (`shadowmixin.py:634` vs `664`) and eye-space depth-range math (`shadowmixin.py:589` reimplementing `shadowmath.near_far_from_points`). Consolidate.

- **MEDIUM — Redundant per-frame GL work the modern passes avoid:** `init_shadow_samplers()` (documented as one-time) called twice per frame (`shadowmixin.py:131,183`); no last-bound cache for `glUseProgram`/`glBindTexture` in `shaderpass.use()`/`bind_texture()` (`:396,885`) though a `_uniform_value_cache` exists for uniforms; `glGetIntegerv(GL_CURRENT_PROGRAM)` round-trip on the default-arg path of `set_matrices`/`set_object_id` (`:512,797`), paid per teapot draw per frame (`teapot.py:316`); sync MRT pick path re-queries GL state per-event instead of once per batch (`selection.py:549`).

- **MEDIUM — `glClientWaitSync` status discarded** (`selection.py:683`): on `GL_TIMEOUT_EXPIRED`/`GL_WAIT_FAILED` the code reads the PBO and dispatches events as if the GPU write completed. Also the overflow-drain (`selection.py:652`) can block the render thread up to 1s if the GPU falls >4 batches behind.

- **LOW — Dead code confirmed by grep:** `_flat.py:1286` `renderGeometry` (no callers), `shaderpass.py:1040` `ShaderRenderMode` (test-only), `selection.py:180` `read_depth` (no callers), `rendervisitor.py:191/237` unreachable `elif self.lighting` and a duplicated viewpoint-cycling algorithm; plus unused imports in `flatcompat.py`/`_flat.py`, a redundant local `import os` (`_flat.py:296`), five near-identical `_set_uniform*` methods and five hand-built texture-transform matrices in `shaderpass.py` that collapse into one helper each, and the stale "192 B" material-block comment (`pbrpass.py:616`, actual size 224 B).

- **Maintainability — god classes/methods** (all line-count-verified): `_flat.Render()` ~220 lines mixing diagnostics/pick-strategy/shadow/IBL/dispatch; `VRML97ShaderProgram` (6-program compile + uniform cache + material/light config + shadow-sampler allocation + texture-transform + pick-id); `ShadowMapMixin` ~735 lines (fps cascade controller + map-pool lifecycle + per-light dispatch + culling); `SelectionMixin` ~540 lines. Natural split points noted in the appendix data.

- **Design note (not a live bug):** `pbrpass._ubo_version` invalidation is correctly honored today, but `PBRMaterial` is a plain assignable node — a future `material.roughness = 0.3` in-place mutation of a cached factor would silently serve a stale UBO. Add a `__setattr__` bump hook or a documented "replace, don't mutate" convention.

---

<a id="sec-4"></a>
## 4. Geometry & material classes

The glTF/PBR geometry (`pbrmesh.py`, `pbrmaterial.py`) is the mature reference: cached VAO/VBO, GC-safe deferred delete, dynamic re-upload for morph/skin, and draw-state diffing with correct winding-flip under mirrored transforms. `teapot.py` follows the same discipline. The VRML97 legacy set has not caught up, and carries confirmed bugs:

- **HIGH — Double tessellation (`indexedfaceset.py:651-653`).** `vertices = self.tessellate()` runs the full (self-documented-as-expensive) tessellation, then the return value is discarded and immediately recomputed with `sources`. `tessellate()` is side-effect-free (verified), so the first call is pure wasted CPU — it unconditionally doubles the compile cost of every qualifying IFS. Delete line 651.

- **HIGH — `IndexedPolygons` has no shader path (`indexedpolygons.py:191-256`).** Its `render()` never checks `mode.shader_mode` and unconditionally issues `glEnableClientState`/`glVertexPointer` — calls that don't exist in core profile. Since `IndexedFaceSetCompile` *prefers* `IndexedPolygonsCompiler` (weight 1.05 > `ArrayGeometryCompiler`'s 1.0) for any IFS with per-vertex normals, `OPENGLCONTEXT_PROFILE=core` on ordinary per-vertex-normal content silently fails to render. Add a `_render_shader` mirroring `ArrayGeometry`/`Quadric`.

- **HIGH — `shadershape.py` is dead with a broken import.** Line 19 imports `create_shader_geometry`, which does not exist in `shadergeometry.py` — importing the module raises `ImportError`. Its own test is `@unittest.skip("shadershape module has broken import")` (`test_shaderpass.py:272`). It duplicates the live `Shape._render_shader`. Delete it and the skipped test.

- **HIGH — `DisplayListCompiler` is unreachable dead code with a latent `NameError`.** Its weight (0.9) can never beat `ArrayGeometryCompiler`'s 1.0, so it is never selected; and `indexedfaceset.py:728` references an undefined `vertexArray` that would raise if the path were ever hit. Delete it (it uses core-incompatible `glBegin`/`glEnd` anyway), or fix and test it.

- **MEDIUM — Three parallel material→uniform paths with no shared source of truth.** `material.py:69` (legacy `glMaterialfv`), `shaderpass.py:1200` (`configure_material_from_node`), and `pbrmaterial.py:176` (`material_to_pbr`) each independently read the same VRML97 `Material` fields with different derived semantics. Different lighting models legitimately need different values, but there is no test asserting they stay mutually consistent, and no shared "read raw fields" step. Centralize the read; cross-reference the three.

- **MEDIUM — `IFSCompiler.polygons()` builds a Python `dict` + `Vertex` object per vertex-use (`indexedfaceset.py:432-479`).** This is the real cause behind the file's top-of-file "needs serious optimization" XXX — O(vertices) pure-Python object churn where the rest of the module is vectorized numpy. Only paid on cache invalidation, but any coordinate/index update (skinning, morphing, streaming) pays it in full. Vectorize with `coordIndex`-based numpy gather.

- **MEDIUM — Winding/cull state setup duplicated across every geometry type** (`arraygeometry.py:127-209`, `indexedpolygons.py`, `quadrics.py`, `nurbs.py`) with no shared helper, so only `pbrmesh.py` has the negative-determinant winding-flip fix; the VRML97 geometry renders wrong winding under mirrored transforms. Extract a shared `apply_winding_cull(mode, ccw, solid)`.

- **LOW — `Material.sortKey` is an empty stub** returning `None` (`material.py:95`), and its only caller is commented out (`appearance.py:82`). Dead, misleading API — delete or implement.

---

<a id="sec-5"></a>
## 5. glTF & asset loaders (security-critical)

The glTF loader (`gltf.py`) has clearly had a serious security pass — numbered "finding" comments document fixes for path traversal (`_resolve_local` realpath containment), SSRF (`_ALLOWED_URL_SCHEMES`), OOB accessor reads (offset/span validated before `np.frombuffer`), and cache poisoning. Accessor decoding, sparse accessors, STEP/LINEAR/CUBICSPLINE interpolation, quaternion slerp, and skinning matrix order are all spec-correct. That work is solid.

The problem is that **the older loaders never received any of it**, and they are reachable from untrusted input:

- **CRITICAL — `loader.py:106-142`: unrestricted fetch + arbitrary local open.** `_Loader.get` opens any `url` that exists as a local path directly (`open(url,"rb")` — no containment, absolute paths and `../` accepted), and otherwise hands it to `urlretrieve` with no scheme allowlist (`file://`, `ftp://` accepted), no same-origin confinement, and no size cap. This is live: `imagetexture.py:240` calls `Loader(url, baseURL=baseURI)` for every `ImageTexture` (verified), and `obj.py:237/283` for `mtllib`/`map_Kd`. A crafted `.wrl`/`.obj`/glTF-with-external-texture with `file:///etc/passwd` or `http://169.254.169.254/latest/meta-data/` is fetched with zero guardrails — local file disclosure, cloud-metadata SSRF, and disk-exhaustion DoS. Give `_Loader` the same treatment `gltf._Resolver` already has: scheme allowlist, same-origin-as-baseURL, realpath containment, size cap.

- **CRITICAL — `gzpickle.py:53`: `pickle.load` on scene data.** Deserializing an attacker-controlled `.pkl.gz` is arbitrary code execution. No plugin registers `.pkl` today (only `vrml2pklgz.py` writes them, presumably from developer files), so it is not currently wired to untrusted input — but the module offers no warning and nothing stops a future caller from pointing it at a download. Never unpickle across a trust boundary; use a restricted `Unpickler` or a data format (JSON/msgpack). Also delete the dead `raise ImportError` hack at line 4.

- **HIGH — `obj.py` broken on Python 3.** `md5(baseURL)` (line 97) raises `TypeError: Strings must be encoded before hashing`, and `urllib.basejoin` (line 283) does not exist in Python 3 (`hasattr(urllib,'basejoin')` is `False` — both verified). The basejoin failure is swallowed by the bare `except:` at line 286, so textured OBJ models silently load without textures instead of failing loudly. Fix: `md5(baseURL.encode())`, `urllib.parse.urljoin`, and narrow the `except:` to log the exception.

- **HIGH — `gltf.py:379-396`: same-origin check bypassable via redirect.** The origin check validates the pre-request URL, but `urllib.request.urlopen` follows 3xx redirects without re-validating the destination. A same-origin URI that 302s to `169.254.169.254` defeats the guard. Disable redirects (raise on 3xx) or re-check origin on each hop.

- **HIGH — `gltf.py:1313-1333`: no size cap on the primary document.** `max_resource_bytes` bounds only *externally referenced* resources; a `.glb`/`.gltf` passed as `bytes` (the documented upload entry point) or a local path — including its inline `data:` buffers — is parsed with no ceiling. Cap `source` before handing it to `pygltflib`.

- **MEDIUM** — `loader.py:137` unbounded `urlretrieve` (disk-DoS); `gltf.py` accessor `componentType`/`type` raise bare `KeyError` instead of the located `ValueError` used everywhere else in the file; `_build_material` (~220 lines) and `_build_scene` (~160 lines with a 75-line nested closure over 15+ locals) are god functions that should become a per-extension table and a `_NodeBuilder` class.

- ✔ **Not a problem:** Pillow's `MAX_IMAGE_PIXELS` decompression-bomb guard is intact (never overridden — verified).

---

<a id="sec-6"></a>
## 6. Test suite

The suite is large (~293 files, ~40k LOC) but most of that is demo/tutorial *application* code, not test logic — real assertions live in the 141 `test_*.py` files plus the shared `OpenGLContext/testing/` library. `conftest.py` is well-designed (reusable `subprocess_runner`/`opengl_env`/`visual_regression_runner` fixtures, explicitly a single source of truth). The problems are duplication *around* it:

- **HIGH — The same ~114 GL scripts run 2–3× per pytest session (`test_all_scripts.py:892-1014`).** Three classes (`TestScriptCategories`, `TestAllScripts`, `TestVisualRegression`) each independently enumerate and subprocess-launch nearly the same script list; 114 scripts are identical between the hand-maintained `SCRIPT_CATEGORIES` table and the glob list, and the visual class launches most of them a third time to capture images. Each launch spins a real GL context under `coverage run`. Collapse to one parametrized runner that runs each script once and captures when it produces an image. **~220 LOC + 114–144 redundant GL subprocess launches per run.**

- **HIGH (latent bug) — Drifted `_check_display_available` (`test_visual_regression.py:174`).** `_check_display_available`/`_check_coverage_available`/`_build_coverage_command` are copy-pasted into three files, and the visual-regression copy is missing the EGL/OSMesa offscreen-detection fix that `test_all_scripts.py` has. On a headless CI box with `PYOPENGL_PLATFORM=egl` (the documented headless setup), the visual regressions **silently skip and read as green** — the exact false-pass the fix was written to prevent. Delete the three copies; route through the shared `OpenGLContext.testing` helpers. **~90 LOC + fixes the bug.**

- **MEDIUM — A fourth parallel regression/report framework.** `rendering_regression.py` (1403 lines) reimplements the "run → capture → diff → HTML report" pipeline (its own `TestResult`/`DiffResult` dataclasses, its own diff math, its own baseline-image directory separate from `tests/reference_images/`) that the shared `framebuffer_comparison`/`report_generator` already provide and that `test_all_scripts.py` already uses. `test_visual_regression.py` then invokes it 5× itemized *and* once un-filtered (a 6th full re-run). Retire the bespoke layer; drop the redundant full-suite run. **~150–250 LOC + 5–6 subprocess launches.**

- **LOW–MEDIUM** — `TestReportGenerator` is unit-tested in two files (`test_visual_regression.py` and `test_testing_infrastructure.py`); merge (~95 LOC). Two unit-test roots with different frameworks (`OpenGLContext/tests/` unittest-style vs `tests/` pytest-style) — consolidate to the documented one.

- **Correctly leave alone:** the 22 `shader_*.py` are literate-programming tutorials that `CLAUDE.md` explicitly protects; the project already reuses them by inheritance where it doesn't break the narrative (`shader_ng.py` extends `shader_11`). Do **not** collapse them into a shared base — the scaffolding is the pedagogy. The 22 `test_gltf_*.py` are cleanly feature-split (a good template for how the rest should be organized).

**Total readily removable: ~600–750 LOC plus several hundred redundant subprocess/GL-context spin-ups per full run**, the biggest lever being the triple-run runner collapse.

---

<a id="sec-7"></a>
## 7. General code health

- **173 `except Exception: pass`** silent swallows + **11 bare `except:`** in library code. Some are legitimate teardown-when-context-gone, but for a *rendering* library this scale of silent swallowing means users get a black screen and an empty log. Audit them; at minimum `log.debug(..., exc_info=True)` before swallowing.
- **Python-2 remnants that are latent runtime crashes, not just style:** ~15 tree-wide — `long()`×3 (the default-pick crash above), `cmp()`×1, `urllib.basejoin`×4 (`obj.py`, all `AttributeError`), plus `.iteritems()`/`.itervalues()`. These raise on execution, so a `grep -rn '\blong(\|\bcmp(\|basejoin\|iteritems\|itervalues'` sweep should be part of the "do first" batch. Separately, **19 files with `from __future__ import`** (dead on Python 3.9+) and **72 `print()`** calls in non-`bin/` library code (should be `logging`) are harmless mechanical cleanup.
- **God objects worth splitting for navigability:** `gltf.py` (2047 → accessors/materials/scenebuild), `_flat.py` (1526), `shaderpass.py` (1230), `context.py` (1114), `nurbs.py` (1023), `selection.py` (982), `indexedfaceset.py` (966).
- **Context-class glue explosion:** ~12 trivial mixin-combination files (backend × interactive/vrml/testing Cartesian product, 8–47 lines each). Minor, but a small factory would replace the lot.
- **Only one `eval`/`exec`** in the tree (`gltest.py:116`, running test scripts — expected and fine).

---

## What's genuinely good (do not regress this)

- **PBR/glTF pipeline:** UBO-based material data, compile-time feature gating to the real texture-unit budget, correct color management and two-sided handling, spec-correct accessor/animation/skinning decode.
- **Shadow subsystem:** clean separation of pure math / GL resources / capability detection / orchestration.
- **Instancing pass:** content-id hashing, per-slot partition caching, cached instanced VAOs — textbook.
- **glTF loader security:** realpath containment, same-origin SSRF guard, accessor bounds validation, texture/buffer dedup.
- **`conftest.py`:** genuinely reusable fixtures with a documented single-source-of-truth policy.

The lesson the codebase teaches itself: the modern half already knows how to cache GPU resources, secure untrusted input, and share code. The work is to bring the legacy half up to that same bar, not to invent anything new.

---

## Recommended action plan

**Do first (correctness + security, low effort, high impact):**
0. Replace `long()`→`int()` (`flatcompat.py:277`, `_flat.py:1427`, `renderpass.py:512`) and the `cmp` sort→`key=` (`renderpass.py:291`). Fixes a default-profile pick crash. *(CRITICAL, ~4 lines)* Then grep the whole tree for other `long(`/`cmp(`/`basejoin`/`has_key` remnants.
1. Fix `loader.py`/`obj.py` security (scheme allowlist, size cap, path containment) — mirror `gltf._Resolver`. *(CRITICAL)*
2. Fix `obj.py` Python-3 breakage (`md5(str)`, `basejoin`) and narrow its bare `except:`. *(HIGH, ~3 lines)*
3. Add the two-sided normal flip + attenuation guard to the VRML97 shaders. *(HIGH, ~4 lines)*
4. Delete line `indexedfaceset.py:651` (double tessellation). *(HIGH, 1 line)*
5. Add a `_render_shader` to `IndexedPolygons`, or reweight so core-profile IFS never routes to it. *(HIGH)*

**Do next (perf — the churn cleanup):**
6. Cache VAOs in `shadergeometry.py`; convert `pointset.py` and `indexedlineset.py` to cached VAO+VBO with `set_array` re-upload. *(HIGH perf; pattern already in `pbrmesh`/`instancing`)*
7. Hoist in-function `import numpy`/`import ctypes` out of hot paths.

**Cleanup (dead code + dedup):**
8. Delete `shadershape.py`, `DisplayListCompiler`, `shaders/generator.py`, `gzpickle.py`'s dead hack (and either remove or sandbox `pickle.load`).
9. Fold `vrml97_vertex_color.frag` onto `_lights_inc.glsl`; fix the stale std140 comments.
10. Collapse the triple-run test runner; dedupe the three `_check_display_available` copies (fixes the headless false-skip); retire `rendering_regression.py`'s bespoke report layer.

**Backlog:**
11. Split the god objects; centralize the three material→uniform paths; vectorize `IFSCompiler.polygons()`; audit the 173 silent exception swallows.
