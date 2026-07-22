# Complete glTF 2.0 Support and Rendering Correctness

**Status: RESOLVED** — the gap list this plan catalogued has been implemented. Animation,
skinning, morph targets (§1), the full geometry set — second UV `TEXCOORD_1`, sparse accessors,
non-triangle primitive modes, computed tangents (§2) — every `KHR_materials_*` extension and
`KHR_texture_transform`/unlit/specGloss (§3, delivered alongside
[PBR-BRDF-CONFORMANCE.md](PBR-BRDF-CONFORMANCE.md)), `KHR_lights_punctual` (§4), real IBL,
alpha blend, and screen-space transmission all landed and are tested. Loader robustness — sampler
state/mipmaps, background/async load, camera auto-framing — is in place. **The one deliberate
remainder is `KHR_draco_mesh_compression`, tracked separately in
[DRACO-COMPRESSION.md](DRACO-COMPRESSION.md).** Extension-level conformance details and the
prioritised remaining polish live in [PBR-BRDF-CONFORMANCE.md](PBR-BRDF-CONFORMANCE.md) and the
GLTF-FULL-FEATURE / GLTF-DEMO conformance tracks. The original in-progress notes and gap tables
below are kept for reference/provenance.

**Builds on:** [PBR-MATERIALS.md](PBR-MATERIALS.md) (the v1 PBR pass + glTF/GLB loader + sample-model
viewer) and [SHADOW-MAPPING.md](SHADOW-MAPPING.md) (shared shadow subsystem).

## Session status — resume here (end of day)

**Landed today (staged, shader compiles, 21 PBR/glTF tests pass):**

1. **CAD / camera-bearing models no longer render black** (Buggy, 2CylinderEngine,
   GearboxAssy, ReciprocatingSaw, …). Two root causes fixed in `loaders/gltf.py`:
   - Model bounds were computed with **column-major** matrices while rendering uses
     **row-vector** `Transform` nodes; for deep CAD hierarchies the framing was
     wrong. Bounds now use `_local_matrix_rv` (`transformmatrix.transformMatrix`),
     identical to what the `Transform` applies. (Note: `transformMatrix` returns a
     0-d scalar for an identity transform — guarded.)
   - The viewer was **adopting embedded glTF cameras**, which produced broken views
     (near=0, model off-frame). The viewer now **always auto-frames** (tightened to
     fill the view); `_adopt_camera`/`_orientation_from_forward` removed.
2. **Material extensions implemented** (loader + `PBRMaterial` fields + `pbr.frag`
   + `PBRShaderProgram.set_pbr_extensions`): `KHR_materials_unlit`,
   `_emissive_strength`, `_specular` (+ `_ior` → F0), `_clearcoat`, `_sheen`,
   `pbrSpecularGlossiness` (→ metal/rough at load), and `KHR_texture_transform`
   (single base-UV transform applied to all channels). The loader parses them and
   the shader has lobes/branches; **a missing `ior` uniform declaration broke the
   shader compile (this was the "RiggedSimple shader compilation failure" — it
   actually killed ALL PBR rendering) and is now fixed.**

**Done but NOT yet verified against each sample model** (do this first tomorrow —
render UnlitTest, EmissiveStrengthTest, SpecularTest, SpecGlossVsMetalRough,
ClearCoatTest, SheenChair, TextureTransformTest against their references via
`tests/pbr_gltf_demo.py`, e.g. `MODEL=UnlitTest python tests/pbr_gltf_demo.py`).

**Known issues still open (reported today, NOT yet fixed):**

- ~~**Transform decomposition is lossy**~~ **FIXED.** `_transform_for` now wraps
  matrix-bearing nodes in `MatrixTransform`, applying the exact glTF matrix
  instead of decomposing into TRS. The old decomposition silently dropped
  180-degree rotations (ambiguous axis) and mirrors (negative-determinant
  bases), which misplaced a subset of parts in Buggy / GearboxAssy /
  ReciprocatingSaw / 2CylinderEngine. See the Performance/Transform notes below
  and `tests/test_matrix_transform.py`.
- **CesiumMilkTruck** shows broken textures (investigate: multiple images/UV sets
  or sampler/format edge case).
- **Rendering is far too slow** — *substantially addressed* (see "Performance"
  below): per-frame VAO churn and the per-frame full-screen MRT id/depth
  readback (a GPU stall) are both removed. Shadow-on cost is still untuned
  (static shadow caching deferred).
- The larger features below (animation, skinning, morph, transmission, real IBL)
  are still unstarted.

**Next-up order:** (1) verify the material extensions render correctly; (2) fix the
transform-matrix decomposition (high impact — affects many CAD models); (3)
**profile + fix performance** (likely the single biggest UX win); (4)
CesiumMilkTruck textures; then (5) animation → morph → skinning → transmission →
IBL per the phasing below.

