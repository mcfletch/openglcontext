# Mirror hall shadows

Status: 📋 Open, parked 2026-09-25. Shadows in `oglc-mirrors` are still not
visible to a player walking the hall. This records what was tried, what was
established, and what to try next.

## The report

"There are no shadows in the mirror demo." The hall
(`OpenGLContext/bin/mirrorhall.py`) has four metal columns with a lamp on
each, a directional sun, windows in the right wall, a dais and a pool, on a
polished checkered marble floor that is itself a planar mirror.

## What was established

1. **The engine's shadows are correct.** Measured rather than judged by eye:
   - Shadows on against shadows off in the hall changes 78-84% of the frame, so
     every light is casting and the maps are being read.
   - A minimal scene (floor, a roof with a square hole, a directional sun)
     puts the patch exactly where the geometry says it should fall, at a
     steep sun and at the hall's low one, in all three directions tried.
   - In the hall, the expected sun patch from the far window was projected
     into the camera and drawn over the render: the lit area lies inside the
     predicted outline, cut by the shadow of the column standing in it.
   - The cascade count (1, 2, 4) changes nothing, so cascade selection is not
     involved.
   - A metal column that looked "sunlit over its full height" in a sun-on
     against sun-off diff was reflecting the sunlit room through the captured
     probe; it is not a shadow fault.
2. **The first state of the hall hid its shadows three ways** (all fixed in
   `e49475e`):
   - the outdoor sky probe lit the interior at full strength, and environment
     light is never shadowed;
   - each lamp sits 0.25 m above a 0.3 m emissive housing, which shaded a
     ~2 m circle round every column -- exactly where the column shadows fall;
   - the sun (`(-0.3, -1, -0.4)`, intensity 0.3) came down steeply enough that
     the ceiling covered all of it.
3. **After those fixes the shadows are present but do not read.** On a plain
   white or grey floor in the same room they are plain: radial column shadows
   from the lamps and a window-shaped sun patch with its glazing bars. On the
   demo's floor they vanish, for reasons that compound:
   - the floor is a high-contrast black/white marble checker at 30 cm, which
     masks a low-frequency 15-20% darkening;
   - it is polished (roughness ~0.08) and a planar mirror, so at the glancing
     angles a walking camera sees it from, most of what reaches the eye is the
     reflected room, which a shadow on the floor does not darken;
   - four lamps of equal strength on the columns fill each other's shadows,
     and each column's own shadow falls at its foot;
   - the captured room probe is still a large share of the light.
   The marble maps themselves are sound (metallic 0, roughness in G, base
   colour sRGB); dropping the normal map changes nothing, dropping the base
   colour map makes the shadows obvious.

## What landed on the way

- `f6a8d63` (engine): a material's maps each land on their own texture unit
  on the draw that uploads them. The first frame of the hall showed its
  reflections in magenta and yellow because each upload rebound the unit of
  the previous map.
- `e49475e` (hall): a capture `Zone` round the room for its environment
  (intensity 0.4), a low sun `SUN = (-0.6, -0.45, -0.66)` at 6.0 through the
  windows onto the floor and the dais, lamps at 2.0, lamp housings with
  `castsShadow = False`. Three tests in `tests/unit/test_mirror_hall.py`.

## What might fix it

In rough order of expected effect for the effort:

1. **Make the sun the key light and put its patches where they are seen.**
   Raise the sun well above the lamps (10+), lower the zone intensity further
   (0.2-0.25), and choose a direction whose window patches fall on open floor
   in the start view with a column standing in one, so its shadow crosses
   the patch. Check each choice by projecting the expected patch into the
   start camera, as was done here, rather than by eye.
2. **Hang the lamps instead of standing them on the columns.** Pendants
   between the columns, or wall sconces on the pilasters, throw long column
   shadows across the floor; lamps on the columns can only light the ceiling
   and their own feet.
3. **Fewer, unequal lamps.** One or two strong lamps and a dim fill cast
   shadows that are not filled in by the others.
4. **Tone the floor down.** A lower-contrast marble (cream and grey rather
   than white and black), or a rougher polish, lets diffuse shading show; the
   polished mirror floor is what the demo is for, so this trades against it.
   A matte runner or rug down the middle would carry visible shadows without
   giving up the mirror.
5. **Check the reflected room is shadowed too.** The floor mostly shows the
   room reflected; if the mirror views light what they draw without the
   shadow maps, or with the environment rather than the zone's capture,
   the reflection of a shadowed wall is unshadowed. The pool read turquoise
   in the far mirror and dark in the direct view, which suggests the mirror
   views are lit differently from the main view. Worth confirming in
   `_drawMirrorViews` / `setupViewLighting(fitted=False)` before any of the
   art changes, since it is an engine question.

## Tools

Scratch tests rendering the hall through `render_scene` with overrides for
the viewpoint, sun direction and intensity, lamp intensity, zone on/off and
shadows on/off, diffing pairs of frames (shadows on/off, sun on/off) and
overlaying the predicted sun patch. None were kept in the suite; the
technique is the part to reuse: a sun-on minus sun-off diff shows exactly
what the sun lights, which judging a single frame by eye did not.
