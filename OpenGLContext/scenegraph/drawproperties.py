"""X3D's LineProperties, PointProperties and FillProperties as a draw's values; no GL

An `Appearance`'s `lineProperties`, `pointProperties` and `fillProperties`
(ISO/IEC 19775-1, 12.4) are read here into what the shaders take:

- :func:`line_style` - a line's width in pixels and its dash pattern.
  `linewidthScaleFactor` multiplies the nominal width of one pixel; zero or
  less is the nominal width. The linetypes X3D requires, 1 to 5 (solid,
  dashed, dotted, dash-dot, dash-dot-dot), have the patterns in
  :data:`PATTERNS`, in pixels at the nominal width and scaled with the
  width. Another linetype is drawn solid, and reported once.
- :func:`point_size` - a point's size in pixels at a distance from the
  viewer: `pointSizeScaleFactor` times the nominal size of one pixel, over
  ``a + b r + c r²`` for `attenuation` (a, b, c) and distance r, between
  `pointSizeMinValue` and `pointSizeMaxValue` times the nominal size.
- :func:`fill_style` - whether polygons are filled, and the hatching drawn
  over them: styles 1 to 6 (horizontal, vertical, rising, falling, square
  crosshatch, diagonal crosshatch) in `hatchColor`, lines :data:`HATCH_SPACING`
  pixels apart. Another style is drawn as style 1, and reported once.

Properties whose `applied` is false, or that are absent, are the defaults.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

__all__ = ['FillStyle', 'HATCH_SPACING', 'LineStyle', 'PATTERNS', 'PointSize',
           'fill_style', 'hatch_stipple', 'line_style', 'on_hatch', 'point_size',
           'stipple']

#: Each required linetype's dashes, alternately drawn and gap, in pixels at
#: the nominal width.
PATTERNS: dict[int, tuple[float, ...]] = {
    1: (),
    2: (8.0, 4.0),
    3: (1.0, 3.0),
    4: (8.0, 3.0, 1.0, 3.0),
    5: (8.0, 3.0, 1.0, 3.0, 1.0, 3.0),
}

#: The highest hatch style drawn as itself.
HATCH_STYLES = 6

#: Pixels between a hatch's lines.
HATCH_SPACING = 8.0

_reported: set[str] = set()


def _report(message: str) -> None:
    if message not in _reported:
        _reported.add(message)
        log.warning(message)


def _applied(properties: Any) -> bool:
    return bool(properties) and bool(getattr(properties, 'applied', True))


@dataclass(frozen=True)
class LineStyle:
    """A line's width in pixels and its dashes, drawn and gap, in pixels"""

    width: float = 1.0
    pattern: tuple[float, ...] = ()

    @property
    def plain(self) -> bool:
        """Whether this is the default one-pixel solid line"""
        return self.width == 1.0 and not self.pattern


def line_style(properties: Any) -> LineStyle:
    """The style a `LineProperties` node (or None) draws lines in"""
    if not _applied(properties):
        return LineStyle()
    scale = float(properties.linewidthScaleFactor)
    width = scale if scale > 0 else 1.0
    linetype = int(properties.linetype)
    pattern = PATTERNS.get(linetype)
    if pattern is None:
        _report('LineProperties linetype %d is drawn solid; linetypes 1 to 5 are drawn'
                % linetype)
        pattern = ()
    return LineStyle(width, tuple(length * width for length in pattern))


def stipple(style: LineStyle) -> tuple[int, int]:
    """`style`'s dashes as the fixed-function pipeline's line stipple: (factor, pattern)

    The pattern's sixteen bits are drawn from the lowest, each `factor`
    pixels long: the stipple repeats every 16 `factor` pixels, the multiple
    of 16 nearest the pattern's period, with the dashes in their proportions.
    (1, 0xFFFF) is solid.
    """
    if not style.pattern:
        return 1, 0xFFFF
    period = float(sum(style.pattern))
    factor = max(1, min(256, round(period / 16)))
    bits = 0
    position = 0.0
    for index, length in enumerate(style.pattern):
        first = round(position * 16 / period)
        last = round((position + length) * 16 / period)
        if index % 2 == 0:
            for bit in range(first, min(last, 16)):
                bits |= 1 << bit
        position += length
    return factor, bits or 1


@dataclass(frozen=True)
class PointSize:
    """A point's size: `scale` pixels over the attenuation, between `minimum` and `maximum`"""

    scale: float = 1.0
    minimum: float = 1.0
    maximum: float = 1.0
    attenuation: tuple[float, float, float] = (1.0, 0.0, 0.0)

    def at(self, distance: float) -> float:
        """The size in pixels at `distance` from the viewer"""
        a, b, c = self.attenuation
        divisor = a + b * distance + c * distance * distance
        size = self.scale / divisor if divisor > 0 else self.maximum
        return min(max(size, self.minimum), self.maximum)


def point_size(properties: Any) -> PointSize:
    """The size a `PointProperties` node (or None) draws points at"""
    if not _applied(properties):
        return PointSize()
    a, b, c = (float(value) for value in properties.attenuation)
    return PointSize(float(properties.pointSizeScaleFactor),
                     float(properties.pointSizeMinValue),
                     float(properties.pointSizeMaxValue), (a, b, c))


@dataclass(frozen=True)
class FillStyle:
    """Whether polygons are filled, and the hatch style (0 for none) and its colour"""

    filled: bool = True
    hatch: int = 0
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)

    @property
    def plain(self) -> bool:
        """Whether this is the default: filled, not hatched"""
        return self.filled and not self.hatch

    @property
    def invisible(self) -> bool:
        """Whether nothing is drawn: neither filled nor hatched"""
        return not self.filled and not self.hatch


def on_hatch(style: int, x: int, y: int) -> bool:
    """Whether pixel (x, y) is on a line of hatch `style`; as ``_fill_inc.glsl`` has it"""
    spacing = int(HATCH_SPACING)
    horizontal, vertical = y % spacing == 0, x % spacing == 0
    rising, falling = (x - y) % spacing == 0, (x + y) % spacing == 0
    return {1: horizontal, 2: vertical, 3: rising, 4: falling,
            5: horizontal or vertical, 6: rising or falling}.get(style, False)


def hatch_stipple(style: FillStyle) -> bytes:
    """`style`'s hatch as the fixed-function pipeline's 32 by 32 polygon stipple

    Rows from the bottom of the window, each four bytes with the leftmost
    pixel the highest bit of the first.
    """
    found = bytearray(128)
    for y in range(32):
        for x in range(32):
            if on_hatch(style.hatch, x, y):
                found[y * 4 + x // 8] |= 0x80 >> (x % 8)
    return bytes(found)


def fill_style(properties: Any) -> FillStyle:
    """The style a `FillProperties` node (or None) draws polygons in"""
    if not properties:
        return FillStyle()
    hatch = int(properties.hatchStyle) if properties.hatched else 0
    if hatch > HATCH_STYLES or hatch < 0:
        _report('FillProperties hatchStyle %d is drawn as style 1; styles 1 to %d are drawn'
                % (hatch, HATCH_STYLES))
        hatch = 1
    red, green, blue = (float(value) for value in properties.hatchColor)
    return FillStyle(bool(properties.filled), hatch, (red, green, blue))
