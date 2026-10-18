"""X3D's layers, as the render pass draws them

:class:`LayeringPassMixin` is the pass's side of :mod:`OpenGLContext.multiview.layers`.
A scene with a ``LayerSet``, or with ``Viewport`` nodes clipping its
children, is drawn as a stack: each view of the frame is drawn as a
sequence of :class:`~OpenGLContext.multiview.strategy.ViewFrame`, one per
:class:`~OpenGLContext.multiview.layers.LayerPart`, bottom layer first.

- Each frame culls the walk of the scene to the paths of its layer and
  clipping (:meth:`~LayeringPassMixin.layerMask`), and is drawn into its
  rectangle through its layer's camera: the view's own for the layer
  navigation drives (``activeLayer``), a
  :class:`~OpenGLContext.multiview.layers.LayerCameras` platform bound to the
  layer's own viewpoint for the others.
- A layer's first part clears the depth buffer within its rectangle and
  draws the background its layer binds; the bottom layer clears to black
  where it binds none.
- The lights, background, fog, navigation and viewpoints a frame reads are
  its layer's (:meth:`~LayeringPassMixin.layerPaths`): a light lights its own
  layer.
- The shadow maps are made for the layer navigation drives, and only that
  layer reads them.
- A layer whose ``pickable`` is false writes no object ids, so a pick passes
  through it to the layers beneath; a pick is resolved through the layer that
  drew what it hit (:func:`~OpenGLContext.multiview.layers.resolve_pick`).
- Each frame, before the scene is walked for a view, the ``LayoutLayer``,
  ``LayoutGroup`` and ``ScreenGroup`` nodes are placed for the camera and
  rectangle they are drawn through in that view
  (:func:`~OpenGLContext.scenegraph.layout.place_layouts`); with several
  views the scene is walked again for each view they move in.

A scene with none of these draws as it would without this mixin: every
method here answers the pass's own paths and frames unchanged.
"""
from __future__ import annotations

import weakref
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Optional

import numpy as np
from OpenGL.GL import GL_FALSE, GL_TRUE, glColorMaski
from vrml.vrml97 import nodetypes
from vrml.x3d import nodes as x3dnodes

from OpenGLContext.multiview import layers
from OpenGLContext.scenegraph import billboard, layout
from OpenGLContext.scenegraph.layering import Placed

if TYPE_CHECKING:
    from OpenGLContext.multiview.strategy import ViewFrame
    from OpenGLContext.passes._flat import GatheredPaths

__all__ = ['LayeringPassMixin', 'NOTHING']

#: The layer of a view whose stack draws no layer at all: no path is in it.
NOTHING = layers.LayerPlan(-1, object())

#: The draw buffer object ids are written to (``passes._flat``).
OBJECT_ID_ATTACHMENT = 1

#: A drawing layer the frame has not named: the layer navigation drives.
_UNSET: tuple[Any, ...] = ()


