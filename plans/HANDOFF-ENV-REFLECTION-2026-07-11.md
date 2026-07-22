# Handoff — glTF env-reflection "upside-down" bug (2026-07-11)

## TL;DR
The reflected environment on metals was **upside-down on all real models**
(MetalRoughSpheres, MetalRoughSpheres Textureless, EnvironmentTest,
IridescenceMetallicSpheres, IridescenceSuzanne). Root cause found and fixed by
**removing a `flipY` hack** in `pbr.frag`. The fix is applied (uncommitted) but the
**after-image was not visually captured** because the GL driver wedged after
repeated subprocess captures. **Next session: restart cleanly, run the two GL
render checks below to confirm, then move to the remaining open items.**

## What was confirmed (high confidence)
- **Bug is real, reproduced at high res.** With the pre-fix shader, the top-left
  smooth metal sphere of MetalRoughSpheres (rendered against a solid-colour
  synthetic env: UP=red, DN=blue, RT=green, LF=yellow, FR=cyan, BK=magenta) showed
  **blue (DOWN) on top, red (UP) on bottom**, LEFT=yellow(LF), RIGHT=green(RT),
  while the scene was upright (the "Metal" label read normally). → vertical
  inversion only.
- **Root cause.** `pbr.frag` had `vec3 flipY = vec3(1.0,-1.0,1.0)` negating the Y of
  the world-space env sample direction (`Nw`, `Rw`). The env cubes are built +Y-up
  (`ibl.py`: UP.jpg→`GL_TEXTURE_CUBE_MAP_POSITIVE_Y`, offset 2) and `faceDir`
  (`_cubemap_inc.glsl`) matches the hardware cube-sampling convention, so **no flip
  belongs there**.
- **Why it shipped inverted / stayed green.** The flip was "validated" against
  `test_ibl_cubemap_render.py::_uv_sphere`, which was **wound inside-out**
  (CCW-normals point inward — proven: 2000/2000 triangles inward). That reversed
  winding rotated the fixture's reflection 180°, so `flipY` looked correct on that
  one sphere while inverting every correctly-wound model. The camera framing
  (`gltf_view._frame`) is identical for all models and `eyeToWorld = inv(view)` is
  model-independent (`_flat.py:291`), so env-reflection orientation is uniform
  across models — the fixture, not the models, was the outlier.
- **Fix is deterministic.** Removing the Y-negation, given the confirmed pre-fix
  state (blue/−Y on top), necessarily yields red/+Y (sky) on top with horizontal
  untouched (green/RT stays on the right) = correct mirror-ball optics.

## Changes made (uncommitted, in working tree)
1. `OpenGLContext/shaders/pbr.frag` (~line 481-488): removed `flipY`; now
   `Nw = normalize(e2w * N)`, `Rw = normalize(e2w * reflect(-V, N))`. Comment
   explains the history.
2. `tests/test_ibl_cubemap_render.py`:
   - `_uv_sphere` winding fixed to outward/CCW: `idx += [a, a+1, b, a+1, b+1, b]`
     (was `[a, b, a+1, a+1, b, b+1]`).
   - Added `_write_synth_env`, `_capture_env`, and
     `test_mirror_sphere_reflects_env_right_way_up` — decisive per-face check
     (top=red/UP, bottom=blue/DN, right=green/RT). Stronger than the old
     `test_env_reflection_is_not_upside_down` garden-brightness heuristic, which
     passed even while the bug was present.
3. `plans/GLTF-DEMO-CONFORMANCE.md`: "Env reflection orientation" bullet updated
   with the real root cause.
4. Memory: `live-demo-blocks-captures.md` added (see below).

## VERIFY FIRST next session (GL was wedged, after-image never captured)
Restart clean (no other GL app / demo running), then:
```
cd openglcontext
../.env/bin/python -m pytest tests/test_ibl_cubemap_render.py::test_mirror_sphere_reflects_env_right_way_up -x -rs -q
```
Expect PASS (top red / bottom blue / right green). If it SKIPS, GL capture is
unavailable — get a real GL target before trusting green.

Optional visual: capture MetalRoughSpheres against the synthetic env and eyeball
the top-left smooth metal sphere — it must now read **red on top** (was blue).
The cached glb is at
`<scratchpad>/MetalRoughSpheres.glb` (or `gltf.load_sample('MetalRoughSpheres')`;
sample cache under `~/.config/OpenGLContext/gltf_cache/`).

## Environment gotcha (cost a lot of time this session)
- A **running interactive demo** (`oglc-gltf-demo`) holds the Wayland display;
  subprocess `gltf_view --capture` then hangs/times out. Also, the demo loads
  shaders at startup, so a running instance shows **stale** rendering until
  restarted.
- Worse: even with no demo running, **repeated** subprocess captures wedge the GL
  driver — the *first* capture after a cooldown works (~1s), then subsequent ones
  time out and don't recover quickly. Space captures out; prefer a single capture
  per cooldown, or in-process hidden-GLFW tests (like `test_bloom_pass.py`).
- See memory `live-demo-blocks-captures.md`.

## Still open (reported this session, NOT the reflection bug)
- **Normal Tangent Test** — "not upside down, more like a glass lens." Separate
  tangent/normal handling; re-check after the env-reflection fix (metallic env
  reflection changed). Tangents were previously verified correct (`w=-1` for
  mirrored UVs).
- **UV Test** (TextureTransformTest, U and UV mappings) — still failing; distinct
  issue (likely wrap-mode / combined-transform on the arrow cells).
- **Transmission Roughness Test** — bottom-right set of boxes still don't match.
- Earlier-session open items still standing: Sponza collision barriers crossing the
  courtyard; RecursiveSkeletons background ring. See GLTF-DEMO-CONFORMANCE.md.

## Key file references
- Env sampling: `OpenGLContext/shaders/pbr.frag` (~481-520), `envColor` (~287).
- Env cube build/upload: `OpenGLContext/passes/ibl.py` (`load_cubemap_faces` 90,
  `_upload_env_faces` 225, `_CUBE_FACES` 72).
- Cube face dirs: `OpenGLContext/shaders/_cubemap_inc.glsl` (`faceDir`).
- eyeToWorld / IBL setup: `OpenGLContext/passes/_flat.py` (`iblSetup` 253, 291).
- Camera framing: `OpenGLContext/bin/gltf_view.py` (`_frame` 601).
- Demo env wiring: `OpenGLContext/bin/gltf_demo.py` (`apply_environment`,
  `default_env_prefix`).
