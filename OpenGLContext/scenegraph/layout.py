"""X3D's Layout arithmetic: rectangles on the screen, and the matrices that
put children in them -- no GL

A ``Layout`` (ISO/IEC 19775-1, 36.4.1) places a rectangle within its parent's
and gives the children of its ``LayoutGroup`` or ``LayoutLayer`` a coordinate
system centred on that rectangle. Each of its fields has a horizontal and a
vertical value; a field given one value uses it for both.

- ``size`` in ``sizeUnits`` is the rectangle's width and height.
- ``align`` puts the rectangle against the parent's LEFT, CENTER or RIGHT
  edge, and its BOTTOM, CENTER or TOP.
- ``offset`` in ``offsetUnits`` moves it from there.
- ``scaleMode`` is how long a unit of the children is: NONE keeps the
  parent's, FRACTION makes one unit the rectangle's width (or height), PIXEL
  one pixel, and STRETCH whatever the other axis's is, so the children keep
  their shape; both STRETCH take the longer side of the rectangle.

Units are FRACTION of the parent's rectangle, PIXEL, or WORLD, which is
whatever units the parent layout measures that axis in, and FRACTION for a
layout with no parent layout; the outermost layout's parent rectangle is the
whole of the layer's viewport. An outermost NONE scale is FRACTION. These are
the readings X_ITE gives the fields.

Lengths are worked in the camera's eye space. A layer drawn through an
``OrthoViewpoint``, as a ``LayoutLayer`` is by default, measures the same at
every depth; through a perspective viewpoint a pixel is measured at the
depth of the layout's origin.

:func:`screen_modelview` is the ScreenGroup's and ScreenFontStyle's: a
coordinate system whose unit is one pixel, facing the screen.

Matrices are 4x4 and row-vector, ``point @ matrix``, as the engine's are.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple, Optional

import numpy as np
from vrml.x3d import nodes as x3d

__all__ = [
    'LayoutEye', 'LayoutSpec', 'Region', 'eye_per_pixel', 'local_matrix', 'place',
    'place_layouts', 'screen_modelview', 'spec_of', 'view_extent',
]

WORLD, FRACTION, PIXEL = 'WORLD', 'FRACTION', 'PIXEL'
NONE, STRETCH = 'NONE', 'STRETCH'
UNITS = (WORLD, FRACTION, PIXEL)
SCALE_MODES = (NONE, FRACTION, PIXEL, STRETCH)
#: Where an origin at or behind the eye is measured from instead.
NEAREST = 1e-6


@dataclass(frozen=True)
class LayoutSpec:
    """A Layout node's fields, each a (horizontal, vertical) pair"""

    align: tuple[str, str] = ('CENTER', 'CENTER')
    offset: tuple[float, float] = (0.0, 0.0)
    offsetUnits: tuple[str, str] = (WORLD, WORLD)
    size: tuple[float, float] = (1.0, 1.0)
    sizeUnits: tuple[str, str] = (WORLD, WORLD)
    scaleMode: tuple[str, str] = (NONE, NONE)


def _pair(values: Any, default: tuple[Any, Any]) -> list[Any]:
    """Two values: both given, one given for both, or the default"""
    found = list(values) if values is not None else []
    if not found:
        return list(default)
    if len(found) == 1:
        return [found[0], found[0]]
    return found[:2]


def _number(value: Any, default: float) -> float:
    value = float(value)
    return value if np.isfinite(value) else default


def _word(value: Any, allowed: Sequence[str], default: str) -> str:
    word = str(value).upper()
    return word if word in allowed else default


def spec_of(layout: Any) -> LayoutSpec:
    """The :class:`LayoutSpec` of a Layout node; values it does not know take
    the defaults"""
    align = _pair(layout.align, ('CENTER', 'CENTER'))
    offset = _pair(layout.offset, (0.0, 0.0))
    offset_units = _pair(layout.offsetUnits, (WORLD, WORLD))
    size = _pair(layout.size, (1.0, 1.0))
    size_units = _pair(layout.sizeUnits, (WORLD, WORLD))
    scale = _pair(layout.scaleMode, (NONE, NONE))
    return LayoutSpec(
        align=(_word(align[0], ('LEFT', 'CENTER', 'RIGHT'), 'CENTER'),
               _word(align[1], ('BOTTOM', 'CENTER', 'TOP'), 'CENTER')),
        offset=(_number(offset[0], 0.0), _number(offset[1], 0.0)),
        offsetUnits=(_word(offset_units[0], UNITS, WORLD), _word(offset_units[1], UNITS, WORLD)),
        size=(_number(size[0], 1.0), _number(size[1], 1.0)),
        sizeUnits=(_word(size_units[0], UNITS, WORLD), _word(size_units[1], UNITS, WORLD)),
        scaleMode=(_word(scale[0], SCALE_MODES, NONE), _word(scale[1], SCALE_MODES, NONE)),
    )


