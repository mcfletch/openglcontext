"""Draws lines of text with Pillow, sized in a Text node's units; no GL

A FontStyle names a face (:func:`face`, from the TrueType registry the
polygon fonts use): the family's member nearest the weight with the slant
asked. Where the family has no such slant the line is sheared, and where its
nearest weight is lighter than the bold asked the glyphs are stroked. A line
is drawn anti-aliased from that face at a
pixel size (:func:`draw_line`) and placed by its ink box about the line's
origin on the baseline, in the node's units, where ``size`` is the face's
em. Where Pillow has libraqm, the layout kerns, makes ligatures and shapes
complex scripts.
"""
from __future__ import annotations

import functools
import math
from typing import Any, NamedTuple, Optional

import numpy as np
from fontTools.ttLib import TTFont, TTLibError
from PIL import Image, ImageDraw, ImageFont, features

__all__ = ['Face', 'Line', 'advance', 'draw_line', 'em_pixels', 'face', 'pixels_per_unit']

#: The pixel em :func:`advance` measures at; widths are kept as fractions of it.
MEASURE_PIXELS = 256

#: Transparent pixels about a line's ink, so filtering at the edge of the
#: quad reads nothing but the line.
PAD = 2

#: The weight at and above which a style is bold.
BOLD = 600

#: The OS/2 width class of a face neither condensed nor expanded.
NORMAL_WIDTH = 5

#: How far a sheared line leans: the tangent of 12 degrees.
OBLIQUE = 0.2126

#: How wide the stroke round a made-up bold glyph is, in ems.
EMBOLDEN = 0.025

#: The least and most pixels an em is drawn at.
EM_PIXELS = (8.0, 512.0)

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


class Face(NamedTuple):
    """A font file, and whether its glyphs are stroked bolder or sheared"""

    path: str
    embolden: bool = False
    oblique: bool = False


def face(fontStyle: Any = None, mode: Any = None) -> Face:
    """The face a FontStyle's family and style name

    The family's member with the slant asked and the weight nearest it, of
    the width nearest normal; else the member of the nearest weight,
    sheared. A face lighter than the bold asked is stroked.
    """
    from OpenGLContext.scenegraph.text.fontprovider import TTFFontProvider  # noqa: PLC0415 the provider loads the registry
    registry = TTFFontProvider.getTTFRegistry()
    name = registry.fontNameFromStyle(fontStyle, mode=mode)
    weight, italic = registry.modifiersFromStyle(fontStyle, mode=mode)
    members = []
    for member in registry.fontMembers(name):
        path = registry.fontFile(member)
        found_weight, found_italic = registry.metadata(path).modifiers
        members.append((bool(found_italic) != bool(italic), abs(found_weight - weight),
                        abs(_width(path) - NORMAL_WIDTH), member, path, found_weight,
                        found_italic))
    if not members:
        return Face(TTFFontProvider.matchFile(fontStyle, mode)[0])
    _slant, _distance, _width_distance, _member, path, found_weight, found_italic = min(members)
    return Face(path, embolden=weight >= BOLD > found_weight,
                oblique=bool(italic) and not found_italic)


@functools.lru_cache(maxsize=256)
def _width(path: str) -> int:
    """The face's OS/2 width class, 1 (ultra-condensed) to 9 (ultra-expanded)"""
    try:
        with TTFont(path, lazy=True) as font:
            return int(font['OS/2'].usWidthClass)
    except (OSError, KeyError, TTLibError):
        return NORMAL_WIDTH


@functools.lru_cache(maxsize=64)
def _font(path: str, pixels: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, pixels, layout_engine=LAYOUT)


def advance(face: Face, text: str, size: float) -> float:
    """How far `text` advances the pen, in units where the em is `size`; kerned"""
    if not text:
        return 0.0
    return float(_font(face.path, MEASURE_PIXELS).getlength(text)) * size / MEASURE_PIXELS


def draw_line(face: Face, text: str, size: float, pixels_per_unit: float) -> Line:
    """`text` drawn from `face`, `size` units to the em, at `pixels_per_unit`"""
    pixels = max(1, round(size * pixels_per_unit))
    font = _font(face.path, pixels)
    if not text:
        return Line(None, 0.0, 0.0, 0.0, 0.0)
    stroke = max(1, round(EMBOLDEN * pixels)) if face.embolden else 0
    box = font.getbbox(text, anchor='ls', stroke_width=stroke)
    left, top = math.floor(box[0]), math.floor(box[1])
    right, bottom = math.ceil(box[2]), math.ceil(box[3])
    if right <= left or bottom <= top:
        return Line(None, 0.0, 0.0, 0.0, 0.0)
    width, height = right - left + 2 * PAD, bottom - top + 2 * PAD
    coverage = Image.new('L', (width, height), 0)
    origin = (PAD - left, PAD - top)
    ImageDraw.Draw(coverage).text(origin, text, font=font, fill=255, anchor='ls',
                                  stroke_width=stroke, stroke_fill=255)
    before = after = 0
    if face.oblique:
        coverage, before, after = _sheared(coverage, origin[1])
    image = Image.merge('LA', (Image.new('L', coverage.size, 255), coverage))
    # Pixels to units: the pixel em is `size` units
    scale = size / pixels
    return Line(image, (left - PAD - before) * scale, (right + PAD + after) * scale,
                -(bottom + PAD) * scale, -(top - PAD) * scale)


def _sheared(coverage: Image.Image, baseline: int) -> tuple[Image.Image, int, int]:
    """`coverage` leaning right by :data:`OBLIQUE` about the row `baseline`, and
    the columns it gained on the left and on the right"""
    width, height = coverage.size
    before = math.ceil(OBLIQUE * (height - baseline))
    after = math.ceil(OBLIQUE * baseline)
    # The source column of each output column: x_out = x_in + k (baseline - y)
    sheared = coverage.transform(
        (width + before + after, height), Image.Transform.AFFINE,
        (1.0, OBLIQUE, -before - OBLIQUE * baseline, 0.0, 1.0, 0.0),
        resample=Image.Resampling.BICUBIC)
    return sheared, before, after


def pixels_per_unit(modelview: Any, projection: Any, viewport_height: float) -> float:
    """How many pixels high one unit of a node's coordinates stands on screen at
    its origin, along whichever of its x and y axes is longer there

    The matrices are row vectors, as the engine's are.
    """
    placed = np.asarray(modelview, dtype='d') @ np.asarray(projection, dtype='d')
    origin = np.array((0.0, 0.0, 0.0, 1.0)) @ placed
    if abs(origin[3]) < 1e-12:
        return 0.0
    found = 0.0
    for axis in ((1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 0.0, 1.0)):
        end = np.asarray(axis) @ placed
        if abs(end[3]) < 1e-12:
            continue
        step = end[:2] / end[3] - origin[:2] / origin[3]
        found = max(found, float(np.hypot(*step)) * viewport_height / 2.0)
    return found


def em_pixels(on_screen: float) -> float:
    """The pixel em to draw at for an em `on_screen` pixels high: the next step
    of the square root of two at or above it, within :data:`EM_PIXELS`"""
    least, most = EM_PIXELS
    if on_screen <= least:
        return least
    step = math.ceil(2.0 * math.log2(on_screen / least) - 1e-9)
    return float(min(most, least * 2.0 ** (step / 2.0)))
