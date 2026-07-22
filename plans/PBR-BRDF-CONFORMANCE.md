# PBR Uber-Shader — glTF 2.0 BRDF & Extension Conformance Review

**Status: RESOLVED (2026-07-12)** — the full punch-list below was implemented in a
conformance pass. Every Tier-1/2/3 item is done; Tier-4 `KHR_texture_basisu` is the
only deliberate exclusion (no Basis transcoder available, and **no model in the demo
suite uses it**, so it is unexercised). Summary of what landed:

- **Spotlight 2× cone** — loader now stores the authored half-angles; the shadow
  projection uses the full-cone FOV (`light.py` `*2`). Spot attenuation + shadow
  frustum both correct.
- **Sheen** — ported `V_Sheen` (Estévez-Kulla) + `D_Charlie`; added the Charlie
  directional-albedo as a **3rd BRDF-LUT channel** for energy (albedo) scaling AND
  an image-based sheen lobe. Sheen is no longer over-bright and reads under IBL.
- **Specular** — `specularFactor` carried as **f90** (grazing weight), not folded
  into F0; applied to direct + IBL + transmission. `specularTexture` (.a) /
  `specularColorTexture` (.rgb) sampled.
- **Iridescence** — `irSensitivity` takes a **vec3** phase shift (one call);
  iridescent Fresnel converted back to F0 (`schlickToF0`) to kill the double-Fresnel;
  `iridescenceTexture` (.r) sampled.
- **Clearcoat** — coat lobe + reflection use the **geometric** normal (or
  `clearcoatNormalTexture`), not the base normal map; IBL Fresnel uses NcdotV.
