# Runtime Image-Based Lighting (Per-Object Irradiance + Reflection)

## Status

Planned (idea). **Radiance HDR IBL sources: implemented** (see below).

## Delivered: Radiance HDR (`.hdr`) IBL sources + HDR skybox

The HDRI-source half of this plan is shipped:

* **`loaders/hdr.py`** -- a zero-dependency (numpy-only) Radiance RGBE decoder:
  header parse, new-style adaptive RLE + old-style RLE + flat scanlines, RGBE ->
  linear float32 `(H, W, 3)`. Tested headless incl. a real Poly Haven file.
* **`loaders/hdri.py`** -- a small catalogue of CC0 Poly Haven panoramas
  (name -> URL + licence/author/source provenance); `resolve()` accepts a
  catalogue name, a URL, or a local path.
* **Equirect -> IBL env** (`passes/ibl.py` + `shaders/ibl_equirect.frag`): the
  `IBLProbe` env cube can now be projected from an equirectangular HDR panorama
  (registered by a node or via `OPENGLCONTEXT_ENV_HDR`), feeding the existing
  irradiance / prefilter / BRDF chain. Generation-counted so an async panorama
  load rebuilds an already-built probe.
* **`scenegraph/hdrbackground.py`** -- `HDRBackground` node: loads a `.hdr` from a
  URL (fetched + cached through the Resolver) or path, draws it as an
  exposure-scaled, ACES-tone-mapped equirect skybox (matching the PBR pass's
  response), and registers the panorama as the IBL environment so metals reflect
  the sky drawn behind them.
* **Viewer wiring**: `oglc-gltf --environment <name|URL|path.hdr>` routes an HDR
  source to the probe + `HDRBackground` (cubemap prefixes still work); shared with
  the browser demo. `--background hdr` draws the panorama as the skybox.

Verified end-to-end: a mirror-metal glTF sphere under `studio_small_03` reflects
the studio (softbox highlight, floor, backdrop) with the sky drawn behind, and
under `kloofendal_43d_clear_puresky` reflects the blue-sky dome -- both
right-way-up. Tests: `test_hdr_loader`, `test_ibl_equirect[_render]`,
`test_hdr_background[_render]`, `test_hdri_catalog`, `test_gltf_view_hdr_env`,
`test_hdr_env_gltf`.

The still-**planned** part of this plan is the per-object probe capture + the
load-time/lazy caching model described below.

## Goal

Give **each object its own IBL set** (diffuse irradiance map + pre-filtered
specular reflection map) computed from that object's own vantage point, so an
object is lit and reflects *what it can see* from where it sits — the walls,
floor, and the scene's `Background` cube/sphere/skydome around it — rather than
one global environment map shared by the whole scene.

The IBL is computed **at load time** for the (large majority) static geometry,
and **lazily re-computed at run time** for the handful of objects that actually
move a meaningful distance. This is the key framing: it would be *extremely*
heavy if every object recomputed every frame, but a normal game scene has only a
small number of non-trivially moving objects, so static geometry pays the cost
once at load and moving objects amortize it over many frames.

Reference implementation to study:
[diharaw/runtime-ibl](https://github.com/diharaw/runtime-ibl) — real-time GPU
generation of the diffuse irradiance map, the pre-filtered specular (mip-chained
roughness) map, and the BRDF integration LUT.

## Motivation

Current PBR IBL (see [PBR-MATERIALS.md](PBR-MATERIALS.md) §9) uses a fixed, scene-
wide environment. That looks wrong for objects enclosed by geometry: a metal
sphere in a red room should reflect and be lit by the red walls next to it, not
by a distant sky, and two objects in different rooms should not share one
environment. Per-object IBL, computed from each object's location, fixes both.

## Per-object model

1. **Capture from the object's location.** Render the surrounding scene
   (including `Background`) into a small cubemap centred on the object — its AABB
   centre, or a chosen reference point. Exclude the object itself from its own
   capture.
2. **Irradiance convolution.** Convolve that cubemap into a low-res diffuse
   irradiance cubemap (cosine-weighted hemisphere integral).
3. **Pre-filtered specular.** Generate the GGX roughness mip chain; share one
   BRDF LUT across all objects (it is view/scene-independent — reuse the existing
   IBL path's LUT).
4. **Attach to the object.** Store the irradiance + pre-filtered maps on the
   Shape/material and bind them into the existing PBR IBL uniforms
   (`OPENGLCONTEXT_IBL=full`) when that object draws, instead of a single global
   probe.

## Caching + update policy (the cheap part for static scenes)

- **Cache key: down-sampled AABB centre.** Each object's cached IBL is tagged
  with the (quantized/down-sampled) AABB centre it was computed at.
- **Static geometry: compute once at load.** Never recomputed unless the object
  moves.
- **Moving/active geometry: lazy re-compute.** Only when the object has drifted
  away from its cached centre by more than a threshold (order of "a few metres" /
  one down-sample cell) is the IBL regenerated — *not* every frame. Re-computes
  are further rate-limited (at most one every N frames, and spread across frames
  so several movers don't all re-bake in the same frame) and tie into the fps-
  adaptive degradation already in the PBR path.
- **Budget/LOD.** Small cubemap faces (e.g. 32–64²) and low mip counts by
  default; distant or small objects can fall back to the global/analytic IBL.

The result: the whole cost model is "load-time bake for static geometry, occasional
lazy re-bake for the few things that move," which keeps a normal game scene cheap
while still giving correct local lighting.

## Radiance HDR (`.hdr`/`.pic`) support for IBL sources

Add a loader for the **Radiance RGBE HDR** format (and ideally equirectangular →
cubemap conversion) so existing IBL environment backgrounds — the near-ubiquitous
`.hdr` panoramas from Poly Haven, HDRI Haven, etc. — can be dropped in directly as
a `Background` / fallback environment. The per-object captures then composite that
background into what each object sees. Ties into the HDRI-for-IBL survey noted in
[PBR-TEXTURE-LIBRARY.md](PBR-TEXTURE-LIBRARY.md).

## Ties into

- [PBR-MATERIALS.md](PBR-MATERIALS.md) — dual-mechanism IBL (`full`/`analytic`);
  per-object maps feed the same `full` uniforms.
- [GLTF-COMPLETE-SUPPORT.md](GLTF-COMPLETE-SUPPORT.md) / [GLTF-DEMO-CONFORMANCE.md](GLTF-DEMO-CONFORMANCE.md)
  — "real IBL" / EnvironmentTest parity.
- [PBR-TEXTURE-LIBRARY.md](PBR-TEXTURE-LIBRARY.md) — HDRIs as future IBL imports.
- [PHYSICS-COLLISION.md](PHYSICS-COLLISION.md) — "moved far enough to re-bake" can
  reuse the moving-body / transform tracking that already exists there.
- [Procedural backgrounds / environment] — captured background feeds each object's
  IBL.