@dataclass(frozen=True)
class Region:
    """A layout's rectangle, as the layouts inside it see it

    ``size`` is its width and height in eye units; ``sizeUnits`` and
    ``offsetUnits`` are the units a WORLD value inside it is read in.
    """

    size: tuple[float, float]
    sizeUnits: tuple[str, str] = (FRACTION, FRACTION)
    offsetUnits: tuple[str, str] = (FRACTION, FRACTION)


def view_extent(projection: Any, depth: float) -> tuple[float, float]:
    """The width and height in eye units the view spans `depth` in front of
    the eye: the same at every depth for an orthographic projection"""
    matrix = np.asarray(projection, dtype='d')
    across = (abs(matrix[0, 0]), abs(matrix[1, 1]))
    if across[0] < 1e-12 or across[1] < 1e-12:
        return (0.0, 0.0)
    if abs(matrix[2, 3]) < 1e-12:
        return (2.0 / across[0], 2.0 / across[1])
    depth = max(float(depth), NEAREST)
    return (2.0 * depth / across[0], 2.0 * depth / across[1])


def eye_per_pixel(projection: Any, pixels: Sequence[float], depth: float) -> tuple[float, float]:
    """How long one pixel of a viewport `pixels` (width, height) is in eye
    units, `depth` in front of the eye"""
    width, height = view_extent(projection, depth)
    return (width / max(float(pixels[0]), 1.0), height / max(float(pixels[1]), 1.0))


