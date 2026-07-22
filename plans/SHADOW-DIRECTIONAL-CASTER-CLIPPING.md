# Directional shadows drop casters that fall outside the camera-fitted light volume

**Status:** **Fixed** (2026-07-11). See "Resolution" below; the diagnosis that
follows is kept for context.
**Area:** Rendering / cascaded shadow maps (not physics).
**Found via:** ground-level walk navigation in the `oglc-gltf` viewer (physics walk
mode). The default aerial framing hides it; walking through the parthenon
colonnade exposes it.

## Resolution

The remaining bug was confirmed to be the cascade **near plane**, not the XY
extent: a caster on the same light ray as the point it shadows shares that
point's light-space XY, so if the receiver is in view the caster can only be lost
to the near plane. A numeric reproduction (a column shadowed by a wall 3 m up-sun
in a tight near cascade) showed the caster at the receiver's XY but at NDC
`z = -1.19` — clipped.

Fix (1) from the proposal was implemented:

- [`shadowmath.directional_cascade`](../OpenGLContext/passes/shadowmath.py) takes an
  optional `caster_bounds` (a `(K,8,3)` array of per-caster world AABB corners) and,
  via [`_extend_near_for_casters`](../OpenGLContext/passes/shadowmath.py), pushes the
  ortho **near plane toward the light** far enough to include any caster whose
  light-space XY *box* overlaps the cascade footprint. Far and XY are untouched, so
  no XY resolution is lost.
- Boxes are tested per caster (not as a merged point cloud): a caster straddling
  the footprint edge usually has its up-sun corners *outside* the footprint XY even
  though it shadows the cascade, so per-corner gating wrongly dropped them. Only
  casters that actually overlap extend the near plane, so off-footprint scene
  geometry costs no depth precision.
- [`shadowmixin._renderDirectional`](../OpenGLContext/passes/shadowmixin.py) builds
  the per-caster boxes once from the full caster pool
  (`_casterWorldAABBCorners(self._toRender_cache)`) and passes them to every cascade.

Measured cost on the repro scene: near-cascade depth range grew ≤1.04×, farther
cascades unchanged — no meaningful precision/peter-panning regression.

Tests: `tests/test_shadowmath.py::TestDirectionalCascade` gained four cases
(clipped-without-bounds precondition, kept-with-bounds, XY unchanged,
off-footprint ignored); `tests/test_shadow_upsun_caster_gl.py` is a live-pipeline
GL regression that asserts the receiver-covering cascade keeps the up-sun caster
with the bounds and would clip it without them. Full shadow suite stays green,
including the directional-CSM pixel test in `test_shadow_rendering.py`.

Fix (2) (whole-scene XY fit for bounded models) was **not** needed and was not
implemented — the near-plane extension alone resolves the reported case.

## Symptom (reproduction)

In `oglc-gltf ../parthenon/parthenon.glb` (physics walk mode, shadows on):

1. Stand in front of the back-room (cella) entrance, looking in.
2. Turn ~90° right.
3. Walk toward a column on the exterior.

As you pass the edge of the wall, the column **suddenly loses its shadowing and
pops to near-full sunlight**. The lit region starts at the middle of the column
face and spreads left/right as you keep moving forward. It is a shadow *caster*
that stops being drawn into the shadow map, not a shading/normal bug.

## What is already correct (do not re-fix)

The **camera**-frustum caster-culling bug is already fixed and locked by a test:

- The shadow depth pass is fed the **full caster pool**, not the camera-visible
  set. A caster behind the camera is absent from the colour pass but present in
  the shadow pool.
- Locked by [`tests/test_shadow_offscreen_caster_gl.py`](../tests/test_shadow_offscreen_caster_gl.py)
  ("a caster outside the camera frustum must still cast shadows").

So the pool handed to the shadow pass is complete. The remaining loss happens
**later**, at the per-light stage.

## Root cause (the remaining bug)

For a directional light, each cascade builds its light view + ortho projection by
**fitting to the camera frustum corners**, then culls the caster pool to *that*
volume:

