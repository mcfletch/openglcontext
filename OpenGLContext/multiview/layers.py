"""X3D's layers as a frame draws them: which, in what order, and where -- no GL

A scene with a ``LayerSet`` (ISO/IEC 19775-1, 35) is drawn as a stack of
layers. Layer 0 is the scene's own children, other than the ``LayerSet``;
layer *n* is the *n*-th node of its ``layers``. ``order`` names the layers
drawn, bottom first, and each is drawn over the one beneath with the depth
buffer cleared between them. :func:`drawn_layers` reads that into a list of
:class:`LayerPlan`, and :func:`active_number` the layer navigation drives.

A layer's ``viewport`` confines it to part of the view it is drawn in, given
in fractions of that view (:func:`clip_rect`). A ``Viewport`` among a layer's
children, and a ``LayoutGroup``'s ``viewport``, clip the children beneath them
in the same way within the layer (:func:`clip_chain`, :func:`chain_rect`).
:class:`Membership` keeps, for a frame's paths, the layer and the clipping
each one is drawn with.

Rectangles are ``(x, y, width, height)`` in window pixels from the bottom
left, as :mod:`OpenGLContext.multiview.views` counts them.
"""
from __future__ import annotations

import math
import weakref
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, NamedTuple, Optional

import numpy as np
from vrml.x3d import binding
from vrml.x3d import nodes as x3d

from OpenGLContext.multiview.views import Rect

__all__ = [
    'LayerCameras', 'LayerPart', 'LayerPlan', 'Membership', 'PathLayers', 'active_number', 'chain_rect',
    'cleared_after', 'clip_chain', 'clip_rect', 'contains', 'drawn_layers', 'intersect',
    'layer_of', 'part_of', 'sized', 'stack_parts',
]

#: X3D's ``clipBoundary``: left, right, bottom, top, as fractions.
WHOLE = (0.0, 1.0, 0.0, 1.0)


class LayerPlan(NamedTuple):
    """One layer of a frame's stack

    ``number`` is the layer's X3D number, 0 for the scene's own children;
    ``node`` is the ``Layer`` or ``LayoutLayer``, None for layer 0.
    ``pickable`` is the layer's ``pickable`` field, and ``viewport`` the
    ``Viewport`` node that confines it, or None.
    """

    number: int
    node: Any
    pickable: bool = True
    viewport: Any = None


def drawn_layers(layer_set: Any) -> list[LayerPlan]:
    """The layers `layer_set` draws, bottom first

    Each number of ``order`` once, at its first place: numbers naming no layer,
    nodes that are not layers and layers whose ``visible`` is false are left
    out.
    """
    found: list[LayerPlan] = []
    seen: set[int] = set()
    members = list(layer_set.layers or ())
    for number in np.asarray(layer_set.order, dtype=np.int64).ravel():
        number = int(number)
        if number in seen or number < 0 or number > len(members):
            continue
        seen.add(number)
        if number == 0:
            found.append(LayerPlan(0, None))
            continue
        node = members[number - 1]
        if not isinstance(node, x3d.X3DLayerNode) or not node.visible:
            continue
        viewport = node.viewport if isinstance(node.viewport, x3d.X3DViewportNode) else None
        found.append(LayerPlan(number, node, bool(node.pickable), viewport))
    return found


def active_number(layer_set: Any, drawn: Sequence[LayerPlan]) -> Optional[int]:
    """The number of the layer navigation drives: ``activeLayer`` where that
    layer is drawn, else the lowest layer drawn; None where none is"""
    if not drawn:
        return None
    named = int(layer_set.activeLayer)
    if any(plan.number == named for plan in drawn):
        return named
    return drawn[0].number


def _fraction(values: Sequence[float], index: int) -> float:
    """The clip boundary's `index`-th value held to [0, 1]; X3D's default
    where it is missing or not a number"""
    value = float(values[index]) if index < len(values) else WHOLE[index]
    if not math.isfinite(value):
        value = WHOLE[index]
    return min(max(value, 0.0), 1.0)


def clip_rect(boundary: Sequence[float], rect: Rect) -> Rect:
    """The part of `rect` a ``clipBoundary`` (left, right, bottom, top, in
    fractions of it) keeps, in whole pixels; empty where it is inside out"""
    x, y, width, height = rect
    left, right, bottom, top = (_fraction(boundary, index) for index in range(4))
    x0, x1 = math.floor(x + width * left), math.floor(x + width * right)
    y0, y1 = math.floor(y + height * bottom), math.floor(y + height * top)
    return (x0, y0, max(x1 - x0, 0), max(y1 - y0, 0))


