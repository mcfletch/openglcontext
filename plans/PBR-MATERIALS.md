# PBR Materials and glTF Loading

**Status:** Implemented (metallic/roughness PBR pass, glTF/GLB loader, sample-model viewer).
IBL ambient deferred (phase 2); tangent generation for *native* geometry deferred.
**Depends on:** [SHADOW-MAPPING.md](SHADOW-MAPPING.md) (consumes its shadow subsystem)

## Implementation status

**Done and tested** — a `PBRPass` renders a Cook-Torrance metallic/roughness BRDF; glTF/GLB
assets load from file or URL into the scenegraph and render with their textures; an interactive
viewer pages through the Khronos sample models. 16 PBR tests pass (unit + GL + network-gated),
and the shadow suite + existing VRML97 scenes still pass.

| File | What |
|------|------|
| `scenegraph/pbrmaterial.py` | `PBRMaterial` node (glTF-aligned) + `PBRTexture` holder + `material_to_pbr` up-conversion |
| `scenegraph/pbrmesh.py` | `PBRMesh` — indexed triangle geometry with position/normal/texcoord/tangent, renders in visible + shadow passes |
| `shaders/pbr.vert` / `pbr.frag` | Cook-Torrance (GGX/Smith/Schlick), base-color/MR/normal/occlusion/emissive maps, sRGB handling, tone-map, MRT id, full shadow sampling |
| `passes/pbrpass.py` | `PBRShaderProgram` (subclasses `VRML97ShaderProgram`) + `PBRPass` + `configure_appearance` (PBRMaterial direct, VRML97 up-converted) |
| `scenegraph/shape.py` | `_render_shader` delegates to `configure_appearance` when the program provides it (VRML97 path untouched) |
| `passes/renderpass.py` | Pass selection: `OPENGLCONTEXT_RENDERER=pbr` |
| `loaders/gltf.py` | glTF 2.0 / GLB loader: accessor decode, materials, embedded/data-URI/external textures, node TRS/matrix hierarchy, bounds for framing, URL fetch+cache, Khronos sample catalog |
| `tests/pbr_gltf_demo.py` | Sample-model viewer (n/p/PageUp/PageDown/arrows to page; turntable) |
| `pyproject.toml` | `gltf` extra (`pygltflib`) |

Verified renders: VRML97 spheres/box up-converted under PBR; glTF Duck (base-color texture),
DamagedHelmet (base-color + metallic-roughness + normal + **emissive** maps), BarramundiFish;
catalogue navigation (advance loads a different model); PBR + spot-light shadows together.

**Coexistence** works as designed: both `PBRMaterial` and VRML97 `Material` render through the one
PBR program (the latter up-converted: diffuse→baseColor, shininess→roughness, metallic 0).

**Texture-unit allocation:** PBR maps occupy units 20–24 (above the shadow units 4–19; material
unit 0 stays free for the VRML97 path). The PBR program links with `validate=False` and assigns
all sampler units before drawing (same reason as the shadow shader).

**Deferred / not done:**
- ~~**IBL ambient** (phase 2)~~ **IN PROGRESS — proper metal rendering (§9).** Metals were
  reflecting a cheap analytic sky gradient with a Fresnel-only ambient specular, so they read as
  plastic and diverged from the Khronos references (`MetalRoughSpheres`, `SpecGlossVsMetalRough`).
  The fix is a dual-mechanism environment path — a full IBL probe (irradiance + prefiltered-env
  cubes + BRDF LUT, split-sum) and a corrected `analytic` path (Karis env-BRDF, no LUT) — behind
  one `OPENGLCONTEXT_IBL` switch with fps-adaptive degradation. See §9.
- **Tangent generation for native geometry** — glTF-supplied `TANGENT` attributes drive normal
  mapping (verified on DamagedHelmet); meshes that lack tangents fall back to vertex normals
  (no normal map). Computing tangents from UVs for native `IndexedFaceSet`/glTF-without-tangents
  is a refinement.
- **glTF skinning/animation, morph targets, sparse accessors, draco, `KHR_lights_punctual`** —
  out of the v1 static-mesh scope.

---

## Goal

Add physically-based rendering (PBR) to the shader render path:

1. A new **`PBRPass`** (subclass of `flatcore.FlatPass`) that renders with a
   **metallic/roughness Cook-Torrance shader** instead of VRML97 Phong, with shadows **on by
   default** (reusing the subsystem from [SHADOW-MAPPING.md](SHADOW-MAPPING.md)).
