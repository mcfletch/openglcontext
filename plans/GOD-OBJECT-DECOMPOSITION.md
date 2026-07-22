# God-Object Decomposition (§3n + §7c)

**Date:** 2026-07-14
**Source findings:** [CODE-REVIEW-2026-07-13.md](CODE-REVIEW-2026-07-13.md) §3n (god classes/methods in the passes layer) and §7c (god files project-wide).
**Status:** Done (branch `refactor/god-object-decomposition`, one commit per file).

## Outcome

All eight targets decomposed behaviour-preservingly; every public import path and
node registration is unchanged (verified by re-import + the existing suites).
Per-file result:

| File | Before | After (facade) | New modules |
|------|-------:|---------------:|-------------|
| `passes/selection.py` | 985 | 420 | `selectionbuffers.py` (FBO classes), `asyncpick.py` (`_AsyncPickMixin` + `_dispatchPickEvent`) |
| `scenegraph/indexedfaceset.py` | 965 | 261 | `ifscompiler.py` (all 4 compilers + `IndexedValueSource` + registry) |
| `scenegraph/nurbs.py` | 1012 | 637 | `nurbstess.py`, `nurbssampling.py`, `nurbstrim.py` |
| `passes/shaderpass.py` | 1254 | 1016 | `shadersource.py` (assembly), `shaderpass_shadow.py` (`_ShadowUniformMixin`) |
| `context.py` | 1114 | 941 | `contextconfig.py` (`ContextConfigMixin`) |
| `loaders/gltf.py` | 2142 | 186 (`gltf/__init__.py` facade) | full package: `resolver`, `accessors`, `textures`, `specular_glossiness`, `transforms`, `materials`, `meshes`, `animation`, `scene`, `loader`, `samples` |
| `passes/shadowmixin.py` | 790 | 660 | `shadowpool.py` (`_CascadeControllerMixin`, `_ShadowMapPoolMixin`) |
| `passes/_flat.py` | 1550 | 1265 | `flateffects.py` (`_FlatEffectsMixin`: IBL/transmission/bloom/cull) |

Verification: 340 pure-Python + GL tests across the touched areas pass (shaderpass,
material, shadow, gltf, selection, IFS, NURBS, deferred-transparent, pbr,
instancing) plus off-screen renders (shadows, bloom, IBL, transmission, NURBS,
IFS, picking). Three test files had a patch/seam target repointed to the module a
function moved to (`test_pick_fence_status` → `asyncpick`; two `test_gltf_loader`
fetch patches → `gltf.resolver`) — the review did the same when a seam moved
(finding 12). `test_instance_cluster_cull_gl` fails identically at the branch
point (pre-existing sandbox subprocess issue), untouched by this work.

### gltf core split — done (follow-up completed)
The tightly-interleaved core was split the rest of the way into a full package:
`__init__` is now a 186-line re-export facade over bottom-up layers
(`resolver → accessors → {textures, transforms, specular_glossiness} → materials →
meshes → animation → scene → loader`, plus `samples`). `gltf_animation.py` moved
into the package and merged with the animation *parsing* into one `animation`
module (runtime + parse are one domain). The archived `KHR_materials_pbrSpecularGlossiness`
conversion got its own `specular_glossiness` module (it is a plug-in extension
adapter, not part of the core metallic/roughness model). Sloppy mid-module imports
were lifted to module scope; optional deps (PIL, pygltflib) stay lazy by design.
Test seams that reached moved internals repointed to the owning submodule
(`gltf.resolver.base64`/`urllib`, `gltf.animation`). Behavior preserved: 184
loader/pbr/skin/morph/anim tests pass (the 4 pre-existing spot-light/screenshot
failures fail identically on the pre-split monolith).