def intersect(first: Rect, second: Rect) -> Rect:
    """The rectangle two rectangles share; empty (zero size) where none"""
    x0, y0 = max(first[0], second[0]), max(first[1], second[1])
    x1 = min(first[0] + first[2], second[0] + second[2])
    y1 = min(first[1] + first[3], second[1] + second[3])
    return (x0, y0, max(x1 - x0, 0), max(y1 - y0, 0))


def chain_rect(chain: Sequence[Any], rect: Rect) -> Rect:
    """`rect` clipped by each ``Viewport`` of `chain` in turn, outermost first"""
    for viewport in chain:
        rect = clip_rect(tuple(viewport.clipBoundary), rect)
    return rect


def layer_of(path: Sequence[Any]) -> Any:
    """The layer node `path` passes through; None for layer 0"""
    for node in path[:-1]:
        if isinstance(node, x3d.X3DLayerNode):
            return node
    return None


def clip_chain(path: Sequence[Any]) -> tuple[Any, ...]:
    """The ``Viewport`` nodes that clip the node at the end of `path`,
    outermost first: each ``Viewport`` the path passes through, and the
    ``viewport`` of each ``LayoutGroup`` it passes through"""
    found: list[Any] = []
    for node in path[:-1]:
        if isinstance(node, x3d.X3DViewportNode):
            found.append(node)
        elif isinstance(node, x3d.LayoutGroup) and isinstance(node.viewport, x3d.X3DViewportNode):
            found.append(node.viewport)
    return tuple(found)


class PathLayers:
    """Which layer, and which clipping, each of one set of paths is drawn in

    ``layers[i]`` and ``clips[i]`` are those of the *i*-th path.
    """

    def __init__(self, paths: Sequence[Sequence[Any]]) -> None:
        self.layers: list[Any] = [layer_of(path) for path in paths]
        self.clips: list[tuple[Any, ...]] = [clip_chain(path) for path in paths]
        self._masks: dict[tuple[int, tuple[int, ...]], np.ndarray] = {}

    def mask(self, layer: Any, chain: tuple[Any, ...]) -> np.ndarray:
        """Which paths are drawn in `layer` (None for layer 0) clipped by `chain`"""
        key = (id(layer), tuple(id(port) for port in chain))
        found = self._masks.get(key)
        if found is None:
            found = np.array([
                held is layer and len(clip) == len(chain)
                and all(a is b for a, b in zip(clip, chain))
                for held, clip in zip(self.layers, self.clips)], dtype=bool)
            # The paths this table was made for hold the layer and viewport
            # nodes, so the ids are not reused while it is kept.
            self._masks[key] = found  # noqa: OGC131 the paths hold the keyed nodes
        return found

    def chains(self, layer: Any) -> list[tuple[Any, ...]]:
        """The distinct clippings of `layer`'s paths, other than none, in the
        order their first paths come"""
        found: list[tuple[Any, ...]] = []
        for held, clip in zip(self.layers, self.clips):
            if held is layer and clip and not any(
                    len(clip) == len(known) and all(a is b for a, b in zip(clip, known))
                    for known in found):
                found.append(clip)
        return found


class Membership:
    """A frame's :class:`PathLayers`, kept while its paths are the same

    `generation` names the set of paths and the fields their clipping is read
    from; a table is made again when either changes.
    """

    def __init__(self) -> None:
        self._held: Optional[tuple[Any, int, int, PathLayers]] = None

    def of(self, paths: Sequence[Sequence[Any]], generation: int) -> PathLayers:
        """The table for `paths`, made again where they or `generation` differ"""
        held = self._held
        if (held is not None and held[0] is paths and held[1] == generation
                and held[2] == len(paths)):
            return held[3]
        table = PathLayers(paths)
        self._held = (paths, generation, len(paths), table)
        return table


class LayerPart(NamedTuple):
    """One rectangle a frame draws part of one layer in

    ``chain`` is the ``Viewport`` nodes that clip the paths drawn here,
    outermost first; () for the paths of the layer clipped by none.
    ``first`` marks the layer's first part, which clears the depth buffer
    and draws the layer's background; ``bottom`` marks the first part of the
    stack, which clears its rectangle whatever the layer binds.
    """

    plan: LayerPlan
    chain: tuple[Any, ...]
    rect: Rect
    first: bool
    bottom: bool