2. A new **`PBRMaterial`** scenegraph node (glTF-aligned metallic/roughness model) with optional
   texture maps: base color, metallic-roughness, normal, occlusion, emissive.
3. **Coexistence** with VRML97 `Material` so existing scenes render under the PBR pass.
4. A **glTF / GLB loader** that imports meshes, materials, and textures into the scenegraph as
   `PBRMaterial`-backed shapes — the primary way real PBR assets enter the system.
5. **Image-based lighting (IBL)** for realistic ambient (phased).

## Background: existing architecture this builds on

References verified against the current tree.

- **Pass selection:** `_defaultRenderPasses.__call__()`
  ([passes/renderpass.py:851](../OpenGLContext/passes/renderpass.py#L851)) chooses a pass from the
  context profile. `flatcore.FlatPass` sets `use_shaders = True`
  ([passes/flatcore.py:52](../OpenGLContext/passes/flatcore.py#L52)).
- **Shader management / material plumbing:** `VRML97ShaderProgram`
  ([passes/shaderpass.py](../OpenGLContext/passes/shaderpass.py)); `configure_material_from_node()`
  ([shaderpass.py:742](../OpenGLContext/passes/shaderpass.py#L742)) and `set_material()` map a
  `Material` node to uniforms. `getShaderProgram()`
  ([_flat.py:744](../OpenGLContext/passes/_flat.py#L744)) is the override point for substituting a
  program.
- **Per-shape material/texture setup:** `Shape._render_shader()`
  ([scenegraph/shape.py:84](../OpenGLContext/scenegraph/shape.py#L84)) calls
  `configure_material_from_node()` and binds a single diffuse texture via `bind_texture()`.
- **Material node:** [scenegraph/material.py](../OpenGLContext/scenegraph/material.py) subclasses
  `vrml.vrml97.basenodes.Material`. `Appearance.material` / `Appearance.texture` are `SFNode`
  slots ([scenegraph/appearance.py](../OpenGLContext/scenegraph/appearance.py)).
- **Geometry / attribute locations:** fixed `0`=texcoord, `1`=normal, `2`=position
  ([scenegraph/shadergeometry.py](../OpenGLContext/scenegraph/shadergeometry.py),
  `vrml97_lighting.vert`). Geometry VBOs currently carry position/normal/texcoord only — **no
  tangents** (needed for normal mapping; see Tangents below).
- **Texture infra:** `Texture` ([texture.py](../OpenGLContext/texture.py)),
  `ImageTexture.cached()` ([scenegraph/imagetexture.py](../OpenGLContext/scenegraph/imagetexture.py)),
  multi-unit binding already supported via the `texture_unit` arg on `bind_texture`.
- **Loaders:** [loaders/](../OpenGLContext/loaders/) has `base.py`, `loader.py`, `obj.py`,
  `vrml97.py` — the registration/strategy pattern a glTF loader plugs into. No glTF support exists.
- **Extension/capability detection:** `context.extensions`
  ([extensionmanager.py](../OpenGLContext/extensionmanager.py)) — reused for IBL/format
  capability checks (e.g. seamless cube maps, float textures).

## Design

### 1. `PBRMaterial` node (`scenegraph/pbrmaterial.py`)

Metallic/roughness model, glTF 2.0-aligned, modeled on
[scenegraph/material.py](../OpenGLContext/scenegraph/material.py):

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `baseColor` | SFColor (+ alpha via `transparency`) | (1,1,1) | linear; glTF `baseColorFactor` |
| `baseColorTexture` | SFNode | NULL | sRGB sampled, glTF base color |
| `metallic` | SFFloat | 1.0 | glTF `metallicFactor` |
| `roughness` | SFFloat | 1.0 | glTF `roughnessFactor` |
| `metallicRoughnessTexture` | SFNode | NULL | glTF packing: G=roughness, B=metallic |
| `normalTexture` | SFNode | NULL | tangent-space; needs tangents |
| `normalScale` | SFFloat | 1.0 | |
| `occlusionTexture` | SFNode | NULL | R channel; ambient occlusion |
| `occlusionStrength` | SFFloat | 1.0 | |
| `emissiveColor` | SFColor | (0,0,0) | glTF `emissiveFactor` |
| `emissiveTexture` | SFNode | NULL | sRGB |
| `transparency` | SFFloat | 0.0 | drives existing transparent sort/blend |
| `alphaMode` | SFString | "OPAQUE" | OPAQUE / MASK / BLEND (glTF) |
| `alphaCutoff` | SFFloat | 0.5 | for MASK |
| `doubleSided` | SFBool | False | cull toggle |

Because `Appearance.material` is an `SFNode`, a `PBRMaterial` drops into the existing slot with **no
`Appearance` change**. Per-channel texture transforms reuse `Appearance.textureTransform`
initially; glTF's `KHR_texture_transform` per-texture transform is a later refinement.

### 2. PBR shader (`shaders/pbr.vert` / `shaders/pbr.frag`)

- Same fixed attribute locations (`0`=texcoord, `1`=normal, `2`=position) so existing geometry VAO
  setup is unchanged; **tangent at `location = 3`** only when normal mapping is active.
- **Cook-Torrance BRDF:** GGX/Trowbridge-Reitz NDF, Smith height-correlated geometry term, Schlick
  Fresnel; `F0 = mix(0.04, baseColor, metallic)`, diffuse `= baseColor * (1 - metallic)`.
- Per-light loop mirrors the VRML97 structure (directional/point/spot, attenuation, spot cone) so
  light setup (`configure_light_from_node`, `set_num_lights`) is shared, **multiplied by the
  light's `shadowFactor`** from [SHADOW-MAPPING.md](SHADOW-MAPPING.md).
- Texture sampling with `has*Texture` flags; sRGB→linear on base-color/emissive; normal-map
  perturbation via TBN when tangents present.
- Ambient: phase 1 = constant ambient × occlusion; phase 2 = IBL (below).
- Preserves MRT object-ID output (attachment 1) for picking parity with the VRML97 shader.

### 3. `PBRShaderProgram` (`passes/shaderpass.py` or `passes/pbrpass.py`)

Subclass `VRML97ShaderProgram` to inherit the location cache, matrix setup, light setup, texture
binding, and the shadow uniform/bind methods. Override the shader filenames and add:

- `set_pbr_material(base_color, metallic, roughness, emissive, occlusion_strength, alpha_*, …)`
- `bind_pbr_textures(...)` — up to 5 maps across texture units, with `has*Texture` flags, leaving
  units reserved for shadow maps per `ShadowCapabilities`.
- `configure_pbr_material_from_node()` paralleling `configure_material_from_node()`.

### 4. `PBRPass` (`passes/pbrpass.py`)

`class PBRPass(flatcore.FlatPass)`:

- `getShaderProgram()` returns the cached `PBRShaderProgram`.
- `use_shadows = True` by default (mixin already present on `flatcore.FlatPass` from the shadow
  plan).
- Inherits the unchanged render flow; only the bound program and material configuration differ.

### 5. Per-shape material dispatch (`scenegraph/shape.py`)

`Shape._render_shader()` currently calls `configure_material_from_node()` unconditionally. Branch
on node type: `PBRMaterial` → PBR configuration + `bind_pbr_textures`; VRML97 `Material` → existing
path **or** up-conversion (below) depending on the active program.

### 6. Coexistence of VRML97 and PBR materials

- **Within `PBRPass`** (recommended default): one PBR program is bound for the whole opaque batch.
  `PBRMaterial` renders directly; a VRML97 `Material` is **up-converted** to PBR inputs —
  `baseColor = diffuseColor`, `metallic = 0`, `roughness ≈ 1 - shininess` (clamped),
  `emissive = emissiveColor`, specular folded into the dielectric F0. So **existing scenes render
  unchanged under the PBR pass** with no per-shape program switching.
- **Within the VRML97 pass:** a `PBRMaterial` is down-converted to `Material` defaults (baseColor→
  diffuse, emissive→emissive), so either pass can draw either material kind.
- **True simultaneous distinct lighting models** (Phong pixels and PBR pixels in one frame) would
  require per-shape program switches with matrix/light/shadow re-binds — supported in principle but
  **deferred**; not needed once up-conversion preserves legacy scenes.

**Answer to "can both coexist?":** yes, via up-conversion through a single program. Mixed *distinct*
models per frame is a later option.

### 7. Tangents for normal mapping (`scenegraph/` geometry)

Normal maps need per-vertex tangents, which current VBOs lack. Add tangent generation:

- For glTF imports: use the asset's supplied `TANGENT` attribute when present; otherwise compute
  from positions/UVs (MikkTSpace-style) at load time.
- For existing geometry nodes (`indexedfaceset`, `arraygeometry`): add an optional tangent VBO at
  `location = 3`, computed lazily when a `PBRMaterial.normalTexture` is in use. Without it, the PBR
  shader falls back to vertex normals (no normal mapping) — so phases before this still work.

### 8. glTF / GLB loader (`loaders/gltf.py`)

Register a glTF strategy alongside `obj.py` / `vrml97.py` via the existing loader pattern
([loaders/loader.py](../OpenGLContext/loaders/loader.py)).

- **Parsing dependency:** `pygltflib` (pure-Python, handles `.gltf` + binary `.glb` + buffer/URI
  decoding). **Not currently installed** — add as an optional dependency (extras group, e.g.
  `pip install openglcontext[gltf]`); the loader imports lazily and errors clearly if missing.
  numpy is already available for buffer views.
- **Mapping glTF → scenegraph:**
  - `scene`/`node` hierarchy → `Transform` groups (TRS → translation/rotation/scale fields);
    quaternion rotation maps to the existing quaternion/XYZR machinery.
  - `mesh.primitive` → a geometry node from `POSITION`/`NORMAL`/`TEXCOORD_0`/`TANGENT` accessors
    + indices (build VBOs at fixed attribute locations; triangles only in v1).
  - `material` → `PBRMaterial` (`pbrMetallicRoughness` factors/textures, `normalTexture`,
    `occlusionTexture`, `emissive*`, `alphaMode`/`alphaCutoff`, `doubleSided`).
  - `texture`/`image`/`sampler` → `ImageTexture` with wrap/filter from the sampler; respect sRGB
    vs. linear per channel.
- **Scope v1:** static meshes + metallic/roughness materials + textures. **Deferred:** skinning/
  animation, morph targets, sparse accessors, `KHR_materials_*` extensions beyond core, draco
  compression, cameras/lights-from-glTF (`KHR_lights_punctual` is a good early add since the light
  nodes already exist).
- **Tests:** load a known small glTF sample (e.g. a metallic/roughness sphere, a normal-mapped
  asset), assert node/material/texture counts and that it renders (screenshot vs. reference).

### 9. Proper metal rendering — environment reflection (IBL) — phase 2

**Status: implemented.** `passes/ibl.py` + `shaders/ibl_*.{vert,frag}` build the probe
(procedural studio env cube → irradiance cube, GGX-prefiltered specular cube, BRDF LUT);
`pbr.frag` samples them (world-space via `eyeToWorld`) with the split-sum, or the analytic
`envBRDFApprox` path, or flat ambient, chosen by `OPENGLCONTEXT_IBL` (`full`/`analytic`/`off`/
`auto`) with `IBLController` fps-adaptive degradation (`full`→`analytic` only — never `off`).
Alongside, three correctness fixes that were essential to metals reading as metal rather than
plastic:
- **GGX alpha = roughness²** — `pbr.frag` fed *perceptual* roughness straight into the GGX NDF /
  Smith geometry terms; glTF 2.0 requires `alpha = roughness²` (perceptual roughness kept only for
  env-map LOD / BRDF-LUT lookup). Wrong lobe width otherwise.
- **ACES filmic tone map** replaces Reinhard, which desaturated saturated metals (gold → muddy
  olive) toward grey. No exposure lift (lifting blows dielectric colours out to white).
- **spec/gloss conversion** (loader): `solveMetallic` at the factor level *and* a per-pixel
  diffuse+specularGlossiness→baseColor+metallicRoughness texture conversion (the metalness of
  texture-driven assets like SpecGlossVsMetalRough lives in the image, not the factors).
- Env is **moderate brightness, high contrast** (bright upper hemisphere + dark floor + HDR soft
  panels): what reads as metal is highlight-vs-surround contrast, not overall brightness — an
  over-bright env washes every colour toward white. Won't pixel-match the Khronos references
  (those use a specific captured HDR); loading an external equirect/`Background` env is the
  follow-up for closer matching.
- Fixed a latent crash: `material_to_pbr` blindly read `.diffuseColor`, so a VRML97 Shape with
  **no material** (a `NullNode`) crashed under the PBR pass; it now up-converts to the default grey.


**Motivation.** A metal has *no* diffuse term: its entire appearance is the reflected
environment, shaped by roughness. The v1 pass stood in a cheap analytic sky/ground gradient
(`envColor` in `pbr.frag`) with a Fresnel-only ambient specular. That reads as *plastic*, not
metal, and diverges sharply from the Khronos reference renders (`MetalRoughSpheres`,
`SpecGlossVsMetalRough`): metal/rough spheres go flat, and metals in shadow go near-black
because there is nothing for them to reflect. Correct metal needs a real environment probe and
the **split-sum** approximation.

**Two mechanisms, one runtime switch (with automatic degradation).** Mirroring the
`OPENGLCONTEXT_TRANSMISSION` capability pattern (`passes/transmission.py`), a resolver
`passes/ibl.resolve_ibl_mode(renderer)` picks the ambient path, overridable by
`OPENGLCONTEXT_IBL` (`full` / `analytic` / `off` / `auto`):

| Mode | Ambient diffuse | Ambient specular | Cost |
|------|-----------------|------------------|------|
| `full` | irradiance cube | prefiltered-env cube × BRDF-LUT split-sum | one-time precompute (cubes+LUT); 3 texture samples/fragment |
| `analytic` | `envColor(N)` gradient | `envColor(R)` × **analytic** env-BRDF (Karis `envBRDFApprox`, no LUT) | ALU only |
| `off` | flat `sceneAmbient × albedo` | none | negligible |

- **`auto` (default):** `full` on a hardware GPU; `analytic` on a software rasteriser
  (llvmpipe/softpipe/swrast — the GGX prefilter/importance-sample loops are too slow there).
- **Automatic degradation:** the effective mode is fps-adaptive, exactly like the shadow
  cascades' `_effectiveCascades` (`shadowmixin.py`): if the recent median fps sags below a
  threshold while in `full`, drop to `analytic` (then `off`) with a cooldown; re-upgrade after
  sustained headroom. The *sampling* delta is small (3 cube/LUT lookups); the real lever this
  guards is the one-time precompute on weak GPUs and any future per-frame env rebuild.

**Analytic path is a first-class fix, not just a fallback.** Even without a probe, the ambient
specular was wrong: it used bare Fresnel, omitting the geometry/visibility integral. Replacing
it with Karis's analytic `envBRDFApprox(NdotV, roughness) → (scale, bias)` and forming
`ambSpecular = env · (F0·scale + bias)` gives correct energy and roughness response with no LUT.
This alone makes metals read as metal in the `analytic` mode and on software rasterisers.

**Full IBL pipeline (`passes/ibl.py` + `shaders/ibl_*.{vert,frag}`).** Built once and cached on
the program (the environment is static), analogous to how the shadow FBOs persist:

1. **Environment cube** (RGB16F, ~128²) — rendered from a **procedural studio environment**
   (sky/ground gradient plus a few bright soft "softbox" panels so metals catch studio-like
   highlights, closer to the neutral reference env than a plain gradient). Self-contained: no
   external HDR asset required. An equirectangular-HDR / `Background`-cube source is an optional
   later input; the procedural env is the always-available default.
2. **Irradiance cube** (RGB16F, ~32²) — cosine-weighted hemisphere convolution of the env cube
   (`ibl_irradiance.frag`) → diffuse ambient.
3. **Prefiltered specular cube** (RGB16F, ~128² base, ~5 mips) — GGX importance-sampled prefilter
   per mip, `roughness = mip / (mipCount−1)` (`ibl_prefilter.frag`).
4. **BRDF integration LUT** (RG16F, ~256², env-independent, computed once) — the split-sum
   `(scale, bias)` table (`ibl_brdf.frag`, fullscreen).

**Shader sampling (`pbr.frag`).** New uniforms `samplerCube irradianceMap, prefilterMap;
sampler2D brdfLUT; int iblMode; float prefilterMaxLod`. The IBL cubes are **world-oriented**, so
sample with the world-space normal/reflection using the already-present `eyeToWorld` matrix
(added for shadows). Full path:

```glsl
vec3 Nw = mat3(eyeToWorld) * N;
vec3 Rw = mat3(eyeToWorld) * reflect(-V, N);
vec3 irr = texture(irradianceMap, Nw).rgb;
vec3 pre = textureLod(prefilterMap, Rw, roughness * prefilterMaxLod).rgb;
vec2 ab  = texture(brdfLUT, vec2(NdotV, roughness)).rg;
ambDiffuse  = irr * albedo * (1.0 - metallic) * ao;
ambSpecular = pre * (F0 * ab.x + ab.y) * ao;
```

**Texture units.** irradiance = 26, prefilter = 27, brdfLUT = 28 (above 0–3 free, 4–19 shadows,
20–24 PBR maps, 25 transmission — well within the driver limit). Set once at compile like the
other samplers; the cubes/LUT are bound per frame in the opaque-pass setup
(`_flat.py` after `setupShaderLights`, guarded to the PBR program).

**Clearcoat** also reflects the environment: its second lobe samples the prefiltered cube at the
clearcoat roughness (currently the analytic gradient), so clearcoat parity comes along for free.

## File-by-file change summary

| File | Change |
|------|--------|
| `scenegraph/pbrmaterial.py` (new) | `PBRMaterial` node |
| `scenegraph/shape.py` | Material dispatch: `PBRMaterial` vs `Material`; up/down-conversion |
| `scenegraph/indexedfaceset.py`, `arraygeometry.py` | Optional tangent VBO (location 3) for normal maps |
| `shaders/pbr.vert/.frag` (new) | Cook-Torrance metallic/roughness + shadow sampling + MRT id |
| `passes/shaderpass.py` | `PBRShaderProgram`, `configure_pbr_material_from_node`, PBR texture binding |
| `passes/pbrpass.py` (new) | `PBRPass(flatcore.FlatPass)` |
| `passes/renderpass.py` | Pass selection for `OPENGLCONTEXT_RENDERER=pbr` |
| `loaders/gltf.py` (new) | glTF/GLB import → scenegraph + `PBRMaterial` |
| `loaders/__init__.py`, `loader.py` | Register glTF strategy |
| `setup.py`/`pyproject` | `gltf` optional-dependency extra (`pygltflib`) |
| `tests/` | PBR + glTF tests (below) |

## Implementation phases

1. **PBR shader + program + pass** — `pbr.vert/.frag` (no textures, no shadows), `PBRShaderProgram`,
   `PBRPass`, VRML97→PBR up-conversion. Render existing demo scenes under PBR.
2. **`PBRMaterial` node + texture maps** — node, `Shape` dispatch, base-color/metallic-roughness/
   occlusion/emissive maps (normal maps gated on tangents).
3. **Shadows on** — flip `PBRPass.use_shadows=True`, reuse `shadowFactor` (depends on
   [SHADOW-MAPPING.md](SHADOW-MAPPING.md) being landed).
4. **Tangents + normal mapping** — glTF tangents + computed tangents for native geometry.
5. **glTF loader** — static meshes/materials/textures; `KHR_lights_punctual` as an early add.
6. **Proper metal rendering** (phase 2, §9) — (a) corrected `analytic` ambient specular (Karis
   env-BRDF split-sum) + fixed spec/gloss→metal/rough conversion; (b) `full` IBL probe
   (irradiance + prefiltered-env cubes + BRDF LUT); (c) `OPENGLCONTEXT_IBL` mode switch with
   capability resolution + fps-adaptive degradation.

## Testing

Per CLAUDE.md (pytest, subprocess for GL, 80–100% coverage, reference images):

- **Unit (no GL):** `PBRMaterial` field defaults; VRML97↔PBR conversion math; glTF accessor →
  numpy buffer decoding; glTF material → `PBRMaterial` mapping; pass-selection logic.
- **GL/integration (subprocess + auto-exit + screenshot):**
  - `tests/pbr_spheres.py` — metallic×roughness grid under directional + point lights (canonical
    PBR sanity scene).
  - `tests/pbr_textured.py` — base-color + metallic-roughness (+ normal map once tangents land).
  - `tests/pbr_gltf_load.py` — import a small glTF sample, assert structure, render vs. reference.
  - `tests/pbr_with_shadows.py` — PBR + shadows together.
  - Regression: VRML97 scenes render acceptably under `PBRPass` via up-conversion.
- Capture via `OPENGLCONTEXT_AUTO_EXIT_FRAMES` / capture-dir env vars; references under
  `tests/reference_images/`.

## Risks and open questions

- **Dependency footprint.** `pygltflib` is a new optional dependency; keep it lazy/optional so the
  base install is unaffected.
- **Tangent generation correctness.** Mismatched tangent conventions cause wrong normal-mapped
  lighting; prefer asset-supplied tangents, validate computed ones against a known normal-mapped
  sample.
- **Texture-unit budget.** Up to 5 PBR maps + shadow maps approaches common 16-unit limits; share
  the unit map with `ShadowCapabilities` and document the allocation.
- **Color space.** Must sample base-color/emissive as sRGB and lighting math in linear, with a
  final encode; getting this wrong makes PBR look flat/oversaturated.
- **Up-conversion fidelity.** `shininess → roughness` is approximate; legacy scenes will look
  *different*, not identical, under PBR. Document the intent (plausible, not pixel-matched).
- **IBL scope.** Full IBL (precompute pipeline) is sizeable; keep it phase 2 and behind a config
  flag.
- **Core profile only.** Shader-path feature; `flatcompat` is out of scope.
```
