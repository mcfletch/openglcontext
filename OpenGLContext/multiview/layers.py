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
    'LayerCameras', 'LayerPart', 'LayerPlan', 'Membership', 'PathLayers', 'PickedPart',
    'active_number', 'chain_rect', 'cleared_after', 'clip_chain', 'clip_generation', 'clip_rect',
    'contains',
    'drawn_layers', 'intersect', 'layer_of', 'part_of', 'resolve_pick', 'sized', 'stack_parts',
    'surface_depth',
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


_clip_changes = 0


def clip_generation() -> int:
    """A count that moves whenever a ``LayoutGroup``'s ``viewport`` is set

    The paths of a scene and this count together decide which clipping each
    path is drawn with (:func:`clip_chain`).
    """
    return _clip_changes


def _clipping_changed(*_args: Any, **_named: Any) -> None:
    global _clip_changes
    _clip_changes += 1


def _watch_clipping() -> None:
    from pydispatch import dispatcher  # noqa: PLC0415 kept with its use
    dispatcher.connect(_clipping_changed, signal=('set', x3d.LayoutGroup.viewport), weak=False)


_watch_clipping()


class PathLayers:
    """Which layer, and which clipping, each of one set of paths is drawn in

    ``layers[i]`` and ``clips[i]`` are those of the *i*-th path. The masks
    and clippings asked for are kept with the table, keyed by the nodes
    themselves, which the paths hold.
    """

    def __init__(self, paths: Sequence[Sequence[Any]]) -> None:
        self.layers: list[Any] = [layer_of(path) for path in paths]
        self.clips: list[tuple[Any, ...]] = [clip_chain(path) for path in paths]
        self._masks: dict[tuple[Any, tuple[Any, ...]], np.ndarray] = {}
        self._layerMasks: dict[Any, np.ndarray] = {}
        self._chains: dict[Any, list[tuple[Any, ...]]] = {}

    def mask(self, layer: Any, chain: tuple[Any, ...]) -> np.ndarray:
        """Which paths are drawn in `layer` (None for layer 0) clipped by `chain`"""
        key = (layer, tuple(chain))
        found = self._masks.get(key)
        if found is None:
            found = self._masks[key] = np.array([
                held is layer and len(clip) == len(chain)
                and all(a is b for a, b in zip(clip, chain))
                for held, clip in zip(self.layers, self.clips)], dtype=bool)
        return found

    def layer_mask(self, layer: Any) -> np.ndarray:
        """Which paths are drawn in `layer` (None for layer 0), however clipped"""
        found = self._layerMasks.get(layer)
        if found is None:
            found = self._layerMasks[layer] = np.array(
                [held is layer for held in self.layers], dtype=bool)
        return found

    def chains(self, layer: Any) -> list[tuple[Any, ...]]:
        """The distinct clippings of `layer`'s paths, other than none, in the
        order their first paths come"""
        found = self._chains.get(layer)
        if found is None:
            found = self._chains[layer] = []
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
        self._held: Optional[tuple[Any, Any, int, PathLayers]] = None

    def of(self, paths: Sequence[Sequence[Any]], generation: Any) -> PathLayers:
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


#: A window depth in front of the camera whatever its far plane
#: (:data:`OpenGLContext.scenegraph.x3dpointing.AHEAD`).
AHEAD = 0.5


class PickedPart(NamedTuple):
    """One part of a view as a pick made in it is resolved: the part, and the
    camera it was drawn through (row-vector ``modelview`` and
    ``projection``, and the ``rect`` it was drawn in)"""

    part: LayerPart
    modelview: Any
    projection: Any
    rect: Rect