def _decompose(modelview: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(rotation rows, scale per axis, translation) of a row-vector matrix"""
    matrix = np.asarray(modelview, dtype='d')
    axes = matrix[:3, :3]
    scale = np.linalg.norm(axes, axis=1)
    safe = np.where(scale > 1e-12, scale, 1.0)
    return axes / safe[:, None], scale, matrix[3, :3].copy()


def _resolved(unit: str, inherited: str) -> str:
    return inherited if unit == WORLD else unit


def place(spec: LayoutSpec, parent_modelview: Any, parent: Optional[Region],
          pixel: Sequence[float], root: Sequence[float]) -> tuple[np.ndarray, Region]:
    """The modelview of a layout's children, and its region

    `parent_modelview` is the modelview of the coordinates the layout's node
    is in; `parent` is the enclosing layout's region, None for an outermost
    layout, whose parent rectangle is `root`, the viewport in eye units.
    `pixel` is one pixel's width and height in eye units.
    """
    rotation, inherited_scale, translation = _decompose(parent_modelview)
    if parent is None:
        parent = Region((float(root[0]), float(root[1])))
        outermost = True
    else:
        outermost = False
    size_units = (_resolved(spec.sizeUnits[0], parent.sizeUnits[0]),
                  _resolved(spec.sizeUnits[1], parent.sizeUnits[1]))
    offset_units = (_resolved(spec.offsetUnits[0], parent.offsetUnits[0]),
                    _resolved(spec.offsetUnits[1], parent.offsetUnits[1]))
    size = [0.0, 0.0]
    shift = [0.0, 0.0]
    scale = [1.0, 1.0]
    low_edge, high_edge = ('LEFT', 'BOTTOM'), ('RIGHT', 'TOP')
    for axis in (0, 1):
        span = parent.size[axis]
        if size_units[axis] == PIXEL:
            size[axis] = spec.size[axis] * pixel[axis]
        else:
            size[axis] = spec.size[axis] * span
        if spec.align[axis] == low_edge[axis]:
            shift[axis] = -(span - size[axis]) / 2.0
        elif spec.align[axis] == high_edge[axis]:
            shift[axis] = (span - size[axis]) / 2.0
        if offset_units[axis] == PIXEL:
            shift[axis] += spec.offset[axis] * pixel[axis]
        else:
            shift[axis] += spec.offset[axis] * span
    modes = [mode for mode in spec.scaleMode]
    if outermost:
        modes = [FRACTION if mode == NONE else mode for mode in modes]
    for axis in (0, 1):
        if modes[axis] == NONE:
            scale[axis] = inherited_scale[axis]
        elif modes[axis] == FRACTION:
            scale[axis] = size[axis]
        elif modes[axis] == PIXEL:
            scale[axis] = pixel[axis]
    if modes[0] == STRETCH and modes[1] == STRETCH:
        scale[0] = scale[1] = max(size[0], size[1])
    elif modes[0] == STRETCH:
        scale[0] = scale[1]
    elif modes[1] == STRETCH:
        scale[1] = scale[0]
    placed = np.identity(4)
    placed[:3, :3] = np.diag((scale[0], scale[1], 1.0)) @ rotation
    placed[3, :3] = np.array((shift[0], shift[1], 0.0)) @ rotation + translation
    return placed, Region((size[0], size[1]), size_units, offset_units)


def screen_modelview(modelview: Any, projection: Any, pixels: Sequence[float],
                     snap: bool = True) -> np.ndarray:
    """A modelview whose unit is one pixel, its axes the screen's, at the
    origin of `modelview`

    `pixels` is the viewport's (width, height). With `snap` the origin is
    moved to the nearest whole pixel, so what is drawn there lands on the
    pixel grid.
    """
    origin = np.asarray(modelview, dtype='d')[3, :3].copy()
    step = eye_per_pixel(projection, pixels, -origin[2])
    if snap and step[0] > 0 and step[1] > 0:
        # Pixels are counted from the view's centre, where the eye's axis
        # meets it; an odd count puts the centre in the middle of one.
        for axis in (0, 1):
            half = (float(pixels[axis]) % 2.0) * 0.5
            count = origin[axis] / step[axis] - half
            origin[axis] = (round(count) + half) * step[axis]
    placed = np.identity(4)
    placed[0, 0], placed[1, 1], placed[2, 2] = step[0], step[1], step[0]
    placed[3, :3] = origin
    return placed


def local_matrix(wanted: Any, parent_modelview: Any) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """(forward, inverse): the local matrix of a node whose children are to
    be seen through `wanted`, inside coordinates seen through
    `parent_modelview`; None where either cannot be inverted"""
    wanted = np.asarray(wanted, dtype='d')
    parent = np.asarray(parent_modelview, dtype='d')
    try:
        forward = wanted @ np.linalg.inv(parent)
        inverse = parent @ np.linalg.inv(wanted)
    except np.linalg.LinAlgError:
        return None
    if not (np.all(np.isfinite(forward)) and np.all(np.isfinite(inverse))):
        return None
    return forward, inverse


class LayoutEye(NamedTuple):
    """The camera a placed node is drawn through: its world-to-eye
    ``modelview``, its ``projection`` and the ``pixels`` (width, height) of
    the rectangle it is drawn in"""

    modelview: Any
    projection: Any
    pixels: tuple[int, int]


def _enclosing(path: Any, regions: dict[int, tuple[Any, Optional[Region]]]) -> Optional[Region]:
    """The region of the nearest layout `path` passes through; None for none"""
    parent = getattr(path, 'parent', None)
    while parent is not None:
        held = regions.get(id(parent))
        if held is not None and held[0] is parent:
            return held[1]
        parent = getattr(parent, 'parent', None)
    return None


def _wanted(node: Any, parent_mv: np.ndarray, eye: LayoutEye,
            enclosing: Optional[Region]) -> tuple[np.ndarray, Optional[Region]]:
    """The modelview `node`'s children are seen through, and the region a
    layout inside it is placed in"""
    if isinstance(node, x3d.ScreenGroup):
        return screen_modelview(parent_mv, eye.projection, eye.pixels), enclosing
    if isinstance(node, x3d.LayoutGroup) and isinstance(node.viewport, x3d.X3DViewportNode):
        # The group's viewport is the rectangle its layout is placed in
        enclosing = None
    chosen = getattr(node, 'layout', None)
    if not isinstance(chosen, x3d.X3DLayoutNode):
        return parent_mv, enclosing
    depth = -float(parent_mv[3, 2])
    pixel = eye_per_pixel(eye.projection, eye.pixels, depth)
    root = view_extent(eye.projection, depth)
    return place(spec_of(chosen), parent_mv, enclosing, pixel, root)


def place_layouts(paths: Sequence[Any], eye_of: Callable[[Any], Optional[LayoutEye]]) -> int:
    """Place the node at the end of each of `paths`; how many moved

    `paths` lead to ``LayoutLayer``, ``LayoutGroup`` and ``ScreenGroup``
    nodes (:class:`OpenGLContext.scenegraph.layering.Placed`), each before
    the paths within it, as the render pass walks them. `eye_of` answers the
    :class:`LayoutEye` a path is drawn through, or None for one not drawn;
    a node not drawn keeps its placement.
    """
    from OpenGLContext.scenegraph.billboard import parent_matrix  # noqa: PLC0415 billboard imports the scenegraph
    regions: dict[int, tuple[Any, Optional[Region]]] = {}
    moved = 0
    for path in paths:
        eye = eye_of(path)
        if eye is None:
            continue
        node = path[-1]
        parent_mv = np.asarray(parent_matrix(path), dtype=np.float64) @ np.asarray(
            eye.modelview, dtype=np.float64)
        wanted, region = _wanted(node, parent_mv, eye, _enclosing(path, regions))
        # The table holds the path, so its id is not reused while it is kept
        regions[id(path)] = (path, region)  # noqa: OGC131 the entry holds the path
        local = local_matrix(wanted, parent_mv)
        if local is not None and node.place(local[0]):
            moved += 1
    return moved