def stack_parts(drawn: Sequence[LayerPlan], table: PathLayers, rect: Rect) -> list[LayerPart]:
    """The parts a view in `rect` draws the layers `drawn` in, bottom first

    A layer's rectangle is its viewport's part of `rect`; each clipping of
    its paths (:meth:`PathLayers.chains`) is a part of that. A part with no
    pixels is left out, and a layer whose own rectangle has none with it.
    """
    found: list[LayerPart] = []
    for plan in drawn:
        own = rect if plan.viewport is None else clip_rect(tuple(plan.viewport.clipBoundary), rect)
        if own[2] <= 0 or own[3] <= 0:
            continue
        found.append(LayerPart(plan, (), own, True, not found))
        for chain in table.chains(plan.node):
            clipped = chain_rect(chain, own)
            if clipped[2] > 0 and clipped[3] > 0:
                found.append(LayerPart(plan, chain, clipped, False, False))
    return found


def contains(rect: Rect, point: Sequence[float]) -> bool:
    """Whether the window position `point` (x, y) is within `rect`"""
    x, y = float(point[0]), float(point[1])
    return rect[0] <= x < rect[0] + rect[2] and rect[1] <= y < rect[1] + rect[3]


def part_of(parts: Sequence[LayerPart], layer: Any, chain: Sequence[Any]) -> Optional[int]:
    """The index of the part of `parts` that draws the paths of `layer` (None
    for layer 0) clipped by `chain`; None where no part does"""
    for index, part in enumerate(parts):
        if (part.plan.node is layer and len(part.chain) == len(chain)
                and all(a is b for a, b in zip(part.chain, chain))):
            return index
    return None


def cleared_after(parts: Sequence[LayerPart], index: int, point: Sequence[float]) -> bool:
    """Whether a layer drawn after part `index` clears the depth buffer at `point`

    Where one does, the depth buffer at the end of the frame no longer holds
    the depth part `index` drew there.
    """
    layer = parts[index].plan.number
    return any(part.first and not part.bottom and part.plan.number != layer
               and contains(part.rect, point) for part in parts[index + 1:])


@contextmanager
def sized(camera: Any, size: Sequence[int]) -> Iterator[None]:
    """Within the block, `camera` projects for a rectangle `size` (width,
    height) pixels; its own aspect is put back as the block ends

    A camera with no ``setViewport``, or an empty size, is left as it is.
    """
    tell = getattr(camera, 'setViewport', None)
    width, height = int(size[0]), int(size[1])
    if tell is None or width <= 0 or height <= 0:
        yield
        return
    held = camera.frustum
    tell(width, height)
    try:
        yield
    finally:
        camera.frustum = held


class LayerCameras:
    """The cameras of the layers navigation does not drive -- no GL

    A layer is seen from the viewpoint its bind stack has on top
    (:func:`vrml.x3d.binding.current_path`), followed each frame as it is
    moved or rebound; where it binds none, from X3D's default viewpoint: a
    ``Viewpoint`` for a ``Layer``, an ``OrthoViewpoint`` for a
    ``LayoutLayer``. Each layer keeps one view platform; layer 0's is kept
    under None.
    """

    def __init__(self) -> None:
        self._platforms: weakref.WeakKeyDictionary[Any, Any] = weakref.WeakKeyDictionary()
        self._bottom: Any = None
        self._defaults: weakref.WeakKeyDictionary[Any, Any] = weakref.WeakKeyDictionary()

    def _platform(self, layer: Any) -> Any:
        from OpenGLContext.move.viewplatform import ViewPlatform  # noqa: PLC0415 kept with its use
        found = self._bottom if layer is None else self._platforms.get(layer)
        if found is None:
            found = ViewPlatform()
            if layer is None:
                self._bottom = found
            else:
                self._platforms[layer] = found
        return found

    def _default(self, layer: Any) -> Any:
        """X3D's default viewpoint for `layer`, made once"""
        from OpenGLContext.scenegraph.viewpoint import OrthoViewpoint, Viewpoint  # noqa: PLC0415 kept with its use
        if layer is None:
            return Viewpoint()
        found = self._defaults.get(layer)
        if found is None:
            found = self._defaults[layer] = (
                OrthoViewpoint() if isinstance(layer, x3d.LayoutLayer) else Viewpoint())
        return found

    def camera(self, layer: Any, paths: Sequence[Any]) -> Any:
        """The view platform `layer` (None for layer 0) is drawn through this
        frame; `paths` lead to the layer's viewpoints, in the order it has them"""
        platform = self._platform(layer)
        path = binding.current_path(list(paths)) if paths else None
        if path is not None:
            view = path[-1]
            view.placeOn(platform, path)
        else:
            view = self._default(layer)
            view.placeOn(platform)
        view.project(platform)
        return platform
