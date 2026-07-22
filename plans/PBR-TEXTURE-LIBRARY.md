# CC0 / PBR Texture & Material Asset Pipeline

**Status:** Planned (investigation). Make it easy to build demos and sample scenes
from a library of ready-made, freely-licensed PBR materials instead of the
hand-baked procedural textures currently used (e.g. the parthenon's
`textures.py`). The immediate driver is [ambientCG / CC0Textures](https://ambientcg.com/)
(formerly cc0textures.com), which ships high-quality tileable material sets as
`.zip` files under a CC0 (public-domain) licence — no attribution, no viral terms,
safe to redistribute inside the repo and in shipped demos.

## Goal

A small **material-library** subsystem that:

- **Imports a CC0 material `.zip`** (ambientCG layout) and produces a ready-to-use
  `PBRMaterial` node with the right channels wired to the right texture slots and
  the right colour spaces (sRGB vs linear).
- **Caches** unpacked/derived textures on disk so a demo doesn't re-unzip or
  re-pack every run, keyed the way the rest of the codebase caches derived data.
- Gives demo/sample code a **one-liner** to drop a named material onto geometry
  (`material_library.load('Marble012')` → `PBRMaterial`), replacing bespoke
  procedural bakes where a real scanned material reads better.
- Stays **license-clean**: only CC0 (or equivalently permissive) sources are
  bundled; a manifest records source + licence per material so provenance is
  auditable and `docs/` can credit correctly.

Non-goals for v1: an in-app material *editor*, live download UI, or a general
texture-authoring tool. This is an *import + cache + attach* pipeline.

## Where it plugs in — the renderer already takes image PBR

The PBR path is done and takes *image* textures per glTF channel. `PBRMaterial`
([scenegraph/pbrmaterial.py](../OpenGLContext/scenegraph/pbrmaterial.py)) holds a
`textures` dict of `PBRTexture` objects keyed by glTF channel name, with an `srgb`
flag per texture and per-context GL upload/mipmap:

| glTF channel key | Packing | Colour space |
|---|---|---|
| `baseColor` | RGB(A) albedo | **sRGB** |
| `metallicRoughness` | **G = roughness, B = metallic** (glTF ORM convention; R = occlusion if fused) | linear |
| `normal` | tangent-space RGB, **+Y (OpenGL) up** | linear |
| `occlusion` | R = ambient occlusion | linear |
| `emissive` | RGB | sRGB |

So the pipeline's real job is **format translation**: CC0 sets ship *separate*
Color / Roughness / Metalness / AO / Normal / Displacement maps, but glTF (and our
material) wants roughness+metallic (+AO) **packed into one RGB texture** in the
ORM layout. That packing is the core of the work.

## ambientCG `.zip` layout (what we're parsing)

A material download unzips to a flat folder of PNG/JPG named by convention, e.g.
for `Marble012` at some resolution `{1K,2K,4K,8K}` and format `{PNG,JPG}`:

```
Marble012_2K-PNG/
  Marble012_2K_Color.png          -> baseColor      (sRGB)
  Marble012_2K_Roughness.png      -> pack into MR.G  (linear, grayscale)
  Marble012_2K_Metalness.png      -> pack into MR.B  (linear, grayscale; absent for dielectrics)
  Marble012_2K_NormalGL.png       -> normal          (OpenGL +Y; prefer over NormalDX)
  Marble012_2K_NormalDX.png       -> (DirectX -Y; flip green if only this exists)
  Marble012_2K_AmbientOcclusion.png -> occlusion / MR.R
  Marble012_2K_Displacement.png   -> height (parallax/displacement; not yet consumed)
  Marble012_2K_Opacity.png        -> baseColor alpha (when present)
```

Naming is stable across their library, so a **regex/suffix map** (`_Color`,
`_Roughness`, `_Metalness`, `_NormalGL`, `_NormalDX`, `_AmbientOcclusion`,
`_Displacement`, `_Opacity`, `_Emission`) drives channel assignment. ambientCG
also publishes a JSON/CSV API and a per-asset metadata file — worth reading for the
licence string and dimensions rather than hard-coding.

### Channel handling rules

- **NormalGL vs NormalDX.** Prefer `NormalGL` (our shader is +Y-up). If only
  `NormalDX` exists, invert the green channel on import.
- **ORM pack.** Build one RGB image `R=AO, G=Roughness, B=Metalness`; set it as
  both `metallicRoughness` and `occlusion` (they read different channels of the
  same texture, exactly as glTF ORM assets do). Missing Metalness ⇒ B=0
  (dielectric); missing AO ⇒ R=255.
- **Resolution.** Default to importing the 1K or 2K set for demos (VRAM + repo
  size); expose the resolution choice. 8K is available but inappropriate to bundle.
- **Colour space.** `Color`/`Emission` sRGB; everything else linear — set the
  `PBRTexture.srgb` flag accordingly so the existing upload path is correct.

## Proposed shape

**New module `OpenGLContext/loaders/material_library.py`** (or a small
`materials/` package if it grows):

- `import_ambientcg_zip(path, resolution=None) -> MaterialAsset` — unzip to a
  cache dir, classify files by suffix, pack ORM, flip DX normals, read metadata.
- `MaterialAsset` — the classified, on-disk result (paths + licence + source URL +
  suffix→channel map); serialisable so it's imported once.
- `to_pbrmaterial(asset, uv_scale=1.0) -> PBRMaterial` — build the `PBRMaterial`
  node with `PBRTexture`s wired and colour spaces set; optional `TextureTransform`
  for tiling ([texturetransform.py](../OpenGLContext/scenegraph/texturetransform.py)).
- `material_library.load(name) -> PBRMaterial` — resolve a bundled/known material
  by name (from a small manifest) to a node, importing+caching on first use.

**Caching.** Unzip + ORM-pack are done once into a cache directory (mirror the
`cache.CACHE` keying the codebase already uses for derived data — key on the zip's
hash + resolution so re-packing is skipped and edits invalidate). Bundled sample
materials live under a `data/materials/` (or `docs/`-adjacent) tree with a
`MANIFEST` recording name, source URL, licence, resolution.

**Demo/sample use.** Replace or complement the parthenon's procedural
`textures.py` bake with a couple of real CC0 stone/marble materials to show the
pipeline; add a `tests/pbr_material_library.py` demo that lays out a row of spheres
each wearing a different imported material (doubles as a visual-regression test via
the auto-exit/capture harness).

## Other CC0 / permissive PBR sources to investigate

Cast a wide net so demos have variety and the importer isn't single-source-coupled:

| Source | Licence | Format / notes |
|---|---|---|
| **ambientCG** (ambientcg.com) | **CC0** | `.zip` per material; JSON/CSV API; huge tileable library. **Primary target.** |
| **Poly Haven** (polyhaven.com) | **CC0** | Textures **and** HDRIs **and** models; clean API + direct downloads. HDRIs feed our IBL (see [PBR-MATERIALS.md](PBR-MATERIALS.md) §IBL and [GLTF-COMPLETE-SUPPORT.md](GLTF-COMPLETE-SUPPORT.md)). Strong second source. |
| **cgbookcase.com** | CC0 | Tileable PBR sets, similar suffix layout. |
| **3DTextures.me** (Joao Paulo) | CC0 | Large library; ORM sometimes pre-packed. |
| **ShareTextures / TextureCan free tier** | CC0 / permissive | Mixed; verify per-asset licence. |
| **Khronos glTF-Sample-Assets** | mixed (mostly CC0/CC-BY) | Already used by the glTF conformance track; a source of *complete materials* not just textures. |
| **KenneyNL** (kenney.nl) | CC0 | Not scanned PBR, but CC0 prototype textures/kits useful for greyboxing demos. |
| **HDRIs for IBL** — Poly Haven, HDRI Haven (merged), sIBL archive | CC0 / CC-BY | Environment maps for the real-IBL work; a parallel "environment library" using the same import+cache+manifest pattern. |

**Also survey the shader/material *definition* side** (not just texture bitmaps),
since the ask mentions "PBR shaders and the like":

- **glTF `KHR_materials_*` extensions** already partly supported (clearcoat,
  transmission, sheen, specular, emissive-strength) — a *material* library that
  ships these as authored glTF material JSON (not just textures) would let demos
  pull complex materials directly. Ties into [GLTF-COMPLETE-SUPPORT.md](GLTF-COMPLETE-SUPPORT.md).
- **MaterialX** — the emerging open standard for interchangeable material graphs;
  AMD/NVIDIA/Adobe libraries publish CC0 MaterialX materials. Longer-term: a
  MaterialX → `PBRMaterial` (+ our shader) reader is a bigger effort but is the
  standards-aligned way to import authored materials, mirroring how the physics
  work adopted the OMI model natively. Note as future, not v1.
- **Filament / glTF material references** — Google Filament's material docs and
  the Khronos PBR neutral tone-map are useful references for matching look.

## Licensing & provenance discipline

- **Bundle only CC0** (or explicitly public-domain-equivalent). CC-BY sources may
  be *referenced/downloaded* by tooling but not committed without an attribution
  file; keep those out of the default bundle.
- Every bundled asset gets a `MANIFEST` row: name, source URL, licence, resolution,
  import date. A `docs/` credits page renders it (the parthenon already ships a
  `CREDITS.txt`).
- The importer records the source licence string from the download metadata so
  provenance is machine-checkable, not just a README claim.

## Open questions / risks

- **Repo size.** Bundling even 1K materials adds MBs. Options: commit a *small*
  curated set only; or ship a `material-fetch` CLI that downloads+caches on demand
  (like the glTF viewer's URL streaming) so nothing large lives in git. Likely
  both — a tiny bundled set for offline demos + a fetch tool for the rest.
- **ambientCG naming drift.** Suffix conventions are stable but not contractual;
  isolate the suffix→channel map in one place (mirrors how physics isolates the OMI
  spelling in one module) and prefer their metadata API where available.
- **Displacement/height unused.** Our shader has no parallax/displacement yet;
  height maps are imported and cached but not consumed until a parallax-occlusion
  or tessellation-displacement path exists (possible tie-in to GPU tessellation).
- **AO double-counting.** With real IBL, a baked AO map plus SSAO/IBL occlusion can
  darken twice; expose an occlusion strength (the material already has
  `occlusionStrength`) and document the interaction.
- **Tiling seams / UV scale.** Tileable sets still need per-object UV scaling; wire
  a `TextureTransform` and pick sensible per-material defaults.
- **Normal-map convention bugs.** The GL/DX green-flip is the classic footgun;
  pin it with a unit test that checks a known DX map is inverted on import.

## References

- ambientCG: <https://ambientcg.com/> (CC0; downloads API at `/api/v2/`).
- Poly Haven: <https://polyhaven.com/> (CC0 textures, models, HDRIs).
- glTF ORM / metallic-roughness texture packing (glTF 2.0 spec §material).
- Related plans: [PBR-MATERIALS.md](PBR-MATERIALS.md) (the render path + IBL),
  [GLTF-COMPLETE-SUPPORT.md](GLTF-COMPLETE-SUPPORT.md) (material extensions, IBL,
  sampler/wrap+mipmaps), [Procedural backgrounds / environment] (HDRI environments).