### Deliberately left (own follow-ups, not this change)
- **§3h** dead legacy fixed-function path in `_flat.py`: its own task (it carries
  a `super()`-call check against `flatcompat`'s overrides).
- **§7d** the ~12 trivial context-glue files (a factory would replace them).

## Scope

§3n and §7c overlap almost completely. §7c's file list — `gltf.py`, `_flat.py`,
`shaderpass.py`, `context.py`, `nurbs.py`, `selection.py`, `indexedfaceset.py` —
plus `shadowmixin.py` (which holds §3n's `ShadowMapMixin`) covers **every** class
and method named in §3n. Treating them as one program avoids doing `_flat` /
`shaderpass` / `selection` twice. Eight files, ~9,800 lines.

| File | Lines | §3n | §7c | Primary god unit |
|------|------:|:---:|:---:|------------------|
| `passes/_flat.py` | 1550 | ✓ | ✓ | `FlatPass` + its 224-line `Render()` sequencer |
| `loaders/gltf.py` | 2142 | | ✓ | module: resolver + accessors + materials + scene + anim parsing |
| `passes/shaderpass.py` | 1254 | ✓ | ✓ | `VRML97ShaderProgram` (50 methods) |
| `context.py` | 1114 | | ✓ | `Context` (config/factory + render core + hooks) |
| `scenegraph/nurbs.py` | 1012 | | ✓ | `_SurfaceRenderer` + tess service + math + trims + sampling |
| `passes/selection.py` | 985 | ✓ | ✓ | `SelectionMixin` + 2 FBO classes |
| `scenegraph/indexedfaceset.py` | 965 | | ✓ | `IndexedFaceSet` node + 4 compilers |
| `passes/shadowmixin.py` | 790 | ✓ | | `ShadowMapMixin` |

## The decomposition model

These are **behavior-preserving** refactors. The guiding rule is *cut along the
seams the code already has* and prefer the least-magical mechanism that fits each
seam. Three mechanisms, in order of preference:

1. **Extract to a sibling module** — for code with **zero `self` coupling**:
   free functions, self-contained resource classes, pure math. Safest possible;
   provably equivalent. (shader-source assembly, the selection FBO classes,
   NURBS knot math, the IFS compilers.)

2. **Extract a cohesive method-cluster to a mixin** — for methods that share
   `self` state but form one clear concern. The public class keeps its **name and
   MRO position**, so importers and tests never change. (the shadow-uniform
   cluster on `VRML97ShaderProgram`; the IBL / transmission / bloom / pick
   clusters on `FlatPass`; the config cluster on `Context`.)

3. **Promote a module to a package** — for a file that is several equal-weight
   concerns with a shared substrate. `__init__.py` re-exports the public API so
   `from …loaders.gltf import load_gltf` keeps working. (`gltf.py`.)

**Invariant across all three:** every symbol any other module or test imports today
keeps its current import path, via re-export from the original module/facade. The
API contract (verified against the tree) that must stay importable from
`passes.shaderpass`: `VRML97ShaderProgram`, `SHADER_DIR`, `preprocess_shader`,
`get_shader_program`, `texture_transform_matrix`, `normal_matrix`,
`configure_light_from_node`, `configure_material_from_node`. From `loaders.gltf`:
`load_gltf`, `load_gltf_url`, `GLTFScene`, `look_orientation`, `_local_matrix_rv`,
`SAMPLE_MODELS_BASE`, `SAMPLE_MODELS`. Node registrations in `OpenGLContext/__init__.py`
(`IndexedFaceSet`, `NurbsSurface`, `TrimmedSurface`, …) pin the fully-qualified
class paths — those classes must stay in their named modules (so the *node* stays
put and the *compilers/helpers* move out beneath it).

Why mixins and not composition-by-delegation for the pass/shader classes: the
method clusters call back into shared `self` state (`_set_uniform*`, `self.matrix`,
the program handles) dozens of times. Delegation would force threading a back-
reference through every call and rewrite every call site — large diff, real
behavior risk. Mixins keep the exact call graph; the only change is which file a
method's `def` lives in. That is the "beauty" tradeoff here: the smallest diff that
makes each file a single-responsibility unit, not the most theoretically-pure
object graph.

## Per-file target shape

### `passes/selection.py` → `selection.py` + `selectionbuffers.py`
- **`selectionbuffers.py`**: `SelectionFBO`, `SelectionBufferFBO` — already fully
  self-contained (no reference to the pass). Mechanism 1. Cleanest cut in the set.
- `SelectionMixin` keeps the pick orchestration; the async-PBO cluster
  (`_acquirePBO`/`submitAsyncPicks`/`drainAsyncPicks`/`_resolveBatch`/…) becomes
  `_AsyncPickMixin` (mechanism 2). Collapse the 3× duplicated event-dispatch block
  into one `_dispatchPickEvent`, and the 4× id encode/decode into helpers that
  preserve the **two distinct conventions** (raw 32-bit for MRT/async vs. `<<12`-
  shifted for the legacy color path — not interchangeable).

### `scenegraph/indexedfaceset.py` → node + `ifscompiler.py`
- **`ifscompiler.py`**: `IFSCompiler`, `ArrayGeometryCompiler`,
  `IndexedPolygonsCompiler`, `DisplayListCompiler`, `IndexedValueSource`,
  `build_normalPerVertex`, `getXNull`, `DummyRender`/`DUMMY_RENDER`,
  `DisplayListRenderer`, `COMPILER_CLASSES`. Registry seam is exactly two
  touchpoints. Mechanism 1.
- `indexedfaceset.py` keeps the `IndexedFaceSet` node (registration path pinned),
  imports the compilers, re-exports `build_normalPerVertex` (tests use it).

### `scenegraph/nurbs.py` → node + `nurbsmath.py` + `nurbstess.py` + `nurbstrim.py` + `nurbssampling.py`
- **`nurbsmath.py`** (pure, mechanism 1): knot validation (`degree`, `uniform`,
  `allIncreasing`), `_control_point_sphere`, `NURBS_LOD_STEPS`/`nurbs_lod_steps`.
- **`nurbstess.py`** (GL tess service): `NURBSTessellatorCallback`,
  `_get_tess_callback`, `_tessellate_nurbs_surface`, `_build_nurbs_vbo`.
- **`nurbstrim.py`**: `Polyline2D`, `NurbsCurve2D`, `Contour2D`.
- **`nurbssampling.py`**: `NurbsSampling` + subclasses, `defaultSampling`,
  `initialise`, `object_space_tess` state.
- `nurbs.py` keeps `_SurfaceRenderer`, `NurbsSurface`, `TrimmedSurface`,
  `NurbsCurve` (registration paths pinned). *(Note the pre-existing latent bug at
  the old `nurbs.py:888` — `Numeric.shape` with `Numeric` never imported, in a dead
  `weight` branch. Preserve as-is under this refactor; fix separately.)*

### `passes/shaderpass.py` → module + `shadersource.py` + shadow mixin
- **`shadersource.py`** (pure, mechanism 1): `_resolve_includes`,
  `preprocess_shader`, `shadow_defines`, `load_fragment_source`, and the
  `SHADER_DIR`/include constants. Re-export `SHADER_DIR`/`preprocess_shader`.
- `VRML97ShaderProgram`'s shadow subsystem (~250 lines, the largest cohesive
  cluster: `bind_*slot`, `bind_shadow_array`, `set_shadow_*`, `init_shadow_samplers`,
  `_shadow_prog`, …) → `_ShadowUniformMixin` in `shaderpass_shadow.py`
  (mechanism 2). The uniform-cache substrate (`_get_location`, `_set_uniform*`,
  `_uniform_unchanged`, `_set_matrix_cached`) → `_UniformCacheMixin`, kept as a
  base every other cluster inherits.
- `shaderpass.py` composes the mixins into `VRML97ShaderProgram` and re-exports
  the module-level helpers tests import.

### `context.py` → `Context` + `contextconfig.py`
- **`contextconfig.py`** `ContextConfigMixin` (mechanism 2, ~245 lines, almost
  entirely classmethods): app-data dir, TTF-font prefs, backend prefs,
  entry-point resolution, `fromConfig`. Self-contained; strongest seam in the file.
- Optional follow-ons (auto-exit, threading, redraw mixins) if the file is still
  heavy after the config cut.

### `loaders/gltf.py` → package `loaders/gltf/`
- `__init__.py` re-exports the public API. Submodules: `resolver.py` (security
  core — `_Resolver`, origin/redirect/size/`data:` handling), `accessors.py`
  (dtype maps, `_read_accessor`, sparse, typed readers), `materials.py`
  (`_build_material`, `_ext_*` table, texture collector, spec/gloss),
  `scene.py` (`_SceneBuilder`, primitives, transforms, cameras, lights),
  `animparse.py` (animation/skin *parsing* → `gltf_animation` objects),
  `samples.py` (Khronos sample catalog). Shared substrate (`_check_size`, `log`,
  the accessor dtype maps) lives in `resolver.py`/`accessors.py` and is imported
  by the rest. Highest effort (the `resolver` param threads through most
  functions) but the bucket boundaries are clean.

### `passes/shadowmixin.py` → `ShadowMapMixin` + helpers
- `_CascadeController` (fps-adaptive cascade count; self-contained state machine).
- `_ShadowMapPool` (lazy pool alloc + `disposeShadowMaps`).
- Move the remaining static caster/AABB/depth math into `shadowmath.py` (its
  existing pure-math home).
- `ShadowMapMixin` keeps `renderShadowMaps` orchestration, per-light dispatch,
  `bindShadowUniforms`, and the depth pass.

### `passes/_flat.py` → `FlatPass` + concern mixins (riskiest; last)
- Mixins in sibling modules: `_IBLMixin`, `_TransmissionMixin`, `_BloomMixin`,
  `_PickMixin` (the `_objectIdFor`/`_writeShapeId`/`selectRender` helpers),
  `_DiagnosticsMixin` (first-frame logging + fps overlay), `_CullMixin`.
- Delete the unreachable legacy `else` branch and the four dead legacy methods
  (this is also §3h) — **only** after confirming `flatcompat` overrides them and
  never calls `super().legacy*`.
- `FlatPass` keeps the render engine (`renderSet`, `shaderRenderOpaque/Transparent`,
  `setupShaderLights`) and the `Render` sequencer, now a thin phase list.

## Execution order (safest / highest-clarity first)

1. `selection.py` — FBO extraction (zero coupling)
2. `indexedfaceset.py` — compiler extraction (clean registry seam)
3. `nurbs.py` — pure-math + tess-service extraction
4. `shaderpass.py` — source-assembly module + shadow/uniform mixins
5. `context.py` — config mixin
6. `gltf.py` — package split
7. `shadowmixin.py` — cascade controller + map pool
8. `_flat.py` — concern mixins + dead-legacy deletion

## Verification per file

Each file is its own commit/theme:
1. Extract with no logic change; keep re-exports.
2. `python -c "import …"` for the module **and every importer**.
3. Run the file's unit tests (e.g. `test_shaderpass.py`, `test_gltf_loader.py`,
   `test_shadowmixin.py`, `test_material_fields.py`, `test_select_render_shared.py`).
4. Off-screen GL render smoke (GLFW hidden window) for anything touching a render
   path; non-black pixel count unchanged.
5. Add a small structural guard test where a seam is newly public (e.g. the pure
   NURBS math, the IFS compiler module) so the split can't silently regress.
