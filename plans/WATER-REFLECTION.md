# Water that reflects the scene

Status: **Complete** — 2026-09-23.

## Why

Water's look is mostly what it reflects: the far shore, the trees, the jetty,
the fire on the bank. The PBR shader reflects only the image-based-lighting
probe, which holds the sky and nothing standing in it, so a lake drawn by the
engine is a rippled sheet of sky colour. The lakeside demo
(`tools/blender/demos/lakeside.glb`) reads as "a textured surface rather than
water" for exactly that reason: no hill, no jetty and no flame appears in it,
and the ripple has nothing to break up but a gradient.

## What lands

A planar reflection, the standard answer for a flat body of water:

- **Which plane.** Each view, before the opaque pass, the draw records are
  searched for water — a geometry carrying `wave_style` — and the sheet nearest
  the camera gives the plane: a point on it and its normal, from the record's
  world matrix. A camera below that plane gets no reflection; it is looking up
  through the surface.
- **The mirrored render.** The view matrix is premultiplied by the reflection
  about that plane, and the view's opaque records are drawn through it into an
  offscreen RGBA16F target at half the view's size, in linear HDR. The
  projection is given an oblique near plane on the water plane (Lengyel), so
  everything below the surface is clipped in every program the pass draws
  with, with no clip-plane code in any shader. Winding flips under a mirror;
  `PBRMesh` already follows the modelview's determinant, and everything else is
  drawn with `glFrontFace(GL_CW)`. Water itself is left out.
- **The sky.** The target is cleared to alpha 0 and geometry writes alpha 1,
  so where nothing was drawn the water keeps the probe's reflection, which is
  the sky. The background is never drawn mirrored.
- **Reading it.** In `pbr.frag`, on a draw with `waveEnabled`, the environment
  specular term takes the reflection target at the fragment's own screen
  position, displaced by the rippled normal, blended over the probe by the
  target's alpha. The split-sum weight already applied to that term is water's
  Fresnel (F0 0.02 from IOR 1.33), so the reflection is faint looking down and
  strong at a glance across the surface.
- **Cost and switch.** One extra opaque draw of the view at quarter the
  pixels, only in a frame with water in view. `ContextDefinition.waterReflection`
  (env `OPENGLCONTEXT_WATER_REFLECTION`, default on) turns it off. A driver
  whose fragment stage has 32 or fewer texture units compiles it out
  (`PBR_PLANAR_REFLECTION`) and keeps the probe reflection.

## What else it took

The lakeside demo showed two more things wrong with the water once it
reflected anything, and both are fixed with it:

- **The ripple was one strength everywhere**, which reads as a texture laid
  over the surface. It now varies in gusts: two long trains (23 and 37 ripple
  lengths) take it from 0.1 to 1.6 of the style's steepness, drifting at 0.6 of
  its speed (`_GUST_TRAINS`, `GUST_*`, shared with `_wave_inc.glsl`).
- **Far water drew its full ripple**, which at a few pixels a wave aliases into
  a grid. Each train now fades as its wavelength falls from four pixels across
  to two, measured in the fragment shader from `fwidth` of the surface
  position (`PIXELS_PER_WAVE`). `wave_normal` stays the unfiltered field.
- `BREEZE` was retuned against the demo: 1.1 m waves 1.2 cm high, a 0.32 m
  ripple at 0.081 rad.

The mirrored render culls the frame's own walk of the scene through the
mirrored camera's frustum, so something above the top of the view that
reflects into it is drawn. `prepareViews` keeps the walk on the pass for that
until `finishViews`.

## Limits

2026-09-24: water is now one case of [PLANAR-MIRRORS.md](PLANAR-MIRRORS.md),
which lifts the first, third and fourth of these: every sheet is its own
mirror in its own plane, a mirror is never in a shared draw, and the distortion
is `reflector.WATER`'s `distortion`, which a lake can vary. `waterReflection`
became `planarReflections`.

- One plane per view: several sheets at different levels reflect the scene as
  seen in the nearest one.
- Transparent shapes — particles, glass — are not drawn into the reflection.
- With several views sharing one draw of an opaque water surface
  (`renderShared`), that surface reflects the sky alone.
- `REFLECTION_DISTORTION` (0.12 view widths per unit of tilt) is a single
  number for every body of water.
