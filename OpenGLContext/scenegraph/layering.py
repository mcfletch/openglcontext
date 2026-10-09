"""X3D's Layering and Layout nodes: a scene drawn as a stack of layers, and
children placed on the screen

- :class:`LayerSet` - the stack: its `layers`, the `order` they are drawn in
  and the `activeLayer` navigation drives (ISO/IEC 19775-1, 35).
- :class:`Layer` - one layer's children, drawn over the layers beneath it
  with the depth buffer cleared, through its own viewpoint, within its
  `viewport`.
- :class:`LayoutLayer` - a layer whose children are placed by its `layout`.
- :class:`Viewport` - a group whose children are drawn within `clipBoundary`,
  fractions of the rectangle the group is drawn in.
- :class:`LayoutGroup` - a group placed by its `layout` within its parent's
  rectangle, or its `viewport` (36).
- :class:`ScreenGroup` - a group whose unit is one pixel, its axes the
  screen's, at its origin (36).

The render pass draws the stack (:mod:`OpenGLContext.passes.layerpass`) and
works out each frame where the Layout nodes put their children
(:mod:`OpenGLContext.scenegraph.layout`), setting each :class:`Placed`
node's ``placement``. Paths through a placed node read that matrix, so their
cached matrices are worked out again only when a placement changes.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from vrml import field
from vrml.vrml97 import nodetypes
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import grouping
from OpenGLContext.scenegraph.framed import Framed

__all__ = ['Layer', 'LayerSet', 'LayoutGroup', 'LayoutLayer', 'Placed', 'ScreenGroup',
           'Viewport']

#: Two placements this close in every element are the same placement.
SAME = 1e-9


class LayerSet(nodetypes.Children, x3d.LayerSet):
    """X3D's LayerSet: the scene's layers, drawn in `order` over its other children

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/layering.html#LayerSet
    """

    def renderedChildren(self, types: Any = None) -> list[Any]:
        """Its layers; anything else in `layers` is not drawn"""
        return [layer for layer in self.layers or () if isinstance(layer, x3d.X3DLayerNode)]


class Layer(grouping.Grouping, x3d.Layer):
    """X3D's Layer: children drawn through the layer's own viewpoint

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/layering.html#Layer
    """


class Placed(Framed):
    """A group drawn in the matrix the render pass last placed it with

    ``placement`` is not one of the node's X3D fields: the pass sets it
    (:meth:`place`) from the node's layout, its parent's coordinates and the
    camera.
    """

    placement = field.newField(' placement', 'SFMatrix4d', 0, np.identity(4))
    MATRIX_FIELDS = ('placement',)
    FRAME_KEY = 'layout-placement'

    def frameMatrix(self) -> np.ndarray:
        return np.asarray(self.placement, dtype=np.float64).reshape(4, 4)

    def place(self, matrix: Any) -> bool:
        """Draw the children in `matrix` from now on; whether that changed anything

        A matrix that cannot be inverted, or that is not finite, is not taken.
        """
        matrix = np.asarray(matrix, dtype=np.float64).reshape(4, 4)
        if not np.all(np.isfinite(matrix)) or abs(np.linalg.det(matrix)) < 1e-30:
            return False
        if np.allclose(matrix, self.frameMatrix(), rtol=0.0, atol=SAME):
            return False
        self.placement = matrix
        return True


class LayoutLayer(Placed, x3d.LayoutLayer):
    """X3D's LayoutLayer: a layer whose children are placed by its `layout`

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/layout.html#LayoutLayer
    """


class LayoutGroup(Placed, x3d.LayoutGroup):
    """X3D's LayoutGroup: children placed by its `layout` within its parent's
    rectangle, or its `viewport`

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/layout.html#LayoutGroup
    """


class ScreenGroup(Placed, x3d.ScreenGroup):
    """X3D's ScreenGroup: children measured in pixels, facing the screen

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/layout.html#ScreenGroup
    """


class Viewport(grouping.Grouping, x3d.Viewport):
    """X3D's Viewport: children drawn within `clipBoundary` of the rectangle
    the group is drawn in

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/layering.html#Viewport
    """
