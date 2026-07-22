# High-Quality Shadow Mapping

**Status:** Implemented (all light types + soft shadows + culling). One optional tier (VSM/EVSM)
deferred with a documented reason.

## Implementation status

**Done and GL-tested** — spot (2D), directional (cascaded shadow maps), and point
(omnidirectional cube) lights all cast shadows; PCF baseline + PCSS contact-hardening soft mode;
range-based light/occluder culling. 58 tests pass (math/caps/mixin units + off-screen render
regression for all three light kinds, soft-vs-hard penumbra, and no-shadow regression).

| File | What |
|------|------|
| `passes/shadowmath.py` | row-vector look-at / perspective / **ortho** / near-far fit / **CSM cascade fit** / **cube face views** / eye→light-clip composition (no GL) |
| `passes/shadowcaps.py` | `ShadowCapabilities` extension/version detection + technique selection |
| `passes/shadowmap.py` | `ShadowMap2D` (spot), `ShadowMapArray` (CSM cascades), `ShadowMapCube` (omni) depth FBOs |
| `passes/shadowmixin.py` | `ShadowMapMixin`: per-light-type frusta, depth pre-pass, CSM cascade split/fit, cube 6-face pass, light + occluder culling, uniform binding |
| `shaders/vrml97_lighting.frag` | spot/CSM/cube shadow sampling, 3×3 PCF, PCSS blocker search + variable-radius penumbra, normal-offset bias |
| `passes/shaderpass.py` | shadow uniform/bind methods (spot/CSM/cube), reserved sampler units, PCSS sampler object |
| `passes/_flat.py` | guarded `renderShadowMaps`/`bindShadowUniforms` hooks (no change when off) |
| `passes/flatcore.py` | mixin + `OPENGLCONTEXT_SHADOWS` / `OPENGLCONTEXT_SHADOWS_SOFT` toggles |
| `scenegraph/light.py` | `castShadows`/`shadowBias`/`shadowMapResolution` + `effectiveRange` |
| `scenegraph/shape.py` | `mode.shadow_pass` depth-only bypass |

Per-light-type techniques implemented:
- **Spot** → single perspective 2D depth map (`sampler2DShadow`).
- **Directional** → cascaded shadow maps: camera frustum split (practical scheme), each cascade
  fit to a tight ortho frustum with texel snapping, stored in a `sampler2DArrayShadow`; cascade
  selected per fragment by eye-space depth.
- **Point** → omnidirectional cube depth map (`samplerCubeShadow`), 6 perspective faces, analytic
  projective-depth comparison; seamless cube filtering.
- **Soft** → PCSS: raw-depth blocker search (via a non-comparison sampler object) → penumbra
  estimate → variable-radius PCF (contact hardening). Wider penumbra than PCF, verified.
- **Culling** → lights whose `effectiveRange` sphere misses the camera frustum are skipped;
  occluders outside a light's frustum are dropped from that light's depth pass.

**Key decision (depth pass):** reuses the lit pipeline driven by `mode.matrix`/`mode.projection`
into a depth-only FBO rather than a separate depth program, because several geometry nodes
(`pointset`, `indexedlineset`, `nurbs`, `extrusions`, `teapot`) bind their own program — a single
depth program would be clobbered. Every program writes `gl_Position` from those matrices, so depth
is correct across all geometry types (the lit fragment output is discarded). A minimal depth
program + shadow pancaking remain a future perf optimization.

**Sampler-unit note:** the lit program declares 2D / 2D-array / cube / raw shadow samplers; they
are assigned distinct units at compile time (`init_shadow_samplers`) so they never alias unit 0,
and the lit program links with `validate=False` (link-time validation spuriously flags the
multiple sampler targets before units are assigned). Real assignment precedes every draw.

**Deferred — VSM / EVSM (variance shadow maps):** the one tier not implemented. It requires
rendering depth *moments* (depth, depth²) into a float color target and blurring them, which
conflicts with the depth-pass design above: the lit program reused for the depth pass writes
ordinary depth, not moments, and geometry nodes that bind their own program can't be made to write
moments. Implementing VSM cleanly needs either a dedicated moment program (giving up the
geometry-agnostic depth pass) or a depth→moment post-process + separable blur pass. PCSS already
provides soft, contact-hardening shadows, so VSM is left as a future enhancement. `textureGather`
acceleration is detected and a `shadowGather` uniform is plumbed, but the gather sampling path is
not yet wired (it needs a `#version 400` preamble or the ARB extension; visual result equals PCF).