class LayeringPassMixin:
    """The layer stack of a frame: its parts, cameras, culls, draws and picks"""

    if TYPE_CHECKING:
        paths: dict[type, list[Any]]
        context: Any
        _pathGeneration: int
        viewFrames: Sequence['ViewFrame']
        activeFrame: Optional['ViewFrame']
        modelView: Any
        projection: Any
        modelproj: Any
        viewPlatform: Any

        def setViewPlatform(self, vp: Any) -> None: ...
        def calculateFrustum(self) -> Any: ...
        def frameForEvent(self, event: Any) -> Optional['ViewFrame']: ...
        def applyViewFrame(self, frame: 'ViewFrame', gl: bool = True) -> None: ...

    #: Whether this frame draws a layer stack.
    layered: bool = False
    #: The layer whose lights, background and bindables are read: a
    #: one-element tuple holding the layer node (None for layer 0), or empty
    #: for the layer navigation drives.
    _drawingLayer: tuple[Any, ...] = _UNSET
    _layerCameras: Optional[layers.LayerCameras] = None
    _layerTable: Optional[layers.Membership] = None
    #: (generation, {(kind, layer): paths}) for :meth:`layerPaths`.
    _layerPathMemo: Optional[tuple[Any, dict[tuple[type, Any], list[Any]]]] = None
    #: Each layer's Billboard facing, keyed by layer; layer 0's under ``_bottomFacing``.
    _layerFacings: Optional['weakref.WeakKeyDictionary[Any, billboard.Facing]'] = None
    _bottomFacing: Optional[billboard.Facing] = None

    # -- what the scene asks for ------------------------------------------
    def layerSet(self) -> Any:
        """The scene's LayerSet, or None: the first one walked"""
        for path in self.paths.get(x3dnodes.LayerSet, ()):
            return path[-1]
        return None

    def layerStack(self) -> tuple[list[layers.LayerPlan], Optional[int]]:
        """(the layers drawn, bottom first; the number of the layer navigation drives)

        A scene without a LayerSet is layer 0 alone.
        """
        found = self.layerSet()
        if found is None:
            return [layers.LayerPlan(0, None)], 0
        drawn = layers.drawn_layers(found)
        return drawn, layers.active_number(found, drawn)

    def activeLayer(self) -> Any:
        """The layer navigation drives: its node, None for layer 0"""
        drawn, number = self.layerStack()
        for plan in drawn:
            if plan.number == number:
                return plan.node
        return None

    def drawingLayer(self) -> Any:
        """The layer the pass is drawing, or the one navigation drives between frames"""
        if self._drawingLayer:
            return self._drawingLayer[0]
        return self.activeLayer()

    def layerTable(self) -> layers.PathLayers:
        """Which layer and clipping each of the scene's rendered paths is in"""
        if self._layerTable is None:
            self._layerTable = layers.Membership()
        return self._layerTable.of(
            self.paths.setdefault(nodetypes.Rendering, []),
            (self._pathGeneration, layers.clip_generation()))

    def stacked(self) -> bool:
        """Whether the scene is drawn as a layer stack: it has a LayerSet, or
        groups clipping their children to a viewport"""
        if self.paths.get(x3dnodes.LayerSet):
            return True
        if self.paths.get(x3dnodes.X3DViewportNode):
            return True
        return any(isinstance(getattr(path[-1], 'viewport', None), x3dnodes.X3DViewportNode)
                   for path in self.paths.get(Placed, ()))

    def layerPaths(self, kind: type, layer: Any = _UNSET) -> Sequence[Any]:
        """The paths to nodes of `kind` in `layer`, by default the one being drawn

        All of the scene's where it is not drawn as a stack.
        """
        found = self.paths.get(kind, ())
        if not found or not self.paths.get(x3dnodes.LayerSet):
            return found
        if layer is _UNSET:
            layer = self.drawingLayer()
        generation = self._pathGeneration
        memo = self._layerPathMemo
        if memo is None or memo[0] != generation:
            memo = self._layerPathMemo = (generation, {})
        key = (kind, layer)
        chosen = memo[1].get(key)
        if chosen is None:
            chosen = memo[1][key] = [path for path in found if layers.layer_of(path) is layer]
        return chosen

    # -- the frames -------------------------------------------------------
    def layerCameras(self) -> layers.LayerCameras:
        """The cameras of the layers navigation does not drive"""
        if self._layerCameras is None:
            self._layerCameras = layers.LayerCameras()
        return self._layerCameras

    def stackLayers(self, frames: Sequence['ViewFrame']) -> list['ViewFrame']:
        """Each view of `frames` as the parts of its layer stack, bottom first

        `frames` is the frame's views as the layout placed them, each looking
        through its own camera. A view styled without layers
        (:class:`~OpenGLContext.multiview.views.ViewStyle`) draws the layer
        navigation drives alone. A view whose stack draws nothing is kept as one
        part of :data:`NOTHING`, which clears it. Answers `frames` unchanged for
        a scene that is not drawn as a stack.
        """
        self.layered = False
        if not self.stacked():
            return list(frames)
        drawn, active = self.layerStack()
        navigated = [plan for plan in drawn if plan.number == active]
        table = self.layerTable()
        stacked: list['ViewFrame'] = []
        for frame in frames:
            shown = drawn if frame.view.style.layers else navigated
            parts = layers.stack_parts(shown, table, frame.rect)
            if not parts:
                parts = [layers.LayerPart(NOTHING, (), frame.rect, True, True)]
            for part in parts:
                stacked.append(self._partFrame(frame, part, active))
        self.layered = True
        return stacked

    def _partFrame(self, frame: 'ViewFrame', part: layers.LayerPart,
                   active: Optional[int]) -> 'ViewFrame':
        """`frame`'s view drawing `part`, through the camera of `part`'s layer"""
        from OpenGLContext.multiview.strategy import ViewFrame  # noqa: PLC0415 strategy imports the passes
        # A view whose stack draws nothing is looked at through its own camera
        navigated = part.plan.number == active or part.plan is NOTHING
        if navigated:
            camera = frame.camera
        else:
            node = part.plan.node
            camera = self.layerCameras().camera(
                node, self.layerPaths(nodetypes.Viewpoint, node))
        with layers.sized(camera, part.rect[2:]):
            self.setViewPlatform(camera)
        found = ViewFrame(
            frame.view, camera, part.rect, self.modelView, self.projection,
            self.modelproj, self.calculateFrustum(),
            fitted=frame.fitted and navigated and not part.chain,
        )
        found.part = part
        found.navigated = navigated and not part.chain
        return found

    def layerMask(self, gathered: 'GatheredPaths', frame: Optional['ViewFrame'] = None
                  ) -> Optional[np.ndarray]:
        """Which paths of `gathered` `frame` draws, or the layer being drawn
        draws when `frame` is None; None where every path is drawn"""
        if not self.layered:
            return None
        table = self.layerTable()
        if len(table.layers) != len(gathered.paths):
            table = layers.PathLayers(gathered.paths)
        if frame is not None and frame.part is not None:
            return table.mask(frame.part.plan.node, frame.part.chain)
        return table.layer_mask(self.drawingLayer())

    def shadowFrames(self, frames: Sequence['ViewFrame']) -> list['ViewFrame']:
        """The frames the shadow maps are made for: those of the layer
        navigation drives"""
        if not self.layered:
            return list(frames)
        active = self.activeLayer()
        return [frame for frame in frames
                if frame.part is not None and frame.part.plan.node is active]

    def drawsShadows(self) -> bool:
        """Whether the layer being drawn reads the shadow maps"""
        return not self.layered or self.drawingLayer() is self.activeLayer()

    def pickable(self, frame: 'ViewFrame') -> bool:
        """Whether `frame` writes object ids: its layer's ``pickable``"""
        return frame.part is None or frame.part.plan.pickable

    def setDrawingFrame(self, frame: 'ViewFrame') -> None:
        """Read `frame`'s layer from now on (:meth:`layerPaths`)"""
        self._drawingLayer = _UNSET if frame.part is None else (frame.part.plan.node,)

    def maskObjectIds(self, masked: bool) -> None:
        """Stop, or start again, writing object ids, for a layer that is not picked"""
        value = GL_FALSE if masked else GL_TRUE
        glColorMaski(OBJECT_ID_ATTACHMENT, value, value, value, value)

    # -- before the walk --------------------------------------------------
    def placeLayouts(self, frames: Sequence['ViewFrame']) -> int:
        """Place the scene's LayoutLayer, LayoutGroup and ScreenGroup nodes for
        the view of the first of `frames`; how many moved

        The pass places them once for each view before culling that view's
        frames (``MultiviewPassMixin.prepareViews``).
        """
        paths = self.paths.get(Placed, ())
        if not paths or not frames:
            return 0
        view = frames[0].view
        mine = [frame for frame in frames if frame.view is view]

        def eye_of(path: Any) -> Optional[layout.LayoutEye]:
            frame = self._frameDrawing(mine, path)
            if frame is None:
                return None
            return layout.LayoutEye(frame.modelView, frame.projection,
                                    (int(frame.rect[2]), int(frame.rect[3])))

        return layout.place_layouts(paths, eye_of)

    def _frameDrawing(self, frames: Sequence['ViewFrame'], path: Any) -> Optional['ViewFrame']:
        """The frame of `frames` a placed node at the end of `path` is drawn in

        A LayoutGroup with a viewport is placed in the part that viewport
        clips. Where the frame is not a stack, the navigated frame.
        """
        if not self.layered:
            return next((frame for frame in frames if frame.navigated), frames[0])
        node = path[-1]
        chain = layers.clip_chain(path)
        if isinstance(node, x3dnodes.LayoutGroup) and isinstance(
                node.viewport, x3dnodes.X3DViewportNode):
            chain = chain + (node.viewport,)
        # A LayoutLayer is placed in its own layer
        layer = node if isinstance(node, x3dnodes.X3DLayerNode) else layers.layer_of(path)
        index = layers.part_of([frame.part for frame in frames], layer, chain)
        return None if index is None else frames[index]

    def faceLayerBillboards(self, frames: Sequence['ViewFrame']) -> None:
        """Turn each layer's Billboards toward the camera of its first frame"""
        paths = self.paths.get(billboard.Billboard, ())
        if not paths or not frames:
            return
        cameras: dict[Any, Any] = {}
        for frame in frames:
            cameras.setdefault(frame.part.plan.node if frame.part is not None else None,
                               frame.modelView)
        grouped: dict[Any, list[Any]] = {}
        for path in paths:
            grouped.setdefault(layers.layer_of(path), []).append(path)
        for node, members in grouped.items():
            modelview = cameras.get(node)
            if modelview is None:
                continue
            self._facingOf(node).face(members, modelview)

    def _facingOf(self, layer: Any) -> billboard.Facing:
        """What turns the Billboards of `layer` (None for layer 0)"""
        if layer is None:
            if self._bottomFacing is None:
                self._bottomFacing = billboard.Facing()
            return self._bottomFacing
        if self._layerFacings is None:
            self._layerFacings = weakref.WeakKeyDictionary()
        found = self._layerFacings.get(layer)
        if found is None:
            found = self._layerFacings[layer] = billboard.Facing()
        return found

    # -- picking ----------------------------------------------------------
    def layerPickResolver(self, event: Any) -> Optional[Callable[..., tuple[float, tuple[Any, Any, Any], Any]]]:
        """How a pick of `event` is resolved through the layers of its view

        A callable of (path, x, y, depth) answering (depth, (modelview,
        projection, rect), layer node), made from the frames as they are now;
        None where the frame is not a stack.
        """
        if not self.layered:
            return None
        chosen = self.frameForEvent(event)
        if chosen is None:
            return None
        mine = [frame for frame in self.viewFrames if frame.view is chosen.view]
        picked = [layers.PickedPart(frame.part, frame.modelView, frame.projection, frame.rect)
                  for frame in mine if frame.part is not None]
        if len(picked) != len(mine):
            return None
        navigated = next((index for index, frame in enumerate(mine) if frame is chosen), 0)

        def resolve(path: Any, x: float, y: float, depth: float
                    ) -> tuple[float, tuple[Any, Any, Any], Any]:
            index, found = layers.resolve_pick(picked, navigated, path, (x, y), depth)
            part = picked[index]
            return found, (part.modelview, part.projection, part.rect), part.part.plan.node

        return resolve