## Performance (profile first, then fix)

**Progress (this session):**

- **Per-draw VAO churn — FIXED.** `PBRMesh.render` no longer generates and
  deletes a VAO (and re-specifies five attribute pointers) every frame. GPU
  resources now hang off the property-based scenegraph cache (`mode.cache`,
  keyed per node) as a `_MeshGPU` built once: the VAO records the attribute and
  element-buffer bindings, so a frame is `glBindVertexArray` + draw. The
  animated 200-primitive harness allocates **200** VAOs for a whole 200-frame
  run (one per mesh) versus **40 400** before (one per mesh per frame), and
  per-frame submission is ~25% faster even on the container's software
  rasteriser (where GPU fill dominates and understates the win). See
  `tests/_pbr_perf_harness.py` (A/B `cached` vs `uncached`) and
  `tests/test_pbr_performance.py`.
- **Per-draw winding determinant — CACHED.** `np.linalg.det(mv[:3,:3])` is now
  computed only when the modelview's upper-3×3 changes, not every draw.
- **FBOs already persist.** Selection, MRT-selection, and shadow-map FBOs are
  created lazily and cached on the `FlatPass` instance, and that instance is
  cached globally (`renderpass._defaultRenderPasses`, rebuilt only when the
  scenegraph reference changes) — so they are *not* re-allocated per frame.
- **Transforms already cached.** `path.transformMatrix()` is memoised with
  field-dependency invalidation in `vrml.vrml97.nodepath`, so the flat-pass walk
  does not recompute world transforms for unchanged nodes.

- **MRT selection FBO — bypassed entirely when not picking.** The selection
  pass rendered the whole scene into a two-attachment FBO, read the *entire* id
  **and** depth buffers back to the CPU (a full `glReadPixels` — a GPU pipeline
  stall), and blitted to screen **every frame**, even when nothing was picking.
  All of it (FBO bind, second render target, readback, blit) now runs only while
  picking is active (`_pick_warm_frames`, reset whenever pick events arrive);
  idle frames render straight to the default framebuffer. This removes a
  full-screen render-target + blit + CPU/GPU sync per frame — the most likely
  cause of the "single-digit/15-20 fps with a far-from-saturated GPU" symptom,
  and of the residual just-under-60 vsync misses. Picking keeps its one-frame
  latency (first pick after a long idle may use a stale buffer once).
- **Redundant per-draw sampler init removed.** `bind_pbr_textures` re-set the
  five constant sampler→unit uniforms on every draw; those are set once at
  compile.
- **Opaque drawn front-to-back (early-z / less overdraw).** Opaque PBR shapes
  all share one `sortKey`, so they drew in arbitrary order and occluded
  fragments still ran the full (expensive, shadow-PCF) PBR fragment shader —
  cost that scales with pixel count, i.e. *worse at full screen*. The opaque
  pass now sorts by eye-space depth (nearest first) so the GPU's early depth
  test rejects occluded fragments before the fragment shader. Depth test still
  guarantees identical output; this only reorders draws. (The shader's
  alpha-MASK `discard` limits early-z on some GPUs; a no-discard opaque shader
  variant or a depth pre-pass — the minimal depth-only program below — is the
  next step if overdraw is still high.)

**Transform decomposition — FIXED (the misplaced-subset bug).** glTF nodes that
carry a raw `matrix` were decomposed into translation+axis-angle+scale, which
**silently drops 180-degree rotations** (the axis `[r21-r12, …]` collapses to
zero at 180°, falling back to *no rotation*) and cannot represent mirrors
(negative-determinant bases) — so a *subset* of parts in Buggy / GearboxAssy /
ReciprocatingSaw / 2CylinderEngine came out wrong while the rest looked fine.
The loader now wraps such nodes in a new `MatrixTransform`
(`scenegraph/transform.py`) that applies the exact matrix (row-vector =
`reshape(4,4)` of the column-major glTF array, no transpose), with the inverse
for the reverse path; bounds use the same baked matrix. Covered by
`tests/test_matrix_transform.py`.

- **The displayed fps was a misleading lifetime average.** The on-screen
  `fps avg` was `count/totalTime` — a *cumulative* average. The timed region in
  `Context.OnDraw` starts before `DoEventCascade`, and a model switch loads the
  next asset **synchronously** there (network fetch + glTF decode, often
  seconds), so every load — and the first-frame shader compile — dumped seconds
  into `totalTime` and **permanently** dragged the number down. Much of the
  "still not 60 fps" was this artifact, not the live render rate. The counter
  now keeps a window of recent frame times and displays the **median** rate
  (`FrameCounter.recentFps`), which ignores one-off load/compile spikes.
  (`tests/test_framecounter_rate.py`.) *Re-measure with this before chasing more
  render-time perf.* (A proper fix for the stall itself is background asset
  loading — see Loader robustness §5.)