def _window_to_world(modelview: Any, projection: Any, rect: Rect,
                     point: Sequence[float], depth: float) -> Optional[np.ndarray]:
    """The world point at window position `point` and window depth `depth`"""
    x, y, width, height = (float(value) for value in rect)
    device = np.array((2.0 * (float(point[0]) - x) / max(width, 1.0) - 1.0,
                       2.0 * (float(point[1]) - y) / max(height, 1.0) - 1.0,
                       2.0 * depth - 1.0, 1.0))
    try:
        inverse = np.linalg.inv(np.asarray(modelview, np.float64) @ np.asarray(projection, np.float64))
    except np.linalg.LinAlgError:
        return None
    found = device @ inverse
    if abs(found[3]) < 1e-300:
        return None
    return np.asarray(found[:3] / found[3])


def surface_depth(path: Any, modelview: Any, projection: Any, rect: Rect,
                  point: Sequence[float]) -> Optional[float]:
    """The window depth of the shape at the end of `path` under `point`

    The pointer's ray through `point` is crossed with the shape's triangles
    (:func:`OpenGLContext.scenegraph.meshdata.geometry_arrays`), and the
    nearest crossing's depth answered. A shape with no triangles, or one the
    ray misses, is measured at its origin. None where the camera or the
    shape's matrix cannot be inverted.
    """
    from OpenGLContext.scenegraph import meshdata, pickgeometry  # noqa: PLC0415 kept with its use
    world = np.asarray(path.transformMatrix(), np.float64)
    # Depth 1 may be behind the camera (the pass trims its projection with a
    # far plane there); the near plane and AHEAD are both in front.
    start = _window_to_world(modelview, projection, rect, point, 0.0)
    ahead = _window_to_world(modelview, projection, rect, point, AHEAD)
    try:
        local = np.linalg.inv(world)
    except np.linalg.LinAlgError:
        return None
    if start is None or ahead is None:
        return None
    hit = np.zeros(3)
    found = meshdata.geometry_arrays(getattr(path[-1], 'geometry', None))
    if found is not None:
        positions = np.asarray(found.attributes['POSITION'], np.float64).reshape(-1, 3)
        corners = (np.arange((len(positions) // 3) * 3) if found.indices is None
                   else np.asarray(found.indices, np.intp).ravel())
        begin, toward = (_homogeneous(np.append(each, 1.0) @ local) for each in (start, ahead))
        bearing = toward - begin
        length = float(np.linalg.norm(bearing))
        if len(corners) and length > 0:
            # Far enough along the ray to pass every triangle
            reach = float(np.linalg.norm(begin)) + float(np.abs(positions).max()) * 2.0 + 1.0
            end = begin + bearing * (reach / length)
            crossings = pickgeometry.segment_triangles(
                begin, end, positions[corners].reshape(-1, 3, 3))
            if len(crossings.t):
                hit = begin + float(crossings.t.min()) * (end - begin)
    clip = (np.append(hit, 1.0) @ world @ np.asarray(modelview, np.float64)
            @ np.asarray(projection, np.float64))
    if abs(clip[3]) < 1e-300:
        return None
    return float(min(max((clip[2] / clip[3] + 1.0) / 2.0, 0.0), 1.0))


def _homogeneous(point: np.ndarray) -> np.ndarray:
    return np.asarray(point[:3] / point[3])


def resolve_pick(views: Sequence[PickedPart], navigated: int, path: Sequence[Any],
                 point: Sequence[float], depth: float) -> tuple[int, float]:
    """(index of the part of `views` a pick is resolved through, its depth)

    A pick that hit nothing, or hit a path no part draws, is resolved through
    `navigated`, the part navigation drives, with the depth read. A hit is
    resolved through the part that drew the path; where a layer drawn after
    it cleared the depth buffer at `point`, the depth is measured on the
    shape (:func:`surface_depth`).
    """
    if not path:
        return navigated, depth
    parts = [view.part for view in views]
    index = part_of(parts, layer_of(path), clip_chain(path))
    if index is None:
        return navigated, depth
    if cleared_after(parts, index, point):
        view = views[index]
        found = surface_depth(path, view.modelview, view.projection, view.rect, point)
        if found is not None:
            depth = found
    return index, depth
