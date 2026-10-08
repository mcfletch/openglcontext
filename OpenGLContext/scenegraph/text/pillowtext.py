"""Draws lines of text with Pillow, sized in a Text node's units; no GL

A FontStyle names a face (:func:`face_file`, through the TrueType registry
the polygon fonts use). A line is drawn anti-aliased from that face at a
pixel size (:func:`draw_line`) and placed by its ink box about the line's
origin on the baseline, in the node's units, where ``size`` is the face's
em. Where Pillow has libraqm, the layout kerns, makes ligatures and shapes
complex scripts.
"""
from __future__ import annotations

import functools
import math
from typing import Any, NamedTuple, Optional

from PIL import Image, ImageDraw, ImageFont, features

__all__ = ['Line', 'advance', 'draw_line', 'face_file']

#: The pixel em :func:`advance` measures at; widths are kept as fractions of it.
MEASURE_PIXELS = 256

#: Transparent pixels about a line's ink, so filtering at the edge of the
#: quad reads nothing but the line.
PAD = 2

#: The layout Pillow kerns and shapes with, where it has one.
LAYOUT = ImageFont.Layout.RAQM if features.check('raqm') else ImageFont.Layout.BASIC


class Line(NamedTuple):
    """A drawn line of text

    ``image`` is white with the coverage in alpha (``LA``), or None for a line
    with no ink. ``left``, ``right``, ``bottom`` and ``top`` are its edges in
    the node's units about the line's origin on the baseline, y upward.
    """

    image: Optional[Image.Image]
    left: float
    right: float
    bottom: float
    top: float


def face_file(fontStyle: Any = None, mode: Any = None) -> str:
    """The font file a FontStyle's family and style name"""
    from OpenGLContext.scenegraph.text.fontprovider import TTFFontProvider  # noqa: PLC0415 the provider loads the registry
    return TTFFontProvider.matchFile(fontStyle, mode)[0]


@functools.lru_cache(maxsize=64)
def _font(path: str, pixels: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, pixels, layout_engine=LAYOUT)


def advance(path: str, text: str, size: float) -> float:
    """How far `text` advances the pen, in units where the em is `size`; kerned"""
    if not text:
        return 0.0
    return float(_font(path, MEASURE_PIXELS).getlength(text)) * size / MEASURE_PIXELS


def draw_line(path: str, text: str, size: float, pixels_per_unit: float) -> Line:
    """`text` drawn from the face at `path`, `size` units to the em, at
    `pixels_per_unit`"""
    pixels = max(1, round(size * pixels_per_unit))
    font = _font(path, pixels)
    if not text:
        return Line(None, 0.0, 0.0, 0.0, 0.0)
    box = font.getbbox(text, anchor='ls')
    left, top = math.floor(box[0]), math.floor(box[1])
    right, bottom = math.ceil(box[2]), math.ceil(box[3])
    if right <= left or bottom <= top:
        return Line(None, 0.0, 0.0, 0.0, 0.0)
    width, height = right - left + 2 * PAD, bottom - top + 2 * PAD
    coverage = Image.new('L', (width, height), 0)
    ImageDraw.Draw(coverage).text((PAD - left, PAD - top), text, font=font, fill=255,
                                  anchor='ls')
    image = Image.merge('LA', (Image.new('L', (width, height), 255), coverage))
    # Pixels to units: the pixel em is `size` units
    scale = size / pixels
    return Line(image, (left - PAD) * scale, (right + PAD) * scale,
                -(bottom + PAD) * scale, -(top - PAD) * scale)