- [`OpenGLContext/passes/shadowmixin.py:312`](../OpenGLContext/passes/shadowmixin.py#L312)
  `_renderDirectional` → per cascade:
  - `corners = shadowmath.frustum_corners_world(camera_view, camera_proj, near_frac, far_frac)`
    (the slice of the **camera** frustum for this cascade),
  - `view, proj = shadowmath.directional_cascade(direction, corners, …)`,
  - `occluders = self._cullOccluders(self._toRender_cache, view, proj)`
    ([shadowmixin.py:337](../OpenGLContext/passes/shadowmixin.py#L337)) —
    **keeps only casters whose bounds intersect this light ortho volume.**

- [`OpenGLContext/passes/shadowmath.py:170`](../OpenGLContext/passes/shadowmath.py#L170)
  `directional_cascade` fits the ortho tightly to those frustum corners. The
  only slack is a single frustum-radius pad on the near/far planes:
  ```python
  near = -maxs[2] - radius
  far  = -mins[2] + radius
  proj = ortho_matrix(mins[0], maxs[0], mins[1], maxs[1], near, far)
  ```

**Consequence:** a caster that is inside the *scene* but outside the
*camera-frustum-fitted light volume* is either culled by `_cullOccluders` or
clipped by the ortho near/XY planes, so it is never written into the shadow map —
and everything it should have shadowed goes bright. The cella wall casting onto a
colonnade column is exactly this: the wall sits between the sun and the column but
off to the side/behind the view, so as you walk it leaves the fitted volume and
its shadow vanishes. The "spreads across the column as you move" is the ortho
boundary sweeping past the caster.

The sun in the viewer is low and to the side
(`DirectionalLight(direction=(-0.62,-0.42,-0.28))`,
[gltf_view.py `_default_lights`](../OpenGLContext/bin/gltf_view.py)), which makes
long grazing shadows from side geometry — the worst case for a frustum-fitted
volume.

## Verified vs. hypothesised

- **Verified (by reading the code):** the light ortho is fitted to the camera
  frustum corners; `_cullOccluders` culls to that ortho; the near pad is one
  frustum radius.
- **Hypothesised (not yet instrumented):** whether a given lost caster is dropped
  by `_cullOccluders`, by the near plane, or by the ortho XY bounds. Confirm
  before fixing — see "First step" below.

## Proposed fix

The standard fix is to stop letting the *camera* frustum bound the caster side of
the light volume. Two levers, smallest first:

1. **Extend the near plane toward the light to the scene bounds (cheap, safe).**
   Any caster between the light and the cascade must be included regardless of the
   camera. Push the ortho `near` out to cover the scene's occluder extent along
   the light axis (do **not** grow XY or far — this costs only depth range, not
   resolution, and is the classic "pancaking"/near-extend CSM fix).
   - `_renderDirectional` already has `occluder_points` and computes
     `_scene_depth_range`; transform the occluder AABB into light space and set
     `near = min(near, that_min)` in (or around) `directional_cascade`. Add an
     optional `caster_bounds` arg rather than changing existing call sites' math.
   - This alone likely fixes the reported case (the wall is *toward the sun*
     relative to the column, i.e. beyond the near plane).

2. **For side casters outside the ortho XY (if step 1 is insufficient):** for a
   **bounded** model (the `oglc-gltf` use case), fit the directional shadow to the
   **scene bounds** instead of the camera frustum — one whole-scene ortho (or make
   the farthest cascade scene-sized). Stable, complete shadows; the only cost is
   texel density over a large scene, which is fine for a single model viewer.
   Gate it (e.g. an env flag or a "bounded scene" heuristic from the loader's
   `world_min/world_max`) so large-world CSM behaviour is unchanged.

Prefer (1) globally; add (2) only for the bounded-viewer path if needed.

## Constraints / don't regress

- Keep the shadow suite green. Relevant files and counts:
  `test_shadowmath.py` (20), `test_shadowmixin.py` (31), `test_shadowcaps.py`
  (13), `test_shadow_sampler_packing.py` (12), `test_shadow_rendering.py` (5),
  `test_shadow_per_light.py` (5), `test_shadowmap.py` (3),
  `test_shadow_offscreen_caster_gl.py` (1), plus `shadow_*.py` visual demos.
- `directional_cascade` has direct unit tests in `test_shadowmath.py`; extend
  them for the near-extension rather than changing existing expectations.
- Extending the near plane reduces depth precision — watch for new peter-panning
  / acne in the shadow reference images; the depth range should grow only as much
  as the casters require, not to an arbitrary large value.
- Directional shadow cascade count is fps-adaptive; pin it with
  `OPENGLCONTEXT_SHADOW_CASCADES=<n>` for reproducible reference images (see
  CLAUDE.md).

## First step for whoever picks this up

Instrument which stage drops the caster, so the fix targets the real culprit:

1. Reproduce in a headless GL driver like `test_shadow_offscreen_caster_gl.py`:
   place a receiver + a side caster + a low directional light, put the camera so
   the caster is just outside the frustum, and log, per cascade, whether the
   caster survives `_cullOccluders` and whether it lands inside the ortho
   `[near, far] × [l,r] × [b,t]` (transform its AABB by `view @ proj`).
2. If it dies at the **near plane** → implement fix (1).
3. If it dies at **XY** → implement fix (2) for the bounded path.
4. Add a locking test (mirror the offscreen-caster GL test) that walks the camera
   so the caster leaves the frustum and asserts the receiver stays shadowed.

## Notes

- This is orthogonal to the physics work; it lives entirely in
  `passes/shadowmixin.py` + `passes/shadowmath.py`.
- The existing `SHADOW-MAPPING.md` plan is the reference for the overall shadow
  design (CSM, PCF/PCSS, range culling).
