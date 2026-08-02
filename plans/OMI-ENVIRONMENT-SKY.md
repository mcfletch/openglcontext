# OMI_environment_sky Support

**Status: partial** — Phases 1 and 2 have landed. `loaders/gltf/environment_sky.py`
reads the document's `skies[]` and the active scene's `sky` index into typed
records, and builds the background each describes: **gradient** → `Background`
(the VRML97 gradient sphere), **panorama** → `HDRBackground` (equirectangular,
which also registers the panorama with the IBL probe) or `CubeBackground`
(cubemap, in the extension's `+X, -X, +Y, -Y, +Z, -Z` order), **plain** →
`SimpleBackground`. The node hangs off the scene root, where the ordinary
Background pass finds and binds it, and `GLTFScene.sky` carries the record
whether or not anything could draw it.

Two details worth knowing, both settled by test rather than by assertion:

- **Gradient colour stops are spaced evenly in *colour*, not in angle**, with
  the angle of each derived by inverting the curve. A `topCurve` of 0.15 moves
  almost the whole way from horizon to zenith colour within a few degrees of the
  horizon, and stops spread evenly up the dome draw that as a visible kink.
- **The panorama is rolled a quarter of its width at load.** The extension puts
  the middle of the texture at `+Z`; `dirToEquirect` puts it at `+X`. Converting
  once here keeps the one shared direction-to-UV mapping that stops the drawn sky
  and the reflections it drives from disagreeing.

**Still open:** Phase 3 (the physical sky) in full; the gradient **sun tint**,
which is azimuthal and so cannot go on the elevation-only colour stops; Phase 4
(the ambient contribution), read and kept but not applied; and the
`KHR_animation_pointer` wiring in Phase 5. Tests:
`tests/unit/test_gltf_environment_sky.py` (loader, 100% of the module) and
`tests/unit/test_gltf_environment_sky_render.py` (rendered frames). Documented in
[docs/gltf.html](../docs/gltf.html#sky). Original plan below.

---

## Goal

Load the [`OMI_environment_sky`](https://github.com/omigroup/gltf-extensions/tree/main/extensions/2.0/OMI_environment_sky)
glTF extension and drive the scene's sky/environment from it. The extension is a
declarative description of a sky — gradient, panorama, physical (atmospheric
scattering), or plain solid colour — plus an ambient-light contribution. Each of
its four sky types maps onto a background node OpenGLContext already renders; the
work is mostly **reading the extension's structure into the existing background
nodes** and registering the result as the IBL environment. Only the `physical`
sky needs a genuinely new shader.

## Extension structure (reference)

Document level — `extensions.OMI_environment_sky.skies[]`, each sky:

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `type` | string | required | `gradient` \| `panorama` \| `physical` \| `plain` |
| `ambientLightColor` | number[3] | `[0,0,0]` | ambient RGB; used when contribution < 1 |
| `ambientSkyContribution` | number | 1.0 | 0–1 blend between sky-derived ambient and `ambientLightColor` |
| `gradient` / `panorama` / `physical` / `plain` | object | null | present for the matching `type` |

Per-type payloads:

- **gradient**: `topColor`, `horizonColor`, `bottomColor` (required RGB);
  `topCurve` (0.15), `bottomCurve` (0.02), `sunAngleMax` (0.5 rad), `sunCurve` (0.15).
- **panorama**: `equirectangular` (texture index; top=+Y, middle=+Z, left=+X) **or**
  `cubemap` (6 texture indices in order +X, -X, +Y, -Y, +Z, -Z).
- **physical**: `groundColor` (`[0.3,0.2,0.1]`), `rayleighColor` (`[0.3,0.5,1.0]`),
  `rayleighScale` (`3e-5` m⁻¹), `mieColor` (`[1,1,1]`), `mieScale` (`5e-6` m⁻¹),
  `mieAnisotropy` (0.8, range −1..1). Scales are **inverse metres** — Godot/Unreal
  use inverse km, so those runtimes multiply by 1000; we keep glTF metres.
- **plain**: `color` (`[0,0,0]`).

Scene level — `scenes[i].extensions.OMI_environment_sky.sky` (integer, default 0)
selects which document-level sky the scene uses. Sun direction comes from the
scene's `KHR_lights_punctual` **directional** light (the physical/gradient sun
terms reference it), not from the extension.

All colour/curve fields are animatable via `KHR_animation_pointer`
(`/extensions/OMI_environment_sky/skies/{}/<type>/<prop>`).

## What already exists

| OMI sky type | Existing OpenGLContext piece | Gap |
|--------------|------------------------------|-----|
| `gradient` | `scenegraph/spherebackground.py` — gradient sky/ground sphere with per-angle colours + `vrml97_background.*` shader | Map 3-stop top/horizon/bottom + curves onto `skyColor`/`skyAngle`; add sun-tint term |
| `panorama` (equirectangular) | `scenegraph/hdrbackground.py` — equirect skybox + `ibl.set_equirect_env` IBL registration (`hdr_background.*`, `ibl_equirect.frag`) | Feed an LDR glTF texture (not just a `.hdr` URL) into the same path |
| `panorama` (cubemap) | `scenegraph/cubebackground.py` — six-face image cube | Assemble 6 glTF textures in OMI face order |
| `physical` | — | **New**: Rayleigh/Mie single-scattering skydome shader |
| `plain` | `scenegraph/simplebackground.py` — solid clear colour | Trivial colour map |
| ambient | world-up ambient hook already feeding the PBR/VRML97 ambient term | Drive it from `ambientLightColor`/`ambientSkyContribution` |

The glTF loader already parses top-level and scene-level extensions in
[loaders/gltf/scene.py](../OpenGLContext/loaders/gltf/scene.py) (see the
`KHR_lights_punctual` handling: `g.extensions` at document level, `scene.extensions`
per scene). This is the seam to read `OMI_environment_sky` from.

## Plan

### Phase 1 — Loader: read the extension into a neutral description
- In `loaders/gltf/`, add `environment_sky.py` parsing
  `g.extensions['OMI_environment_sky']['skies']` into a list of dataclasses
  (`GradientSky`, `PanoramaSky`, `PhysicalSky`, `PlainSky`) with all fields +
  defaults applied.
- Resolve the scene's selected index from `scene.extensions['OMI_environment_sky']['sky']`
  (default 0) in `scene.py`, exposing `GLTFScene.sky` alongside the existing light/camera wiring.
- Resolve panorama texture indices through the existing glTF texture loader
  (`loaders/gltf/textures.py`), reusing sRGB/wrap handling.

### Phase 2 — Map declarative skies to background nodes
- **gradient** → build a `SphereBackground`: translate `topColor`/`horizonColor`/
  `bottomColor` + `topCurve`/`bottomCurve` into the `skyColor`/`skyAngle`/`groundColor`
  stops the node already consumes; bake the curve shaping into the sampled stops (or
  pass curve uniforms if we extend the shader).
- **panorama/equirectangular** → refactor `hdrbackground.py` so the equirect skybox +
  `ibl.set_equirect_env` path accepts an in-memory texture (glTF LDR image), not only a
  `.hdr` URL. Factor the shared skybox/IBL-registration mix-in so both HDR-URL and
  glTF-panorama sources use it.
- **panorama/cubemap** → assemble a `CubeBackground` from the 6 textures in OMI order.
- **plain** → `SimpleBackground` with `color`.
- Attach the chosen node under the loaded scene root so the existing Background pass
  renders it, and register it as the IBL radiance source (gradient/plain synthesize a
  small equirect for IBL; panorama already has one).

### Phase 3 — Physical (atmospheric-scattering) sky
- New `scenegraph/physicalsky.py` + `shaders/physical_sky.vert/frag`: analytic
  single-scattering Rayleigh + Mie skydome (Preetham/Nishita-style), parameterised by
  `rayleighColor`/`rayleighScale`/`mieColor`/`mieScale`/`mieAnisotropy`/`groundColor`
  and the scene's directional-light sun vector. Keep glTF inverse-metre units; document
  the ×1000 inverse-km note.
- Render it in the Background pass and bake a low-res equirect capture of it to feed the
  IBL probe (so metals reflect the physical sky), reusing the equirect→env-cube path in
  `passes/ibl.py`.

### Phase 4 — Ambient contribution
- Feed `ambientLightColor` + `ambientSkyContribution` into the existing world-up ambient
  term: when contribution == 1 use the sky-derived ambient, else blend toward
  `ambientLightColor`.

### Phase 5 — Animation, viewer wiring, tests
- Wire the animatable colour/curve fields to `KHR_animation_pointer` (Player-driven
  setters, as done for other live-animated properties in PBR-BRDF-CONFORMANCE).
- `oglc-gltf` picks up the scene sky automatically; add a `--sky <index>` override.
- Tests: per-type loader unit tests (defaults + field parsing), a render test per sky
  type against a small authored `.gltf`, and an IBL-registration check that a metal
  sphere reflects each sky. Add an `OMI_environment_sky` sample to the conformance roster.

## Open questions
- Gradient curve fidelity: bake curves into sampled colour stops (no shader change) vs.
  add `topCurve`/`bottomCurve`/`sunCurve` uniforms to `vrml97_background.frag`. Start
  with baked stops; add uniforms only if banding shows.
- Physical-sky IBL cost: bake the equirect once on load and re-bake only when the sun
  (directional light) moves, matching the RUNTIME-IBL lazy-rebake policy.

## Related
- [RUNTIME-IBL.md](RUNTIME-IBL.md) — equirect→env-cube IBL path, `HDRBackground`, lazy re-bake.
- [GLTF-FULL-FEATURE-CONFORMANCE.md](GLTF-FULL-FEATURE-CONFORMANCE.md) — background-at-infinity, extension roster.
- [PHYSICS-COLLISION.md](PHYSICS-COLLISION.md) — precedent for building natively on an OMI glTF extension.
- "Procedural backgrounds / environment" (PROJECT-PLAN todo) — physical sky overlaps the procedural-skydome goal.