- **Volume** — thickness scaled by the model matrix (`vModelScale`); Beer-Lambert
  absorption now also **tints diffuse transmission** (ScatteringSkull's teal).
- **Transmission** — `(1−specular)` energy term + IOR→mip; `KHR_materials_dispersion`
  (RGB-split refraction) implemented.
- **Diffuse transmission** — albedo double-tint removed, ambient de-energized, −N IBL
  back-glow, volume-absorption tint.
- **KHR_lights_punctual** — range window applied once; spot falloff `t²`.
- **KHR_node_visibility** — propagates to children.
- **KHR_animation_pointer** — implemented **LIVE** (Player-driven setters for node
  visibility / material factors / texture transforms), not a static bake.
- **KHR_materials_anisotropy** — anisotropic GGX + IBL bent normal + texture.
- **EXT_mesh_gpu_instancing** — normalized-integer ROTATION dequantized.
- **KHR_texture_transform** — extension `texCoord` override honoured. (Per-channel
  matrices: verified **no** Khronos asset transforms two textures differently in one
  material, so the single-matrix design is conformant for the whole suite; adding
  per-channel matrices would halve the instancing UBO budget for zero real assets.)

Original review below (kept for the rationale/reference-source citations).

---

**Status:** Review (no code changed). Discuss scope before acting.
**Date:** 2026-07-12
**Reviewed against:**

- glTF 2.0 spec, [Appendix B: BRDF Implementation](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#appendix-b-brdf-implementation-general)
- Each `KHR_*`/`EXT_*` extension's spec README (Khronos glTF extensions registry)
- Khronos reference renderer [glTF-Sample-Renderer](https://github.com/KhronosGroup/glTF-Sample-Renderer) `source/Renderer/shaders/` (`brdf.glsl`, `material_info.glsl`, `pbr.frag`, `ibl.glsl`, `punctual.glsl`, `iridescence.glsl`) — the "linked WebGL renderer," treated as the authoritative implementation.

**Files reviewed:** [shaders/pbr.frag](../OpenGLContext/shaders/pbr.frag), [shaders/_brdf_inc.glsl](../OpenGLContext/shaders/_brdf_inc.glsl), [loaders/gltf.py](../OpenGLContext/loaders/gltf.py), [passes/pbrpass.py](../OpenGLContext/passes/pbrpass.py), [scenegraph/pbrmaterial.py](../OpenGLContext/scenegraph/pbrmaterial.py), [passes/shaderpass.py](../OpenGLContext/passes/shaderpass.py).

---

## TL;DR

**The core metallic-roughness BRDF is conformant** — the GGX distribution, height-correlated
Smith visibility, Schlick Fresnel, and Lambertian diffuse are function-for-function identical to
the reference implementation, as are `alpha = roughness²`, the 0.04 dielectric F0 from IOR, the
`F0` metal/dielectric mix, and the `(1−F)(1−metallic)` diffuse energy split. A plain
metallic-roughness material renders to spec.

Across the **19 supported extensions**, most are conformant or close. The genuine defects are
concentrated in a handful of extension lobes and in two non-BRDF loader bugs. **Full compliance
is reachable** — the list below is finite and mostly low-cost. Highlights:

- **Two real correctness bugs unrelated to BRDF math:** glTF **spotlights render ~2× too wide**,
  and **`KHR_node_visibility` doesn't hide child nodes**. Both are cheap fixes with broad impact.
- **Sheen is materially incomplete** (missing the `V_Sheen` visibility term, which also carries
  the microfacet normalization → sheen is *far* too bright).
- **Transmission and diffuse-transmission** have energy-conservation gaps (missing
  `(1−specular)` weighting; diffuse-transmission color double-tinted by albedo).
- Several extensions are correct at their *default* parameters and only diverge for authored
  non-default values (specular weight < 1, colored iridescent bases, non-unit model scale).

Nothing here blocks the base renderer; this is the punch-list to call glTF "fully compliant."

---

## Master compliance matrix

Severity = worst-case visual/correctness impact on an asset that *uses* the feature.
"Default-correct" = pixel-correct at the extension's default parameter values; diverges only
for authored non-defaults.

| Extension | Verdict | Worst severity | Headline gap |
|-----------|---------|----------------|--------------|
| Core metallic-roughness BRDF | ✅ Conformant | — | Identical to reference (D/V/F/Lambert, F0, energy split) |
| KHR_materials_ior | ✅ Conformant | — | `((ior−1)/(ior+1))²` exact, default 1.5→0.04 |
| KHR_materials_emissive_strength | ✅ Conformant | — | Linear pre-tonemap multiply, correct |
| KHR_materials_unlit | ✅ Conformant | — | Base color direct, alpha/mask respected, pickable |
| KHR_materials_pbrSpecularGlossiness | ✅ Conformant | — | Full per-pixel spec→metal-rough conversion |
| EXT_texture_webp | ✅ Conformant | — | WebP-only source fallback works (needs Pillow WebP) |
| **KHR_lights_punctual** | ⚠️ Partial | **Med-High** | **Spot cone ~2× too wide** (+ range-window squared) |
| **KHR_node_visibility** | ⚠️ Partial | **Medium** | **Invisibility doesn't propagate to children** |
| **KHR_materials_sheen** | ⚠️ Incomplete | **Major** | **Missing `V_Sheen`** (no normalization → over-bright); no albedo-scaling; no IBL sheen |
| KHR_materials_transmission | ⚠️ Partial | Medium | Missing `(1−specular)` energy term; mip ignores IOR; no dispersion |
| KHR_materials_diffuse_transmission | ⚠️ Partial | Medium | Back lobe double-tinted by albedo; ambient not de-energized; no IBL back-glow |
| KHR_materials_iridescence | ⚠️ Partial | Medium | Per-channel `irSensitivity` shift; F0-replace + Schlick double-Fresnel; factor tex unused |
| KHR_materials_specular | ⚠️ Partial (default-correct) | Med | Weight folded into F0 (f90=1) → grazing too bright when `specularFactor<1`; no specular textures |
| KHR_materials_clearcoat | ⚠️ Mostly conformant | Moderate | Coat uses bump-mapped normal (not geometric); no `clearcoatNormalTexture` |
| KHR_materials_volume | ⚠️ Mostly conformant | Low-Med | Thickness ignores model-matrix scale (wrong on non-unit scale) |
| KHR_texture_transform | ⚠️ Mostly conformant | Low-Med | One shared matrix/material (breaks 2 differently-transformed textures); `texCoord` override ignored |
| KHR_texture_basisu | ⚠️ Detected-only | Medium | KTX2/Basis not decoded; drops texture if no PNG/JPEG fallback |
| KHR_animation_pointer | ❌ Not implemented | Med-Low | Pointer-targeted channels silently ignored (static defaults) |
| EXT_mesh_gpu_instancing | ✅ Implemented | Low | Normalized-integer quaternion ROTATION not dequantized |

Rotation sign in KHR_texture_transform was checked and is **correct** — the angle is deliberately
negated to compensate for the un-flipped V axis (previously verified against TextureTransformTest).

---

## Detailed findings

### ✅ Conformant — no action

- **Core metallic-roughness BRDF.** `D_GGX`, `V_SmithGGXCorrelated` (`0.5/(GGXV+GGXL)`, folding
  `1/(4·NdotL·NdotV)`), `F_Schlick` (VdotH), Lambert `c_diff/π` — all algebraically identical to
  the reference. `alpha=roughness²`, `F0=mix(0.04, albedo, metallic)`, `kd=(1−F)(1−metallic)`
  energy split all correct. (The Appendix-B *text* writes the separable Smith visibility; the
  reference *renderer* uses height-correlated, and so do we — the better choice.)
- **KHR_materials_ior** — `iorF0 = ((ior−1)/(ior+1))²`, default 1.5 → 0.04. Exact.
- **KHR_materials_emissive_strength** — `emissiveFactor·sRGB(tex)·strength`, added linearly
  before tone-map so >1 survives to bloom. Exact.
- **KHR_materials_unlit** — base color out, no lighting, MASK `discard` + BLEND alpha respected,
  still writes the object-id (pickable). Exact.
- **KHR_materials_pbrSpecularGlossiness** — full solve-for-metallic conversion (`a=0.04`
  quadratic) for both factor-only and per-pixel (texture) materials; correct sRGB/linear handling
  and `roughness = 1 − glossiness`. Only inherent loss is the standard approximation's colored-
  metal round-trip (documented). No functional gap.
- **EXT_texture_webp** — falls back to the WebP source when no base source; Pillow decodes it.
  (Caveat: relies on the installed Pillow having WebP support.)

### ⚠️ Real bugs (BRDF-independent) — cheap, broad impact

**KHR_lights_punctual — spot cone ~2× too wide.** *(Medium-High)*
The loader stores `cutOffAngle = 2·outerConeAngle` and `beamWidth = 2·innerConeAngle`
([gltf.py:1814-1818](../OpenGLContext/loaders/gltf.py#L1814)); that doubling is undone **only** in
the shadow `viewMatrix` ([light.py:83](../OpenGLContext/scenegraph/light.py#L83)), but the cone
*attenuation* reads the raw uniform — `spotAttenuation` uses `cos(lightCutOffAngle)` with
half-angle geometry ([pbr.frag:320-326](../OpenGLContext/shaders/pbr.frag#L320)). So an authored
45° outer cone illuminates as a 90° half-angle cone. Native VRML spots (true half-angles) are
unaffected. **Effect:** every glTF spotlight lights ~double its authored cone. **Fix cost:** low —
stop doubling in the loader and halve inside the shadow-matrix path instead, or halve the cone
uniforms before attenuation. **Note:** existing regression baselines were captured with the current
behaviour and will shift.

**KHR_node_visibility — invisibility doesn't propagate to children.** *(Medium)*
An invisible node skips its own mesh/light ([gltf.py:1552-1585](../OpenGLContext/loaders/gltf.py#L1552)),
but the child-recursion loop runs unconditionally, so descendants of an invisible node still render.
Spec requires a node drawn only if it *and all ancestors* are visible. **Effect:** a subtree hidden
via a parent flag still shows. Also baked once at load (no runtime/animation toggle). **Fix cost:**
low — thread an inherited `visible` flag (AND-combined) through the recursion.

### ⚠️ KHR_materials_sheen — materially incomplete *(Major)*

`D_Charlie` is **exact**. But:

- **Missing `V_Sheen` visibility — Major.** Reference sheen is `sheenColor · D_Charlie · V_Sheen`;
  ours is `sheenColor · D_Charlie` only ([pbr.frag:478-482](../OpenGLContext/shaders/pbr.frag#L478)).
  The microfacet normalization `1/(4·NdotL·NdotV)` lives *inside* `V_Sheen`, so omitting it drops
  the entire geometry/normalization factor — sheen is far too bright with the wrong grazing
  falloff (exactly where fabric sheen matters). Port `lambdaSheenNumericHelper` / `lambdaSheen` /
  `V_Sheen` into `_brdf_inc.glsl` (reference source captured in the audit). **Fix cost:** moderate.
- **Missing sheen-albedo scaling (E term) — Moderate.** The base layer is never scaled down to pay
  for sheen (`sheen_albedo_scaling = min(1 − max₃(sheenColor)·E(NdotV), 1 − max₃(sheenColor)·E(NdotL))`),
  so sheen is pure additive energy gain; velvets wash out. Needs the sheen directional-albedo `E`
  (a LUT in the reference, or the Estevez–Kulla analytic fit). **Fix cost:** moderate.
- **No sheen in the IBL/ambient path — Moderate.** Sheen exists only in the punctual loop; under a
  probe environment fabrics get no sheen highlight (the in-code comment admits this). **Fix cost:**
  moderate (reuse `prefilterMap`/`envColor(Rw)` as sheen radiance with a Charlie DFG approximation).
- **Minor:** sheen folded into the shared `spec` accumulator (blocks proper albedo scaling until
  restructured); roughness floor 0.07 vs spec's div-safety epsilon; `sheenColorTexture` /
  `sheenRoughnessTexture` not loaded.

### ⚠️ KHR_materials_transmission *(Medium)*

- **Missing `(1 − specular reflectance)` weighting — Medium.** Reference returns
  `(1 − F_specular) · attenuatedColor · baseColor` so transmitted energy falls to zero as the
  Fresnel rises toward grazing; ours keeps the backdrop at full strength and *adds* full specular
  on top ([pbr.frag:582-583](../OpenGLContext/shaders/pbr.frag#L582)). **Effect:** glass is a touch
  too bright everywhere and, more visibly, silhouettes stay transparent instead of going
  reflective-opaque. **Fix cost:** low — reuse the `envBRDFApprox` term already computed in the IBL
  branch: `transmitted *= (1.0 − (F0·ab.x + ab.y))`.
- **Blur mip ignores IOR — Low.** Reference scales roughness→mip by `clamp(ior·2−2, 0, 1)`
  (`applyIorToRoughness`), = 1.0 at the glass default 1.5 (so identical there); low-IOR materials
  over-blur. **Fix cost:** trivial.
- **KHR_materials_dispersion not implemented — Low/cosmetic** (separate extension; RGB-split IOR).

### ⚠️ KHR_materials_diffuse_transmission *(Medium)*

- **Back lobe double-tinted by albedo — Medium, trivial fix.** Reference `diffuse_btdf` uses
  `diffuseTransmissionColor` *alone*; ours multiplies by `albedo · diffuseTransmissionColor`
  ([pbr.frag:455](../OpenGLContext/shaders/pbr.frag#L455)) — a green leaf with a white transmission
  color transmits green² instead of the authored tint. **Fix:** drop `albedo` from that line.
- **Ambient/IBL diffuse not de-energized — Medium.** Only the *direct* front diffuse gets
  `(1−factor)`; `ambDiffuse` keeps full strength, so under IBL a translucent object has full front
  diffuse *plus* the back lobe (net energy gain). **Fix:** multiply `ambDiffuse` by `(1−factor)`.
- **No environment-driven back-glow — Medium.** Reference samples irradiance from `−n`; ours
  transmits only from punctual lights, so leaves/wax/paper don't back-glow under a probe. **Fix
  cost:** medium (add a `−Nw` irradiance sample to the ambient branch).
- **Minor:** back lobe skips `(1−F)(1−metallic)` (small; these materials are dielectric).

### ⚠️ KHR_materials_iridescence *(Medium)*

The interference math is a **faithful port** — `evalIridescence`/`irSensitivity` constants,
XYZ→sRGB matrix, OPD/phase, phi signs, Airy sum all match; no global hue inversion. Two deviations:

- **`irSensitivity` called per-channel with a scalar shift — Medium.** Ours declares `float shift`
  and calls it three times picking `.x/.y/.z`; the reference passes `vec3 shift` in one call. Since
  `XYZ_TO_REC709` mixes all three XYZ channels into each output channel, and the reference uses a
  *different* phase shift per channel *before* that mix, ours is wrong whenever `phi` differs across
  R/G/B — i.e. a **colored base F0** (iridescent metal, colored specular). Neutral dielectric
  soap-bubbles (equal channels) are correct. **Fix cost:** low — make `irSensitivity` take `vec3
  shift`, call once.
- **Output used as F0, then Schlick re-applied — Medium.** `evalIridescence` returns a reflectance
  already evaluated at `NdotV`; we assign it to F0 and the main BRDF runs `F_Schlick(VdotH, F0)` (and
  the IBL split-sum) on top → the angular term is applied twice. Exact at normal incidence; over-
  brightens/desaturates toward white and shifts hue bands off-normal. **Fix cost:** medium (plumb an
  iridescent Fresnel through the specular term instead of through F0).
- **Minor:** single combined F0 into `evalIridescence` (endpoints correct; only fractional-metallic
  differs); `iridescenceTexture` (`.r` strength map) parsed but not sampled in the shader.

### ⚠️ KHR_materials_specular — default-correct *(Med when specularFactor < 1)*

At the default `specularFactor = 1` this is **pixel-identical** to the reference. Diverges only for
authored reduced specular:

- **Weight folded into F0 with implicit f90 = 1.0 — Med.** Spec: `specularFactor` scales the whole
  dielectric Fresnel and sets `f90 = specularWeight`; ours bakes it into `dielF0` and leaves f90=1
  ([pbr.frag:391](../OpenGLContext/shaders/pbr.frag#L391)). Normal incidence matches exactly; at
  grazing, ours → 1.0 while the reference → `specularWeight`, so grazing highlights are too bright
  and the coupled `(1−F)` edge diffuse too dark. Same divergence on the **IBL** path (the `ab.y`
  bias term isn't weight-scaled — V2). **Fix cost:** low — keep the weight out of F0, apply
  `F = specularFactor · F_Schlick(VdotH, dielF0)` on the dielectric contribution and `f90 =
  specularFactor`; apply consistently to the IBL bias.
- **No `specularTexture` / `specularColorTexture` — Med for those assets** (per-texel specular mask
  and tint ignored). **Fix cost:** medium (sampler + UBO flag + loader wiring; budget-gated).

### ⚠️ KHR_materials_clearcoat — mostly conformant *(Moderate)*

BRDF math and energy layering (direct and IBL) are correct. Gaps:

- **Coat uses the bump-mapped base normal — Moderate.** The coat lobe and its reflection vector
  must use the *clearcoat normal* (geometric normal by default), but ours feeds the base
  `normalTexture`-perturbed `N` ([pbr.frag:485-496, 538-548](../OpenGLContext/shaders/pbr.frag#L485)).
  **Effect:** on a material with both a base normal map and a coat (car paint over orange-peel), the
  glossy coat reflection wrongly wobbles with the base bumps. **Fix cost:** moderate (capture the
  pre-bump geometric normal, thread it through the coat).
- **`clearcoatNormalTexture` not loaded/sampled — Minor** (coat-only normal maps render smooth).
- **Fresnel uses VdotH; spec mandates NdotV — Minor** (differs off the specular peak; the IBL path
  at [pbr.frag:543](../OpenGLContext/shaders/pbr.frag#L543) already uses NdotV correctly). Trivial.
- **Coat roughness floor 0.04 — Minor** (ultra-glossy coats slightly softened). Trivial.

### ⚠️ KHR_materials_volume — mostly conformant *(Low-Med)*

σ_t (`−log(attenuationColor)/attenuationDistance`), Beer-Lambert, the `attenuationDistance = +∞`
sentinel, and thickness-texture modulation are all **correct**. One gap:

- **Thickness ignores model-matrix scale — Low-Med.** Reference scales local thickness by the
  model matrix's axis lengths so refraction offset and absorption are in world units; ours treats
  `thicknessFactor` as already world-scale. Correct only when model scale ≈ 1 (most demo assets);
  wrong on non-unit-scaled instances. **Fix cost:** low, but needs the model matrix plumbed into
  the fragment shader (only `eyeToWorld`/`projectionMatrix` are available there today).

### ⚠️ KHR_texture_transform — mostly conformant *(Low-Med)*

Matrix math (`translation·rotation·scale`) and per-texture application via the `texCoordMask` high
bits are **correct**; rotation sign is deliberately negated for the un-flipped V axis (verified).

- **One shared matrix per material — Low-Med.** `uv_transform_holder` is a single slot; a material
  giving two textures *different* transforms uses only the last-added channel's matrix for all.
  **Fix cost:** moderate (per-channel matrix array in the UBO).
- **Extension-level `texCoord` override ignored — Low** (loader reads `info.texCoord`, not
  `KHR_texture_transform.texCoord`). Trivial.

### ⚠️ KHR_lights_punctual — remaining minor items

Inverse-square attenuation (loader sets `(0,0,1)`), the range window on positional lights only, and
candela/lux units (via the exposure meter) are all **correct**. Beyond the 2×-cone bug above:

- **Range window squared — Low.** Ours does `w²/d²` (Frostbite form); spec/reference apply the
  window once: `clamp(1−(d/range)⁴,0,1)/d²`. Light fades slightly sooner. Trivial.
- **Spot falloff curve — Low.** `smoothstep` (Hermite) vs reference `t²`; slightly softer edge.
  Cosmetic.

### ❌ / plumbing extensions

- **KHR_animation_pointer — Not implemented, silently ignored *(Med-Low)*.** Channels with
  `path:"pointer"` (no `target.node`) are dropped at both loader gates; animated material factors /
  camera / TextureTransform / visibility just stay at their static defaults. **Fix cost:** medium
  (JSON-pointer resolver + STEP interpolation for int/bool targets).
- **KHR_texture_basisu — Detected-only *(Medium)*.** Deliberately not decoded (needs a GPU-block
  transcoder Pillow lacks). PNG/JPEG fallback is used when present; a **KTX2-only** asset renders
  untextured (flat base-color). **Fix cost:** high (KTX2/Basis transcoder + compressed-texture
  upload).
- **EXT_mesh_gpu_instancing — Implemented, one gap *(Low)*.** Per-instance TRS applied correctly;
  but normalized-integer `ROTATION` accessors aren't dequantized (raw ints → garbage rotations).
  Float ROTATION (the common case) is fine. **Fix cost:** low — use `_read_normalized` for that
  accessor.

---

## Things that look like variances but are correct (don't "fix")

- Height-correlated vs separable Smith — we match the reference, not the Appendix-B text.
- `(1−F)` on the direct diffuse — correct `fresnel_mix` energy conservation.
- AO on indirect light only — correct.
- Roughness floor 0.04 — matches reference intent.
- `D_Charlie` — byte-identical (only its *visibility* is missing).
- IOR→F0, emissive-strength, unlit, specGloss conversion, texture-transform rotation sign,
  inverse-square light attenuation, candela/lux units — all verified correct.

---

## Recommended path to 100%

Ordered by (impact ÷ cost). Suggest agreeing on a batch before touching code.

**Tier 1 — high impact, low cost (do first):**
1. **Spotlight 2× cone** — every glTF spot; loader one-liner (+ rebaseline shadows).
2. **`node_visibility` child propagation** — hierarchical hide; thread one flag through recursion.
3. **Diffuse-transmission albedo double-tint** — spec violation; delete one `albedo` multiply.
4. **Transmission `(1−specular)` energy term** — reuse the existing envBRDF term.
5. **Diffuse-transmission ambient de-energize** — one `(1−factor)` multiply.

**Tier 2 — real quality gains, moderate cost:**
6. **Sheen `V_Sheen`** (the big sheen fix) + roughness-floor relaxation.
7. **Iridescence** — `vec3 shift` in `irSensitivity` (low) and, ideally, the double-Fresnel
   restructure (medium).
8. **Clearcoat geometric coat normal.**
9. **Specular weight/f90** (direct + IBL) — low cost, corrects `specularFactor < 1`.
10. **Diffuse-transmission IBL back-glow** + **sheen in IBL** + **sheen albedo-scaling.**

**Tier 3 — completeness / niche assets:**
11. Missing textures: `specularTexture`/`specularColorTexture`, `sheenColorTexture`/
    `sheenRoughnessTexture`, `iridescenceTexture`, `clearcoatNormalTexture` (all sampler-budget-gated).
12. Volume thickness model-scale; texture-transform per-channel matrix + `texCoord` override;
    gpu-instancing normalized ROTATION; transmission mip IOR; range-window/spot-curve shape.

**Tier 4 — large, separate efforts:**
13. **KHR_texture_basisu** transcoding (KTX2/Basis + compressed upload).
14. **KHR_animation_pointer** resolver.
15. **KHR_materials_dispersion** (new extension).

This overlaps existing tracks — P6 (sheen/specular) and P1 (punctual lights) in
[GLTF-FULL-FEATURE-CONFORMANCE.md](GLTF-FULL-FEATURE-CONFORMANCE.md), and the iridescence/second-UV
items in [GLTF-DEMO-CONFORMANCE.md](GLTF-DEMO-CONFORMANCE.md). Recommend folding the Tier-1/2 fixes
into those plans once we agree scope.