- **Redundant uniform uploads skipped.** `_set_uniform*` now caches the last
  value per (program, uniform) and skips the `glUniform` call when unchanged, so
  shared/default materials across many shapes stop re-uploading ~30 uniforms
  each. Safe (the cache mirrors exactly what was uploaded).

- **Per-shape draw-submission overhead cut (VirtualCity et al.).** Profiling
  VirtualCity (167 shapes, 167 distinct materials, mostly a textured backdrop —
  so *submission*-bound, not fill-bound) showed `configure_appearance` +
  `set_matrices` at ~60% of the frame. Fixed: (a) the opaque/transparent loops
  pass the program to `set_matrices`/`set_object_id`, removing a per-shape
  `glGetIntegerv(GL_CURRENT_PROGRAM)` round-trip (×2); (b) the projection matrix
  (identical for every shape in a frame) and the `uvTransform` mat3 (identity
  for almost all materials) upload only when their bytes change, not per shape;
  (c) the identity uvTransform is a cached constant, not rebuilt per call. Frame
  CPU dropped ~16% even on the software rasteriser (where the removed GL calls
  are cheap); on a real driver the removed round-trips/stalls matter more, and
  shaving a few ms can flip a vsync-quantised 30 fps to 60.

**Still open (next iteration):**

- **Material uniforms → std140 UBO — DONE.** The ~20 static per-material factors
  moved into an anonymous `MaterialBlock` uniform block (`shaders/pbr.frag`,
  `pbrpass.pack_material_block`), uploaded once per material and cached across
  frames (`WeakKeyDictionary`); a shape now switches materials with one
  `glBindBufferBase` instead of ~20 `glUniform` calls. Only
  alpha/alphaMode/transmission/`hasX` stay as plain (frame/pass-dependent)
  uniforms. std140 offsets validated against the driver. `configure_appearance`
  dropped from ~0.275→0.089 s and Buggy's per-frame call count roughly halved.
  Also added a per-shape material *object* early-out + material-grouped opaque
  draw order for the reuse case. **Next lever after the UBO: instancing —
  see TODO below.**
- **Per-object normal matrix — DONE (cofactor form).** `set_matrices` now uses a
  direct 3×3 cofactor/determinant inverse-transpose (`shaderpass.normal_matrix`),
  ~3× faster than `np.linalg.inv`, halving `set_matrices`. (The earlier "cofactor
  is slower" note was measured with per-element numpy indexing; a `.tolist()`
  pure-Python solve is the fast path.)
- **TODO — GPU instancing / multi-draw batching.** After the UBO, the remaining
  per-frame cost on the heavy CAD/skeleton samples (Buggy/GearboxAssy/BrainStem)
  is *submission-bound*: one `glBindVertexArray` + matrix uploads + draw per
  shape, hundreds of times a frame. The structural fix is to stop issuing a draw
  per shape:
  - Batch shapes that share a mesh + material via instanced draws
    (`glDrawElementsInstanced`), feeding per-instance model matrices (and
    per-instance material-UBO index) through an instance buffer / SSBO-style
    attribute — the natural home for glTF `EXT_mesh_gpu_instancing` too.
  - Or a multi-draw path (`glMultiDrawElementsIndirect`) for distinct-mesh
    scenes, with per-draw material selected by `gl_DrawID`.
  Needs a per-context instance-buffer manager, a batching pass over `toRender`
  (group by (mesh, material)), and vertex-shader changes to read the model matrix
  and normal matrix per instance. Big change; do it when submission is the
  confirmed cap (py-spy now shows matrix uploads + draw calls dominating).
- **Model loads block the render thread** (synchronous network + decode in the
  event cascade), freezing the UI per switch. Background download/decode would
  fix the stall itself (and is what poisoned the old cumulative fps average).
- Same VAO churn remains in the VRML97 `shadergeometry` path
  (`render_shader_interleaved` / `render_shader_arrays`).
- Static shadow caching (deferred deliberately — speculative; see below).

**Environment (root cause of "the 3060Ti is never saturated"):** the dev
container was rendering on **llvmpipe (CPU software)**, not the GPU, because
`libnvidia-egl-wayland.so` couldn't load — its dependency `libwayland-server0`
was missing from the image, so GLVND silently fell back to Mesa/llvmpipe. Fixed
in `.devcontainer/Dockerfile`. `GL_RENDERER` is now logged once at startup (with
a loud warning if it contains llvmpipe/softpipe/swrast) — see
[[devcontainer-wayland-nvidia-llvmpipe]]. **All pre-fix perf numbers were
software-rendering.** On the GPU, VirtualCity went 30→138 fps.