---

## Goal

Add a high-quality, capability-adaptive shadow-mapping subsystem to the shader render path,
integrated **first** with the existing VRML97 lighting shader so the shadow machinery is proven
against a known-good lighting baseline before the PBR work
([PBR-MATERIALS.md](PBR-MATERIALS.md)) consumes it.

"High quality" means we implement the full modern shadow feature set rather than a minimum
viable map:

- **Per-light-type techniques:** spot → single perspective map; directional → cascaded shadow
  maps (CSM); point → omnidirectional cube-depth maps (no approximation, real omni shadows).
- **Soft, contact-hardening shadows:** hardware PCF baseline, scaling up to PCSS and
  variance/exponential-variance shadow maps (VSM/EVSM) where the GPU supports them.
- **Capability tiers driven by available OpenGL extensions** — detect at context init, pick the
  best technique the driver supports, degrade gracefully.

The subsystem is built as a reusable mixin so both the VRML97 pass and (later) the PBR pass get
shadows from the same code.

## Background: existing architecture this builds on

References verified against the current tree.

- **Render orchestration:** `FlatPass.Render()`
  ([passes/_flat.py:1640](../OpenGLContext/passes/_flat.py#L1640)); the shader path runs
  `setupShaderLights()` → `shaderRenderOpaque()` → `shaderRenderTransparent()` at
  [_flat.py:1726–1744](../OpenGLContext/passes/_flat.py#L1726-L1744). `renderSet()`
  ([_flat.py:1582](../OpenGLContext/passes/_flat.py#L1582)) produces the `toRender` occluder list.
- **Shader management:** `VRML97ShaderProgram` ([passes/shaderpass.py](../OpenGLContext/passes/shaderpass.py))
  compiles GLSL from `OpenGLContext/shaders/`, caches uniform locations per program, exposes
  `set_matrices`, `set_light`, `set_num_lights`, `bind_texture`, `_set_uniform*`. Lit fragment
  shader [shaders/vrml97_lighting.frag](../OpenGLContext/shaders/vrml97_lighting.frag) already
  has the per-light loop (`calcLight`, lines 82–128) where shadow attenuation gets multiplied in.
- **Lights:** [scenegraph/light.py](../OpenGLContext/scenegraph/light.py) — `DirectionalLight`,
  `PointLight`, `SpotLight`. Already provide `viewMatrix(cutOffAngle, aspect, near, far)`
  (perspective from light, [light.py:74](../OpenGLContext/scenegraph/light.py#L74)) and
  `modelMatrix(direction)` (light view, [light.py:93](../OpenGLContext/scenegraph/light.py#L93)).
  Gaps: `DirectionalLight` has no `location`; `PointLight.modelMatrix` requires a `direction`.
- **Matrix helpers:** `pyvrml97/vrml/vrml97/transformmatrix.py` — `perspectiveMatrix`,
  `orthoMatrix`, `transMatrix`, `rotMatrix`. Frustum extraction in
  [frustum.py](../OpenGLContext/frustum.py) (`Frustum.fromViewingMatrix`) for CSM split bounds.
- **FBO patterns to copy:** `SelectionFBO` / `SelectionBufferFBO`
  ([_flat.py:38–350](../OpenGLContext/passes/_flat.py#L38)) show the create / resize /
  completeness-check / cleanup lifecycle for FBOs in this codebase.
- **Extension detection already exists:** `context.extensions` is an `ExtensionManager`
  ([extensionmanager.py](../OpenGLContext/extensionmanager.py)) with `initExtension('GL.ARB.x')`
  and `listGL()`. We query it once to build a capability profile.
- **Prior art (different technique):** the legacy `shadow/` package implements **stencil shadow
  volumes** for fixed-function GL. We do not modify it; its per-light pass loop in
  `shadow/passes.py` is a useful structural reference only.

## Capability tiers

Detected once via `context.extensions` / GL version at first render, cached on the pass as a
`ShadowCapabilities` object. Each higher tier is used only if every extension it needs is present;
otherwise we fall back. All tiers assume the core-profile 3.3 baseline the shader path already
targets.

| Capability | Requirement | Used for | Fallback if absent |
|------------|-------------|----------|--------------------|
| Depth-texture PCF | core 3.3 (`sampler2DShadow`) | baseline soft edge, all light types | — (always present) |
| `textureGather` PCF | `GL_ARB_texture_gather` / GL 4.0 | faster/wider PCF kernels | manual N×N `textureProj` taps |
| 2D array depth | core 3.0 (`sampler2DArrayShadow`) | CSM cascades in one texture | per-cascade separate textures |
| Cube depth | core 3.0 (`samplerCubeShadow`) | point-light omni shadows | 6× 2D maps + manual face select |
| Cube map **arrays** | `GL_ARB_texture_cube_map_array` / GL 4.0 | all point lights' cubes in one sampler | one cube per point light (unit budget) |
| Seamless cube filtering | core 3.2 (`GL_ARB_seamless_cube_map`) | clean cube-face seams | clamp-to-edge per face |
| Layered rendering | geometry shader, core 3.2 (`gl_Layer`) | single-pass CSM / single-pass cube (6 faces, all cascades in one draw) | N draws (per cascade / per face) |
| Depth clamp | core 3.2 (`GL_ARB_depth_clamp`) | occluders crossing the near plane | tightened near plane + bias |
| Anisotropic filtering | `GL_EXT_texture_filter_anisotropic` | VSM/EVSM sharpness at grazing angles | trilinear |
| Float color targets | core 3.3 (`GL_RG32F` / `GL_RGBA32F`) | VSM / EVSM moments | PCSS-only path |

**Quality ladder (selected per light or globally via config):**

0. **Hardware PCF** — `sampler*Shadow` + an N×N kernel (`textureGather`-accelerated when present).
   Always available; the default.
1. **PCSS** (percentage-closer soft shadows) — blocker search → penumbra estimate → variable-width
   PCF. Pure shader; gives contact hardening. Cost-gated, opt-in per light.
2. **VSM / EVSM** — store depth moments in a float color map, blur (separable Gaussian) and
   hardware-filter/mipmap for cheap large penumbrae and MSAA. EVSM (two exponential warps) controls
   light bleeding. Selected when float targets + filtering are available and large soft shadows are
   requested.

## Design

### 1. `ShadowCapabilities` (new, `passes/shadowcaps.py`)

Queries `context.extensions` and `glGetString(GL_VERSION)` once; exposes booleans
(`has_texture_gather`, `has_cube_array`, `has_geometry_layered`, `has_depth_clamp`,
`has_float_color`, `has_aniso`, `max_texture_units`, `max_array_layers`, …) and a chosen
`technique` per light type. Logged at startup so test runs record what path executed.

### 2. Shadow-map FBO wrappers (new, `passes/shadowmap.py`)

Three FBO classes, all following the `SelectionFBO` lifecycle (lazy create, resize,
`glCheckFramebufferStatus`, cleanup):

- **`ShadowMap2D(size)`** — single depth **texture** (`GL_DEPTH_COMPONENT32F`),
  `GL_COMPARE_REF_TO_TEXTURE` + `GL_LEQUAL`, `GL_LINEAR`, `CLAMP_TO_BORDER` border `(1,…)`.
  `glDrawBuffer(GL_NONE)`. Used for spot lights.
- **`ShadowMapCascade(size, cascades)`** — `GL_TEXTURE_2D_ARRAY` depth texture, one layer per
  cascade; attaches a layer (or all layers, for layered single-pass) to the FBO. Used for
  directional lights (CSM).
- **`ShadowMapCube(size)`** — `GL_TEXTURE_CUBE_MAP` depth texture (or a slice of a
  `GL_TEXTURE_CUBE_MAP_ARRAY` when available), 6 faces. Used for point lights. Optional linear
  distance variant for omni.

A VSM/EVSM variant adds a **color** target (`GL_RG32F`/`GL_RGBA32F`) plus a separable-blur helper
(two-pass Gaussian into a ping-pong FBO). Gated on `has_float_color`.

A small `ShadowMapPool` allocates/reuses maps keyed by `(light, technique)` and enforces
`MAX_SHADOW_LIGHTS` and the texture-unit budget from `ShadowCapabilities`.

### 3. Per-light-type matrix generation (`passes/shadowmixin.py`)

For each shadow-casting light, compute the light view/projection(s). Reuse `light.viewMatrix` /
`light.modelMatrix` where they fit, and fill the gaps:

- **SpotLight** — perspective from `cutOffAngle`: `light.viewMatrix(cutOffAngle, aspect=1, near,
  far)` × `light.modelMatrix(direction)`, composed with the path transform. One map. Best fit for
  the existing helpers.
- **DirectionalLight** — **CSM.** Split the camera view frustum into K cascades (practical split:
  blend of logarithmic and uniform). For each cascade, fit a tight `orthoMatrix` around that
  slice's world-space corners (from `Frustum`/the view-projection inverse); orient the light view
  along `direction`. Stabilize against shimmering by snapping the ortho origin to texel
  increments. `light` has no `location`, so position the light view to enclose the cascade.
- **PointLight** — **omnidirectional cube.** Six 90°-FOV perspective views from `location`, one per
  cube face (±X, ±Y, ±Z). Store either compared depth (`samplerCubeShadow`) or linear distance
  (radius) for a distance-based test. `light.modelMatrix` needs a synthesized per-face direction;
  generate the six view matrices directly here rather than via the node helper.

Store per light: the technique, the texture handle(s), and the light-space matrix(es) plus
(for CSM) the cascade split depths, (for cube) the far radius for distance normalization.

### 4. Depth pre-pass (`passes/shadowmixin.py`)

`renderShadowMaps(toRender)`:

1. Select up to `MAX_SHADOW_LIGHTS` casters from `self.paths.get(nodetypes.Light, ())`
   (respect `light.on` and a new per-light `shadows`/`castShadows` flag — see node changes),
   ordered by importance (e.g. intensity × proximity) so the cap drops the least significant.
2. For each light: bind its shadow FBO, set the viewport to the map size, and draw every occluder
   in `toRender` with a minimal **depth-only** program, applying the acne/precision controls
   below (see "Depth-pass precision controls").
   - **Single-pass** when `has_geometry_layered`: a geometry shader replicates primitives to all
     cube faces / all cascades using `gl_Layer`, with per-layer light matrices in a uniform array
     — one draw per light instead of 6 (cube) or K (CSM).
   - **Multi-pass fallback**: loop faces/cascades, binding one FBO layer each.
3. Restore the main framebuffer, viewport, cull/offset/clamp state.

**Geometry reuse without a second geometry path:** the depth shaders declare only
`layout(location = 2) in vec3 aPosition;` — the same attribute location existing VAOs already bind
for position ([shadergeometry.py](../OpenGLContext/scenegraph/shadergeometry.py)). Normals/texcoords
are simply unused, so each geometry node's existing `_render_shader` VAO setup drives the depth
pass unchanged; only the bound program differs. (Alpha-tested/cutout geometry, if added later,
would need texcoords + the base-color texture in the depth shader.)

New depth shaders: `shaders/shadow_depth.vert/.frag` (2D/CSM), `shaders/shadow_cube.vert/.geom/.frag`
(layered cube), `shaders/shadow_cascade.geom` (layered CSM). VSM/EVSM add `shadow_moments.frag`
writing depth moments to the color target.

#### Depth-pass precision controls

Four mechanisms work together to fight shadow acne and depth-precision loss in the depth pass:

- **Front-face culling.** Render back faces into the shadow map (`glCullFace(GL_FRONT)`) so the
  recorded depths sit behind lit front faces, pushing acne into unlit interiors. Toggled off for
  `doubleSided`/open (non-solid) geometry, which has no reliable back face.
- **Depth bias.** Slope-scaled `glPolygonOffset(factor, units)` during the pass plus a
  **normal-offset bias** applied along the surface normal at sample time in `shadowFactor`. Both
  exposed via the per-light `shadowBias` field; tuned per technique (PCF/PCSS/VSM each need
  different ranges).
- **Shadow pancaking.** To maximize depth precision we want the light's **near plane pushed close**
  to the visible occluders, but that would clip occluders lying *between* the near plane and the
  light (which still need to cast). Pancaking keeps them: the depth vertex shader clamps
  pre-near geometry onto the near plane (`gl_Position.z = max(gl_Position.z, -gl_Position.w)`, i.e.
  clamp to NDC `-1`) instead of letting it clip. Combined with **`GL_DEPTH_CLAMP`** (so far-plane
  crossings are clamped, not clipped), this lets us tighten the light frustum — the single biggest
  win for CSM cascade precision — without dropping casters. Disabled where it would corrupt a
  technique that needs true linear depth (e.g. distance-based omni / VSM moments), which instead
  use a tight-but-honest near/far fit.
- **Depth clamp.** `GL_DEPTH_CLAMP` (core 3.2 / `GL_ARB_depth_clamp`) enabled during the pass;
  fallback is a slightly looser near plane plus the pancaking clamp alone.

These are most impactful for **CSM**, where each cascade's tight ortho fit otherwise risks clipping
tall occluders just outside the slice — pancaking + depth clamp keep them casting while preserving
the tight fit that gives cascades their resolution.

#### Light and occluder culling (range-based)

A light only affects geometry within its **effective range**, and only geometry inside the light's
frustum can cast into that light's shadow map. We exploit both to shrink work, reusing infrastructure
that already exists:

- **Effective range.** For point/spot lights the VRML97 attenuation `1/(c + l·d + q·d²)` (scaled by
  `intensity`) lets us solve for the distance `d_max` where contribution falls below a perceptual
  threshold (≈ 1/255). That defines a bounding **sphere** (point) or bounded **cone/sphere** (spot)
  of influence — expose it as a computed `effectiveRange` / influence-volume property on the light
  node so both this pass and the lit pass can use it. **DirectionalLights have no attenuation
  (infinite range)** and are exempt; their extent is bounded by the scene / CSM cascade fit instead.
- **Light culling (skip whole lights).** If a light's influence volume doesn't intersect the
  **camera** view frustum (`self.frustum`, already computed by `calculateFrustum()`
  [_flat.py:1976](../OpenGLContext/passes/_flat.py#L1976)), the light is invisible this frame — skip
  its shadow map *and* free its `MAX_LIGHTS`/`MAX_SHADOW_LIGHTS` slot for a light that matters. This
  directly improves the cap behavior under many lights.
- **Per-light occluder culling (shrink the depth pass).** Build a `Frustum` from the light's
  view-projection via `Frustum.fromViewingMatrix()` ([frustum.py:70](../OpenGLContext/frustum.py#L70))
  and filter `toRender` to occluders whose `bvolume` intersects it — the same test
  `frustumVisibilityFilter()` ([_flat.py:1615](../OpenGLContext/passes/_flat.py#L1615)) already runs
  against the camera frustum, applied per light. The cheap range-sphere test is a pre-filter before
  the full plane test. Each `toRender` tuple already carries a `bvolume`
  ([_flat.py:1591](../OpenGLContext/passes/_flat.py#L1591)) whose `visible(frustum, matrix)`
  ([boundingvolume.py:65](../OpenGLContext/scenegraph/boundingvolume.py#L65)) does the intersection,
  so no new geometry math is needed.

> **Correctness caveat:** caster culling must use the **light** frustum, *not* the camera frustum.
> An occluder outside the camera view but between the light and a visible receiver still casts a
> visible shadow, so it must stay in the depth pass. Only objects outside the *light's* frustum/range
> can be dropped. For CSM, cull per cascade against that cascade's ortho frustum.

For cube (omni) lights, the range sphere is the natural cull volume; per-face culling additionally
tests each of the six 90° frusta. A static-light/static-geometry cache (phase 5) can memoize these
per-light occluder lists until the light or an occluder moves.

> **Beyond the depth pass — deferred.** Per-object *light assignment* in the lit pass (so a fragment
> only loops the lights that actually reach it) is a bigger change: the forward shader currently
> loops all global lights uniformly. Doing it properly means per-object light lists or a
> clustered/forward+ light cull. Worth it for many-light scenes but out of scope here; the
> range/influence property added above is the groundwork for it.

### 5. `Render()` hook refactor (`passes/_flat.py`)

Extract the shader render block ([_flat.py:1726–1744](../OpenGLContext/passes/_flat.py#L1726-L1744))
so subclasses inject work without copy-pasting `Render()`. Add no-op `preLitPasses(toRender)` /
`postLitPasses(toRender)` on `FlatPass`, called around opaque/transparent rendering. The shadow
mixin overrides `preLitPasses` to call `renderShadowMaps`. **This must not change existing VRML97
output** — guard with the visual-regression suite before/after.

### 6. Shadow sampling in the VRML97 shader

`shaders/vrml97_lighting.vert`: output world-space position (and, for CSM, view-space depth for
cascade selection).

`shaders/vrml97_lighting.frag`: add, sized by `ShadowCapabilities` via `#define` injection at
compile time (the program already loads source as files; we prepend a small `#define` preamble):

```glsl
uniform int        shadowCount;
uniform int        shadowLightIndex[MAX_SHADOW_LIGHTS]; // shadow slot -> light index
uniform int        shadowKind[MAX_SHADOW_LIGHTS];       // 0=2D 1=CSM 2=cube
uniform mat4       shadowMatrix[MAX_SHADOW_LIGHTS * MAX_CASCADES];
uniform float      cascadeSplit[MAX_SHADOW_LIGHTS * MAX_CASCADES];
uniform sampler2DShadow      shadowTex2D[MAX_SHADOW_LIGHTS];
uniform sampler2DArrayShadow shadowTexCSM[MAX_SHADOW_LIGHTS];
uniform samplerCubeShadow    shadowTexCube[MAX_SHADOW_LIGHTS];
```

A `shadowFactor(slot, worldPos, N, L)` function:

- selects cascade (CSM) by view depth, or face (cube) by light→fragment vector;
- applies **normal-offset bias** along `N` plus slope-scaled depth bias;
- runs the tier kernel (PCF / `textureGather` PCF / PCSS / VSM resolve);
- returns 0..1.

In `calcLight()` ([vrml97_lighting.frag:82](../OpenGLContext/shaders/vrml97_lighting.frag#L82)),
multiply `diffuse + specular` by the light's `shadowFactor` when that light owns a shadow slot.
The shader compiles to several variants (kernel tier) selected by the preamble; unused sampler
arrays cost nothing.

### 7. `VRML97ShaderProgram` additions (`passes/shaderpass.py`)

- `set_shadow_count(n)`, `bind_shadow_maps(entries)` where each entry carries the technique,
  texture handle, target texture unit, and matrices/splits; binds the right sampler array slot and
  uniform block per light.
- Compile-time preamble injection so kernel size / `textureGather` / cascade count are baked per
  the detected capabilities.

### 8. Pass wiring

- `ShadowMapMixin` mixed into `flatcore.FlatPass` with `use_shadows` (default **off** for the
  VRML97 pass to preserve current visuals/perf; the PBR pass will default it **on**).
- Config surface: `OPENGLCONTEXT_SHADOWS=1`, shadow map resolution, `MAX_SHADOW_LIGHTS`, kernel
  tier override, soft-shadow technique. Document in CLAUDE.md.

### 9. Node changes (`scenegraph/light.py`)

Add optional fields (defaulting to current behavior): `castShadows` (bool, default True when
shadows enabled), `shadowMapResolution`, `shadowBias`. Keep VRML97 round-trip safe (extension
fields, not part of the standard node).

Add a computed **`effectiveRange`** / influence-volume helper on point/spot lights (derived from
`attenuation` + `intensity`, threshold ≈ 1/255), used by the light/occluder culling above and
available as groundwork for later per-object light assignment. Directional lights report unbounded
range.

## File-by-file change summary

| File | Change |
|------|--------|
| `passes/shadowcaps.py` (new) | `ShadowCapabilities` — detect extensions/version, choose techniques |
| `passes/shadowmap.py` (new) | `ShadowMap2D`, `ShadowMapCascade`, `ShadowMapCube`, VSM variant, `ShadowMapPool` |
| `passes/shadowmixin.py` (new) | `ShadowMapMixin`: light-frustum math, `renderShadowMaps`, `preLitPasses` |
| `passes/_flat.py` | Refactor `Render()` to call `preLitPasses`/`postLitPasses` (no behavior change) |
| `passes/flatcore.py` | Mix in `ShadowMapMixin`; add `use_shadows` |
| `passes/shaderpass.py` | Shadow uniform/bind methods + compile-time preamble injection |
| `shaders/shadow_depth.vert/.frag` (new) | Depth-only program (position at location 2) |
| `shaders/shadow_cube.{vert,geom,frag}` (new) | Layered omnidirectional cube depth |
| `shaders/shadow_cascade.geom` (new) | Layered CSM |
| `shaders/shadow_moments.frag` (new) | VSM/EVSM moment write (optional tier) |
| `shaders/vrml97_lighting.vert/.frag` | World-space output + `shadowFactor` sampling |
| `scenegraph/light.py` | `castShadows`, `shadowMapResolution`, `shadowBias` fields |
| `tests/` | Unit + GL shadow tests (below) |

## Implementation phases

1. **Spot-light 2D shadows, PCF baseline** — `ShadowCapabilities`, `ShadowMap2D`, depth pre-pass,
   `Render()` hook refactor, VRML97 shader sampling, bias tuning. Smallest correct end-to-end path;
   establishes the reference image.
2. **Directional CSM** — cascade splitting/fitting, `ShadowMapCascade`, array-shadow sampling,
   stabilization. Layered single-pass when available, multi-pass fallback.
3. **Point-light omni cube shadows** — `ShadowMapCube`, six-view generation, cube sampling,
   seamless filtering, cube-array packing when available. (Explicitly in scope — no approximation.)
4. **Soft-shadow tiers** — `textureGather` PCF, then PCSS, then VSM/EVSM with blur, each gated by
   `ShadowCapabilities`.
5. **Polish** — per-light `castShadows`, range-based light/occluder culling (effective-range volume
   + per-light frustum filter of `toRender`), importance ordering under the cap, static-map caching
   for non-moving lights/geometry, config + docs.

PBR integration is **not** in this plan: once the mixin and shader `shadowFactor` exist, the PBR
shader reuses them ([PBR-MATERIALS.md](PBR-MATERIALS.md)).

## Testing

Per CLAUDE.md (pytest, subprocess for GL, 80–100% coverage, reference images):

- **Unit (no GL):** cascade-split math; per-light-type matrix generation (spot/dir/point) for known
  inputs; capability-tier selection given mocked extension sets; importance ordering / cap logic.
- **GL/integration (subprocess + auto-exit + screenshot):**
  - `tests/shadow_spot.py` — plane + occluder under a spot light; assert a dark, correctly-placed
    penumbra vs. a committed reference.
  - `tests/shadow_directional_csm.py` — large ground plane with objects at varying depth; verify
    cascade coverage and no visible seams.
  - `tests/shadow_point_omni.py` — object surrounded by geometry under a central point light;
    verify shadows in all directions (the omni correctness test).
  - `tests/shadow_soft.py` — contact-hardening check (penumbra widens with blocker distance) when
    PCSS/VSM tiers are active; skip-marked when the tier is unavailable.
  - Regression: existing VRML97 scenes render unchanged with `use_shadows=False`.
- Capture via `OPENGLCONTEXT_AUTO_EXIT_FRAMES` / capture-dir env vars; references under
  `tests/reference_images/`. Because the active tier varies by GPU, soft-shadow references are
  tier-tagged and those tests skip when the tier isn't selected.

## Risks and open questions

- **Tier variance across GPUs/CI.** The container/CI GPU may lack 4.0-era extensions, so
  `textureGather`/cube-array/VSM paths might not run there. Keep tier-0 PCF fully correct and make
  it the reference-image baseline; tier-specific tests skip when not selected.
- **Cube shadow cost.** Six views per point light per frame is expensive; the layered single-pass
  path mitigates draw-call overhead but not fill. Cap point shadow casters, cache for static
  lights, and allow lower cube resolution.
- **CSM shimmering.** Needs texel-snapping and stable cascade fitting; budget tuning time.
- **Bias tuning.** Acne vs. peter-panning across all three light types and the PCSS/VSM tiers —
  expose `shadowBias` and normal-offset scale; light-bleed reduction for VSM (EVSM/min-variance
  clamp).
- **Texture-unit budget.** Cube + CSM + 2D sampler arrays consume units; combined with PBR maps
  later this tightens. `ShadowCapabilities.max_texture_units` drives `MAX_SHADOW_LIGHTS`; cube-map
  arrays collapse many point lights into one unit when available.
- **Shader variant explosion.** Kernel tier × light kinds compiled via preamble `#define`s — keep
  the variant matrix small and logged.
- **Core profile only.** Shader-path feature; the `flatcompat` fixed-function pass is out of scope
  (it keeps the legacy stencil `shadow/` volumes).
