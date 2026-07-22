# glTF Full-Feature Conformance

**Status: Feature-Complete (2nd pass)** — a second QA review (29 models vs the
Khronos reference column) drove a batch of new feature work: `KHR_materials_anisotropy`,
`KHR_materials_dispersion`, and `KHR_animation_pointer` are now IMPLEMENTED (were
missing), diffuse-transmission is IBL-driven and spec-conformant, punctual/self-lit
scenes no longer wash out, `KHR_node_visibility` propagates to children, and a
neutral **studio** environment set matches the material references. 93 tests pass.
The spotlight-2×-cone conformance fix and the emissive **bloom** halo have since
landed (see [PBR-BRDF-CONFORMANCE.md](PBR-BRDF-CONFORMANCE.md) and the bloom pass).
Remaining deferred (research-grade): full volumetric **subsurface** for
ScatteringSkull and nested-shell transmission (USDShaderBall). See "Second pass" below.

## Second pass (2026-07-12) — features added

Triggered by a 29-model visual review against the upstream screenshots.

- **KHR_materials_anisotropy** — anisotropic GGX (`D_GGX_anisotropic`/
  `V_GGX_anisotropic` in `_brdf_inc.glsl`), tangent frame from the rotation +
  optional direction texture, and an IBL bent-reflection normal. Loader/UBO/pass
  plumbing (`anisotropyStrength`/`Direction`, `anisotropyMap` unit 21).
  Fixes CompareAnisotropy, AnisotropyStrength/Disc/Rotation, AnisotropyBarnLamp.
- **KHR_materials_dispersion** — per-channel (R/G/B) refraction IOR spread in the
  transmission block → chromatic fringe. Fixes DispersionTest, DragonDispersion,
  CompareDispersion.
- **KHR_animation_pointer** — pointer channels are sampled at the capture time and
  **baked into the glTF JSON** before build (`_bake_pointer_animations`), so node
  visibility / texture-transform / material-factor targets reproduce the posed
  frame. Fixes LightVisibility (now shows only the green light), and drives
  PotOfCoalsAnimationPointer / AnimationPointerUVs.
