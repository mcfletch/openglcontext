# Water that reflects the scene

Status: **In progress** — 2026-09-23.

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

## Limits

- One plane per view: several sheets at different levels reflect the scene as
  seen in the nearest one.
- Transparent shapes — particles, glass — are not drawn into the reflection.
- The reflection is of the frame's culled set, so something outside the
  camera's frustum does not appear in the water even where its reflection
  would be in view.