**Shadows (this session):**

- **Depth-only shadow program.** The depth pre-pass ran the full lit PBR
  fragment shader; a minimal position-only program (`shadow_depth.vert/frag`,
  `use_depth()`) now writes depth without lighting/texture/PBR work.
- **Per-pass shadow syncs removed.** Each cascade/cube-face did a
  `glCheckFramebufferStatus` + `glGetIntegerv` save/restore every frame,
  serialising the ~22 depth passes; FBOs are now validated once and the render
  target is saved/restored once per batch.
- **Adaptive cascades (VRAM + fps gated).** Directional CSM cascades are a
  premium: `ShadowCapabilities` now queries total VRAM (NVX/ATI meminfo), and
  the effective cascade count ramps up only with VRAM headroom (≥6 GB → full
  budget) *and* sustained fps well above 60, shedding a cascade the instant fps
  hits 60 (with a cooldown to avoid oscillation). Box + 4 shadow lights went
  21→106 fps. The 1→N cascade cost is anomalously steep (1 cascade ~1 ms, each
  extra ~6–13 ms at 2048²) — a fill/clear slow path not yet root-caused
  (immutable `glTexStorage3D` didn't fix it).
- **Per-cube-face occluder culling.** Point-light faces now cull occluders to
  the face frustum (empty faces still clear to "lit"). Helps scattered scenes;
  little gain on compact ones (fill-bound).

**Still open:** shadow-map generation is fill-bound at 2048/1024 (a compact
scene's shadows still cost ~30 ms with 4 lights); cube-*face* view-frustum
culling (skip faces the camera can't see) and a static-shadow cache are the next
levers. "Maximise-window freezes" is a *framebuffer-scaling* cost (main-pass
fill + shadow PCF), distinct from the window-independent generation cost.

Symptoms: frame rate *hovers* near ~30 fps (not a hard, consistent cap — it
varies), and enabling shadows drops to single-digit fps; the 3060Ti is far from
saturated. The variability rules out a simple vsync lock; this reads as
CPU-side / draw-submission overhead plus redundant per-frame work. Profile (e.g.
`py-spy` / `cProfile` on a single static model, and a GPU timer query around the
passes) and check these prime suspects:

- **Use the existing cache system — don't reinvent it.** The scenegraph already
  has a sophisticated cache (`mode.cache` / `context.cache` holders with
  field-dependency invalidation, as `arraygeometry`/`IndexedFaceSet` use to cache
  compiled geometry, and `boundingvolume.cacheVolume`/`getCachedVolume`). The PBR
  path should hang its GPU resources off the same cache rather than rebuilding them
  per frame. In particular:
- **Per-draw VAO churn.** `PBRMesh.render` calls `glGenVertexArrays` +
  `glVertexAttribPointer`(×5) + `glDeleteVertexArrays` **every frame for every
  primitive** (a CAD model has 100–250 shapes). Build the VAO+VBOs once and cache
  them via the cache holder (invalidate on the geometry fields), then just
  `glBindVertexArray` + draw. Same churn likely in the VRML97 `shadergeometry` path.
- **Per-draw numpy in the hot loop.** `PBRMesh.render` runs `np.linalg.det(mv[:3,:3])`
  every draw (winding); `set_matrices` does an inverse-transpose normal matrix per
  object. Cache these (winding is constant per mesh+parent-parity; normal matrix
  per object-transform).
- **Python-per-object render submission.** The pass walks paths, recomputes
  `transformMatrix()`, sets matrices/object-id, and calls `Render(mode)` per shape
  in Python — hundreds of times. Cache transform matrices (the cache already tracks
  transform-field changes) and reduce per-object uniform churn.
- **Static shadow caching (big win for typical scenes).** Most scenes are a *few
  moving objects in a static set*. Cache each **static light's depth map of the
  static geometry once**, then per frame re-render only **moving/mobile geometry**
  on top of (a copy of) that cached depth — so shadow cost scales with the mobile
  subset, not the whole scene. Pairs with: a minimal depth-only program (positions
  only, no fragment work — currently the depth pass reuses the full lit/PBR
  fragment shader and discards it), and the per-light occluder culling already
  designed in SHADOW-MAPPING §"Light and occluder culling". Identify static vs
  mobile via the same field-dependency signals the cache uses (a node whose
  transform/geometry hasn't changed is static).
- **MRT selection buffer every frame.** The pass renders object-IDs to a second
  attachment + reads back for picking even when nothing is picking; check whether
  that (and the blit) is a meaningful cost.

Target: a single static glTF model should run at hundreds of fps on this GPU;
shadows on a mostly-static scene should cost a small increment (only the mobile
geometry re-rendered), not 5–10×.

## Goal

Close the gap between the v1 glTF importer/PBR renderer and the Khronos
`glTF-Sample-Models` reference renders. This plan was written from a QA pass that
browsed all 88 models in the viewer ([tests/pbr_gltf_demo.py](../../tests/pbr_gltf_demo.py))
and compared each against its README reference screenshot. It records every
observed discrepancy, separates **rendering-correctness bugs** from
**unimplemented features**, and lays out the work to reach reference parity.

Each item names the sample model(s) that expose it — those double as acceptance
test cases.

## Already fixed (v1.1, this session)

For context — these were found during the same QA pass and are **done**:

- **Vertex colors** (`COLOR_0`) — BoxVertexColors, BoxAnimated. Loader reads the
  accessor; shader modulates base color (location 4 + `hasVertexColor`).
- **Grayscale / luminance-alpha textures read back wrong color** — the
  TextureLinearInterpolationTest "white" cards rendered yellow because an `LA`
  image was uploaded as 2-channel RG (`white → (lum, alpha, 0)`). Loader now
  normalises every image to RGBA.
- **Metals looked like glossy plastic** — MetalRoughSpheres, NormalTangentTest,
  NegativeScaleTest. Added a cheap **analytic environment** (sky/ground gradient)
  for ambient diffuse + a roughness-blurred specular reflection, so metals read
  as metal. (A stand-in for real IBL — see §3.1.)
- **Negative scale flipped front/back culling** — NegativeScaleTest. Front-face
  winding is now chosen from the modelview determinant.
- **Tiny models rendered black** — Avocado, Corset, ToyCar (radius ~0.04 m). The
  camera frustum near/far is now scaled to the model's bounding radius.
- **glTF camera adoption rotated the view** — the orientation conversion ignored
  the view platform's angle negation; fixed for typical view directions.
- **Texture wrap modes ignored** — TextureSettingsTest clamp/mirror failed (all
  REPEAT). Loader now applies the glTF sampler `wrapS/wrapT/minFilter/magFilter`
  (+ mipmaps).
- **Unicode model names** — `Unicode❤♻Test` raised `UnicodeEncodeError` on fetch;
  URLs are now percent-encoded (`safe_url`).
- **Double-sided back-face normals not flipped** — TransmissionTest (and any
  double-sided surface) rendered dark/inside-out from one side; the PBR shader now
  flips the normal on back-facing fragments (`gl_FrontFacing`). (Transmission
  itself is still unimplemented — see §3.)

## Observed gaps (to implement)

### 1. Animation and rigging — **DONE**

All four rows below are implemented and tested (unit + GL render):
[gltf_animation.py](../OpenGLContext/loaders/gltf_animation.py) (interpolation +
`Skin` + `Player`), the loader wiring in [gltf.py](../OpenGLContext/loaders/gltf.py)
(`GLTFScene.animations`/`node_transforms`/`node_morph`/`skins` + `player()`), the
CPU deform on [pbrmesh.py](../OpenGLContext/scenegraph/pbrmesh.py) (morph + LBS via
a dynamic-VBO re-upload keyed on a deform version), and viewer playback in
[gltf_view.py](../OpenGLContext/bin/gltf_view.py) (`OnIdle` drives animation 0;
`k` pause, `[`/`]` switch, `--animation`/`--no-animation`/`--anim-time`). Tests:
`test_gltf_animation.py`, `test_gltf_morph.py`, `test_gltf_skin.py`,
`test_gltf_animation_render.py`.

| Feature | Model(s) | Status |
|---------|----------|--------|
| Keyframe TRS animation (STEP/LINEAR/CUBICSPLINE, slerp) | BoxAnimated, AnimatedCube, InterpolationTest, BrainStem | **DONE** — `Sampler`/`Channel`/`Animation`/`Player`; node TRS written per frame |
| Skinning (`JOINTS_0`/`WEIGHTS_0` + `skins` + `inverseBindMatrices`) | RiggedSimple, RiggedFigure, CesiumMan, BrainStem | **DONE** — CPU linear-blend skin; joint matrices `inverseBind @ jointWorld @ inverse(meshNodeWorld)` (row-vector); ~145 fps CPU ceiling on BrainStem (34k verts) |
| Morph targets (`targets` + node/mesh `weights`) | AnimatedMorphCube, AnimatedMorphSphere, MorphPrimitivesTest | **DONE** — CPU deform `base + Σ wᵢ·targetᵢ` (pos/normal/tangent), morph-then-skin order |
| Recursive/instanced node animation | RecursiveSkeletons | **DONE** — morph/skinned meshes are per-node copies (never cache-shared), so independent weights/joints |

glTF 2.0 has no inverse-kinematics primitive; rigs are forward-kinematic skeletons
whose joint transforms are keyframed (fully supported). OMI extensions remain
handled by `physics/omi_gltf.py` (untouched by this work).

### 2. Geometry / vertex features

| Feature | Model(s) | Current behaviour |
|---------|----------|-------------------|
| Second UV set (`TEXCOORD_1`) | MultiUVTest | Texture prints "Multiple UVs not supported"; only `TEXCOORD_0` is read |
| Computed tangents (when no `TANGENT`) | meshes with a normal map but no tangents | Normal map ignored (falls back to vertex normals) |
| Sparse accessors | SimpleSparseAccessor | Returns zeros (unsupported) |
| Draco mesh compression (`KHR_draco_mesh_compression`) | (various compressed variants) | Fails to decode |
| Primitive modes other than triangles | (line/point primitives) | Only `GL_TRIANGLES` drawn |

### 3. Material / shading correctness

| Feature | Model(s) | Current behaviour |
|---------|----------|-------------------|
| Real image-based lighting | MetalRoughSpheres, reflective assets | **DONE (§3.1).** Dual path behind `OPENGLCONTEXT_IBL`: corrected `analytic` env-BRDF (Karis split-sum) + a `full` IBL probe (irradiance/prefiltered-env cubes + BRDF LUT), fps-adaptive degradation. Also fixed: GGX `alpha=roughness²` (was perceptual), ACES tone map (Reinhard desaturated metals). Env is procedural studio (not the Khronos HDR) so not pixel-exact. Was: analytic sky gradient with Fresnel-only ambient specular (plastic metals) |
| ~~Alpha BLEND transparency~~ | AlphaBlendModeTest, WaterBottle | **DONE.** `Appearance.sortKey` routes `alphaMode=BLEND` to the transparent pass; `shaderRenderTransparent` sorts back-to-front and blends with straight alpha (`GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA`) — the old inverted func was a bug. OPAQUE/MASK stay in the opaque pass. (Per-fragment sort / OIT still future — see [ORDER-INDEPENDENT-TRANSPARENCY.md](ORDER-INDEPENDENT-TRANSPARENCY.md).) |
| Double-sided back-face normals | TwoSidedPlane, doubleSided materials | Cull disabled, but back-face normals aren't flipped, so back faces are mis-lit |
| Texture sampler wrap/filter + mipmaps | TextureSettingsTest, TextureCoordinateTest | Loader ignores glTF sampler `wrapS/wrapT/minFilter/magFilter`; uses LINEAR/REPEAT, no mipmaps |
| `KHR_texture_transform` (per-texture UV transform) | TextureTransformTest, TextureTransformMultiTest | Ignored |
| `KHR_materials_unlit` | UnlitTest, TextureTransformMultiTest | Rendered lit instead of unlit |
| ~~`KHR_materials_transmission` / `_volume` (attenuation)~~ | IridescentDishWithOlives, MosquitoInAmber, DragonAttenuation | **DONE (screen-space).** The opaque scene is captured to a mipmapped backdrop ([passes/transmission.py](../OpenGLContext/passes/transmission.py)); transmissive shapes (drawn after opaque, back-to-front) sample it at the IOR-refracted screen position, roughness → mip (frosted), tinted by baseColor + volume Beer-Lambert. Capability-gated: `full` on a GPU, cheap alpha-blend `blend` on a software rasteriser, `off` — override with `OPENGLCONTEXT_TRANSMISSION`. Not yet: transmission/thickness *textures*, true depth-aware refraction. |
| `KHR_materials_specular` | SpecularTest | Specular factor/color/texture ignored |
| `KHR_materials_pbrSpecularGlossiness` (legacy spec/gloss) | SpecGlossVsMetalRough | **DONE (§3.1).** Was converted *wrongly* — `metallic` forced to 0 and the specular colour dropped, so metals became dull plastic. Fixed: Khronos `solveMetallic` conversion at the factor level **and** per-pixel diffuse+specGloss→baseColor+metallicRoughness texture conversion (the metalness of this model lives in the texture). The two bottles now match. |
| `KHR_materials_iridescence` | IridescenceLamp, IridescenceMetallicSpheres, IridescenceSuzanne | Thin-film iridescence ignored |
| `KHR_materials_clearcoat` | ClearCoatTest, ClearCoatCarPaint, TextureTransformMultiTest | Clearcoat lobe ignored |
| `KHR_materials_sheen` | SheenChair, SheenCloth | Sheen lobe ignored |
| `KHR_materials_emissive_strength` | EmissiveStrengthTest | Emissive not scaled |
| `KHR_texture_transform` (per-texture UV transform) | TextureTransformTest, TextureTransformMultiTest | UV offset/rotation/scale ignored |
| Vertex-color alpha + BLEND interaction | (vertex-colored transparent) | Not validated |

These are the bulk of the remaining reference mismatches found in QA: they are all
**KHR PBR material extensions** (each adds a BRDF lobe or a workflow conversion),
plus transmission (which additionally needs screen-space refraction). They are
substantial, not contained bugs — see the phasing below.

### 4. Lights / scene

| Feature | Model(s) | Current behaviour |
|---------|----------|-------------------|
| `KHR_lights_punctual` (glTF-defined lights) | Lights*, some scenes | Ignored; viewer supplies its own lights |
| glTF camera edge cases (180° / straight-down) | (camera-bearing assets) | `_orientation_from_forward` degenerates |

### 5. Loader robustness

- **Catalog/model URL drift.** Some README-listed models 404 (the repo
  reorganised; e.g. VirtualCity). `load_sample` tries `glTF-Binary` → `glTF` →
  `glTF-Embedded` but should also handle moved paths and surface a clear
  "unavailable in this branch" rather than a bare 404.
- **Large models / streaming.** Big assets (Sponza, city scenes) block the UI
  thread while downloading + decoding; consider background load + a progress line.
- **Color space.** Confirm sRGB decode on base-color/emissive vs linear on
  data textures across all sampler/format combinations (the LA fix closed one
  hole; a systematic audit is wanted).

## Design

### Animation system (§1)

A reusable, scenegraph-level keyframe animation layer:

- Parse `animations[*]`: each `channel` targets a node's `translation`/`rotation`/
  `scale`/morph `weights`; each `sampler` has input (time) + output accessors and
  an interpolation (`STEP`/`LINEAR`/`CUBICSPLINE`).
- A `GLTFAnimation` object holds channels; `update(t)` writes interpolated TRS into
  the target `Transform` nodes (and morph weights into the mesh). The existing
  `OnIdle` turntable already proves per-frame field updates re-render correctly.
- Quaternion channels use spherical interpolation (reuse
  `OpenGLContext.quaternion.slerp`).
- The loader returns the animation list on `GLTFScene`; the viewer plays
  animation 0 (with controls to pause / pick).

### Skinning (§1)

GPU skinning in the PBR vertex shader:

- New attributes: `JOINTS_0` (uvec4, location 5) + `WEIGHTS_0` (vec4, location 6).
- Per-frame joint matrices `jointMatrix[i] = globalTransform(joint) *
  inverseBindMatrices[i]`, uploaded as a uniform array (or a UBO/texture for many
  joints). Skinned position = Σ weightᵢ · jointMatrixᵢ · position; same for the
  normal (with the joint normal matrix).
- Driven by the animation system (joint node transforms animate, skin re-evaluates).
- Cap joint count; fall back to bind pose past the cap.

### Morph targets (§1)

Sum weighted target deltas for position/normal/tangent in the vertex shader
(small target counts) or precompute on the CPU per frame for larger sets. Weights
come from the node/animation.

### Proper metal rendering — real IBL + spec/gloss (§3.1)

The single biggest metal-fidelity gap. Two independent defects compound in
`MetalRoughSpheres` and `SpecGlossVsMetalRough`:

1. **No real environment reflection.** Metals are entirely their reflected
   environment, but the v1 shader reflected a cheap analytic sky gradient with a
   **Fresnel-only** ambient specular (missing the geometry/visibility integral),
   so metals read as plastic and go near-black in shadow. See PBR-MATERIALS.md §9
   for the full design; summary:
   - **Two mechanisms, one switch** (`OPENGLCONTEXT_IBL` = `full` / `analytic` /
     `off` / `auto`), following the `OPENGLCONTEXT_TRANSMISSION` capability pattern.
   - **`analytic`** (also the software-rasteriser / degraded path): keep the
     procedural environment but replace bare Fresnel with Karis's analytic
     `envBRDFApprox` split-sum — correct energy/roughness, no LUT. This is a real
     fix, not just a fallback.
   - **`full`**: a proper probe built once and cached — a procedural *studio*
     environment cube (gradient + soft "softbox" panels), an irradiance cube
     (diffuse), a GGX-prefiltered specular cube (roughness mips), and a BRDF
     integration LUT (`passes/ibl.py`, `shaders/ibl_*`). `pbr.frag` samples them
     in world space via the existing `eyeToWorld` matrix.
   - **Automatic degradation:** the effective mode is fps-adaptive like the shadow
     cascades (`shadowmixin._effectiveCascades`) — `full`→`analytic`→`off` when the
     frame rate sags, re-upgrading after sustained headroom.
   - Reuse the shadow subsystem's seamless-cube / float-format capability detection.

2. **Broken spec/gloss→metal/rough conversion** (`loaders/gltf.py`). The loader set
   `metallic = 0` and **dropped the specular colour entirely** (`spec_rgb` was
   computed then ignored), so a metal authored in `pbrSpecularGlossiness` (the whole
   spec/gloss row of `SpecGlossVsMetalRough`) became a dull `F0 = 0.04` plastic. Fix:
   the standard Khronos conversion — `solveMetallic(diffuse, specular)` to recover
   `metallic`, then blend base colour from the diffuse- and specular-derived colours
   by `metallic²`. Factor-level first (covers the named model); per-pixel
   spec/gloss-*texture* conversion is a follow-up.

### Materials & textures (§3)

- **Samplers/mipmaps:** apply glTF `wrapS/wrapT/minFilter/magFilter`; generate
  mipmaps; this needs the texture layer to accept per-texture sampler state
  (currently `Texture.store` hard-codes LINEAR/REPEAT).
- **Double-sided:** flip the normal for back-facing fragments
  (`gl_FrontFacing ? N : -N`) when the material is double-sided.
- **Alpha BLEND:** route `BLEND` materials through the transparent pass with
  back-to-front sorting (ties into [ORDER-INDEPENDENT-TRANSPARENCY.md](ORDER-INDEPENDENT-TRANSPARENCY.md)).
- **`KHR_texture_transform`:** per-texture UV matrix uniform.
- **`KHR_materials_unlit`:** an unlit branch (emit base color directly).
- **Transmission/clearcoat/sheen/specular/ior/emissive_strength:** add
  incrementally; transmission needs a scene-color copy for refraction.

### Second UV set & tangents (§2)

- Read `TEXCOORD_1`; let each texture reference its `texCoord` index (0/1); pass
  both UVs to the shader.
- Compute per-vertex tangents (MikkTSpace-style) at load when a normal map is
  present but `TANGENT` is absent.

### Lights & loader (§4, §5)

- Import `KHR_lights_punctual` into the existing `PointLight`/`SpotLight`/
  `DirectionalLight` nodes (the loader already has node world transforms).
- Harden `load_sample`: handle repo path drift, optional background download,
  clearer unavailable-model messaging.
- A color-space audit pass over base-color/emissive (sRGB) vs MR/normal/occlusion
  (linear) for every PIL mode / GL format combination.

## Phasing

1. **Texture/material correctness** (highest parity-per-effort): samplers+mipmaps,
   double-sided normals, `KHR_texture_transform`, `KHR_materials_unlit`, alpha
   BLEND, second UV set, computed tangents.
2. **Animation** (keyframe TRS) + **morph targets** — **DONE** (see §1).
3. **Skinning** — **DONE** (see §1). RiggedSimple/Figure, CesiumMan, BrainStem.
4. **Proper metal rendering** (§3.1) — fixed spec/gloss conversion + corrected `analytic`
   ambient specular first (contained, high impact), then the `full` IBL probe and the
   `OPENGLCONTEXT_IBL` switch with fps-adaptive degradation. Broad reflective-material accuracy.
5. **Advanced material extensions** — transmission, clearcoat, sheen, specular, ior.
6. **Robustness** — Draco, sparse accessors, loader path drift, streaming, color-
   space audit.

## Testing

Per CLAUDE.md (pytest, subprocess for GL, reference images):

- **Unit (no GL):** animation channel interpolation (STEP/LINEAR/CUBICSPLINE,
  slerp); skin joint-matrix assembly; morph weight blending; second-UV accessor
  decode; sampler-state mapping; `KHR_texture_transform` matrix; image color-space
  normalisation (incl. L/LA/P modes).
- **GL/integration (subprocess + screenshot):** one named sample model per fixed
  feature, asserting the specific symptom is gone (e.g. AnimatedCube changes
  between two times; RiggedSimple bends under animation; MultiUVTest no longer
  shows the "not supported" texture; AlphaBlendModeTest shows graded transparency;
  UnlitTest is flat). Compare against the README reference where practical.
- Keep the no-IBL analytic-environment path as a tier so tests pass on GPUs/CI
  without the IBL precompute.

## Risks

- **Scope.** This is a large surface; phase 1 (texture/material correctness) gives
  the most parity per unit effort and should land first.
- **Animation re-render cost.** Writing node fields each frame re-runs scene
  traversal; fine for single models, watch for large scenes.
- **Skinning joint limits / UBO sizing** on lower-end GPUs.
- **IBL precompute** is itself sizeable (shared with the PBR plan's phase 2).
- **Extension creep.** The `KHR_materials_*` family is open-ended; implement by
  observed demand from the sample set, not exhaustively.
