# Text drawn by Pillow

Status: in progress (2026-10-08).

## Why

The X3D corpus and the text demos show three faults in the engine's text:

- Screen and HUD text comes from images of DejaVu Sans Mono made in
  advance at 10 to 32 pixels; the nearest is used, and every face is that
  one monospaced face.
- A `Text` node is drawn as flat polygons from the glyph outlines, with no
  smoothing on the edges, so slanted strokes in bold and italic step.
- Neither path reads a font's kerning.

## Direction

Agreed 2026-10-08: draw text with Pillow, which the engine already depends
on. Pillow draws a string from any installed face at any pixel size,
anti-aliased; with libraqm (present here) it kerns, makes ligatures and
shapes complex scripts.

1. `scenegraph/text/pillowtext.py` - no GL. A FontStyle resolved to a font
   file (family, style; the registry the solid font uses), and a line of text
   as a coverage image with its ink box in the Text node's units: `size` is
   the face's em, lines `size` x `spacing` apart.
2. A `texture` font provider, first in the default search order. Each line
   is a quad over its ink box carrying a white image whose alpha is the
   coverage, bound as the base colour map, so the material colours and
   lights it in both renderers and a Text shape is sorted and blended with
   the transparent shapes. The pixel size follows the text's size on screen,
   in steps, with mipmaps for distance. Text casts no shadow.
3. The overlay UI and the HUD: glyphs drawn by Pillow at the size asked,
   from the face asked, kerned, in an atlas made as glyphs are needed.

The polygon fonts stay, for `FontStyle3D` formats that ask for them
(`solid`, `outline`, extruded `thickness`).

## Limits

- A texture on a Text shape's appearance is not drawn; the text takes its
  material's colour.
- Text casts no shadow.