- **KHR_node_visibility child propagation** — invisibility now ANDs down the node
  recursion (Tier-1 fix), so a subtree under an invisible parent is hidden
  (LightVisibility's red light + its child lights).
- **Diffuse transmission** — dropped the albedo double-tint, de-energized the
  ambient reflection, and added the **−N irradiance back-glow** (Tier-1/2 fixes);
  leaves/panels now back-light under IBL.
- **Transmission energy** — `(1 − specular reflectance)` weighting + IOR-scaled
  blur mip (Tier-1): glass reads less milky, silhouettes go reflective.
- **Punctual / self-lit photometrics** — `background='none'` now forces IBL off
  and zeroes the flat ambient fill (`gltf_scene_ambient`), so DirectionalLight,
  PointLightIntensityTest and EmissiveStrengthTest read as dark scenes with crisp
  coloured lights instead of washed grey.
- **Neutral studio environment** — a generated `studio_*` cubemap (dark grey
  cyclorama + softboxes) selected per-scene via `SceneSpec.environment='studio'`
  for the metal/glass/anisotropy showcases whose references are shot in a studio
  (MetalRoughSpheres etc. keep the outdoor set, matching THEIR reference).
- **Framing / camera** — closer hero framings; VirtualCity uses upright camera 8
  (authored camera 0 has a ~90° roll).

**Since landed:** the emissive bloom halo (bloom pass) and the spotlight-2×-cone
loader fix (the loader no longer doubles the cone half-angles; see
[PBR-BRDF-CONFORMANCE.md](PBR-BRDF-CONFORMANCE.md)).

**Still deferred:** full volumetric subsurface (ScatteringSkull reads as translucent
bone via diffuse-transmission, not full SSS) and nested-shell transmission
(USDShaderBall outer shell). See
[PBR-BRDF-CONFORMANCE.md](PBR-BRDF-CONFORMANCE.md) for the full conformance punch-list.

---

**Status (first pass): Core Complete** — every reported visual issue fixed; 23
Khronos baselines + Parthenon pass, 98 new models render as review candidates.

Goal: render *every* Khronos glTF-Sample-Assets model correctly — full feature
support, not a curated subset. Triggered by expanding the demo roster from 23 to
all 121 GLB-shipping Khronos models (see [gltf_demos.py](../OpenGLContext/loaders/gltf_demos.py)),
which surfaced a batch of rendering gaps in the new models during visual review.

Related: [GLTF-COMPLETE-SUPPORT.md](GLTF-COMPLETE-SUPPORT.md),
[GLTF-DEMO-CONFORMANCE.md](GLTF-DEMO-CONFORMANCE.md),
[PBR-MATERIALS.md](PBR-MATERIALS.md). Baselines + report:
`oglc-gltf-regression` (see [gltf-regression framework]).

## Loader/roster work already landed

- Migrated the sample source from the **deprecated** `glTF-Sample-Models` repo to
  the current **`glTF-Sample-Assets`** repo (old repo 404s for newer models).
- Roster expanded 23 → 121 Khronos models + Parthenon; env-cube background for
  reflective/transmissive materials.
- `EXT_texture_webp` texture-source fallback (Pillow already decodes WebP; the
  loader just wasn't reading the extension's image source) — fixes
  SheenWoodLeatherSofa (was untextured white).

## Issue catalogue (from the 11-model visual review)

| # | Model(s) | Symptom | Root cause | Phase | Status |
|---|----------|---------|------------|-------|--------|
| 1 | VirtualCity | camera outside the world | panoramic dome; auto-frame sits outside — use a baked camera | Framing | **Done** |
| 2 | PotOfCoals | coals not visible | viewed near-level; coals are inside the pot | Framing | **Done** |
| 3 | RecursiveSkeletons | camera trapped inside | huge fractal bounds vs fit margin | Framing | **Done** |
| 4 | PlaysetLightTest | blown white | punctual intensity (cd/lux) passed raw, no falloff, no exposure | P1 Lights | **Done** |
| 5 | PointLightIntensityTest | flat gray, no colours | light positions **double-transformed** + no inverse-square/`range` + sky IBL washout | P1 Lights | **Done** |
| 6 | LightVisibility | no light changes | it is an *animation* (`KHR_animation_pointer` toggling `KHR_node_visibility`) | P4 Anim | **Done** (node_visibility + animation_pointer both landed) |
| 7 | GlassHurricaneCandleHolder | opaque blue | `KHR_materials_volume` thick-wall used max thickness everywhere (ignored thicknessTexture) | P2 Volume | **Done** |
| 8 | USDShaderBallForGltf | opaque black shell | same thick-wall volume path | P2 Volume | **Done** |
| 9 | GlassVaseFlowers | water too strong | same volume path (milder) | P2 Volume | **Done** |
| 10 | RecursiveSkeletons | octagon background + black corners | sky background is a **finite** sphere; huge scene camera pulls back beyond it | P3 Background | **Done** |
| 11 | ScatteringSkull | opaque matte white | `KHR_materials_diffuse_transmission` unimplemented (+ `_volume_scatter`/`_dispersion`) | P5 Subsurface | Partial (diffuse_transmission + dispersion done; full volume-scatter/SSS pending) |
| 12 | SpecularSilkPouf | muddy sheen colour | sheen+specular already applied; subtle authored blue reads acceptably | P6 Sheen | Acceptable |

## Phases

### P1 — Punctual light photometric model  *(mostly done; exposure open)*
glTF `KHR_lights_punctual` intensities are physical: point/spot in **candela**,
directional in **lux**; point/spot use **inverse-square** falloff windowed by an
optional **`range`**. None of the 23 blessed baselines use punctual lights, so
these changes are low-risk to them (verified: baselines still pass).

**Landed:**
- **Root-cause bug — glTF light positions were double-transformed.** `_light_node`
  baked the node's *world* position into `.location`, but the light is mounted
  under that node's Transform, so the render pass applied the world matrix a second
  time. Off-centre lights landed past their targets (PointLightIntensityTest lit
  only the near-origin panel). Fixed: lights now carry **local** coords `(0,0,0)` /
  `-Z` and let the Transform place them → all six panels light correctly.
- Loader: point/spot → `attenuation=(0,0,1)` (inverse-square); carry `range` as
  `_gltf_range`.
- Shader: `lightRange[]` uniform + glTF range-window in `pbr.frag`, gated so VRML
  lights (range 0) are unaffected.
- Self-lit scenes (own `KHR_lights_punctual`) default to `background='none'`
  (black, no sky IBL) so the demo environment isn't layered onto them.
- Tests: `TestPunctualLight` (local coords / inverse-square / range).

**Camera exposure — done.** Added a real camera-exposure stage (`exposure` uniform
in `pbr.frag`, default 1.0 so every other scene stays pixel-identical). A load-time
**light meter** (`_meter_exposure`) reads the strongest illuminance the scene's own
punctual lights deliver near its centre and stops the camera down so absolute-unit
scenes (PlaysetLightTest 512 lux + 1500 cd) don't clip -- exactly what a real
camera does, applied by one general formula, never brightening. Plumbed
scene→context→pass (`GLTFScene.exposure` → `context.gltf_exposure` → `set_exposure`).
Tests: `TestMeterExposure`. PlaysetLightTest now reads as the intended dark scene.

### P2 — KHR_materials_volume thick-wall refraction  *(done)*
Thick-walled transmission looked opaque because the shader used `thicknessFactor`
(the *max* thickness) as the Beer-Lambert path length for **every** fragment, so
thin walls absorbed as if they were the thickest point. Fixed by sampling the
**`thicknessTexture` (.g)** per fragment (`thickness = thicknessFactor * tex.g`) in
both the refraction offset and the attenuation. Plumbed like the other extension
textures (loader `add('thickness', …)`, `PBR_EXT_UNITS['thickness']=20`, shader
`thicknessMap`/`hasThicknessMap`). GlassHurricaneCandleHolder (opaque blue →
translucent blue glass), USDShaderBall (opaque black → green glass), GlassVaseFlowers
(over-tinted → clear glass with visible stems). Transmission baselines still pass.

### P3 — Background at infinity  *(done)*
The camera-locked gradient sphere was near-plane **clipped** when a huge scene
(RecursiveSkeletons) pushed the near plane past the finite sphere's radius, leaving
an octagon with black corners. Fixed with the skybox trick in
`vrml97_background.vert`: `gl_Position = clip.xyww` pins the background to the far
plane so no vertex clips, at any scene scale. Baselines unaffected.

### P4 — Deterministic animation capture + node visibility  *(done)*
- **Deterministic capture:** `SceneSpec.anim_time` pins a model to a fixed
  animation time so the captured pose is reproducible; the regression harness
  passes `--anim-time`. Representative times set on Fox/BrainStem/CesiumMan/… .
- **KHR_node_visibility:** the loader honours the authored initial `visible`
  flag -- an invisible node draws no geometry/light and is excluded from the
  framing bounds.
- **KHR_animation_pointer — done.** Pointer channels (node visibility / texture-transform /
  material-factor targets) are sampled at the capture time and baked into the glTF JSON
  before build (`_bake_pointer_animations`), and the Player drives them live. LightVisibility
  reproduces the posed frame.

### P5 — Diffuse transmission  *(done; dispersion done; full volume-scatter/SSS pending)*
- **KHR_materials_diffuse_transmission** implemented as a back-facing (wrap)
  diffuse lobe -- light entering the far side scatters through to the camera, with
  energy taken from the diffuse reflection. Plumbed as per-material uniforms
  (`diffuseTransmissionFactor`/`Color`, like `transmissionFactor`), so no UBO
  repack. Covers ScatteringSkull, DiffuseTransmission{Plant,Teacup,Test}.
- **KHR_materials_dispersion — done.** Per-channel (R/G/B) refraction IOR spread in the
  transmission block gives the chromatic fringe (DispersionTest, DragonDispersion).
- **Pending — KHR_materials_volume_scatter / full SSS:** true volumetric in-scattering is
  research-grade; the skull reads as translucent bone but not the full sub-surface look.

### P6 — Sheen / specular tint
`KHR_materials_sheen` (Charlie lobe) and `KHR_materials_specular` are already
applied; SpecularSilkPouf's sheen is a subtle authored blue (`[0.025,0.03,0.075]`)
and reads acceptably. Left as a minor tuning item, not a functional gap.

## Verification
Every phase re-renders the affected models **and** the 23 blessed baselines via
`oglc-gltf-regression`; a phase is not done until the baselines still pass and the
target models visibly improve against the Khronos reference column.
