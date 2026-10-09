"""X3D's grouping nodes that draw their children as a Group does

CADAssembly and CADLayer group the parts of a CAD model and CADFace holds one
of its faces (ISO/IEC 19775-1, 32), PickableGroup the geometry a picking
sensor may test (38), and StaticGroup children that do not change (10).
Their other fields are carried and not used in drawing.
"""
from typing import Any

from pydispatch import dispatcher
from vrml.vrml97 import nodetypes
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import boundingvolume, grouping
from OpenGLContext.scenegraph.switch import CHILDREN_CHANGE_SIGNAL

__all__ = ['CADAssembly', 'CADFace', 'CADLayer', 'PickableGroup', 'StaticGroup']


class CADAssembly(grouping.Grouping, x3d.CADAssembly):
    """X3D's CADAssembly, drawn as a group"""


class CADLayer(grouping.Grouping, x3d.CADLayer):
    """X3D's CADLayer, drawn as a group"""


class PickableGroup(grouping.Grouping, x3d.PickableGroup):
    """X3D's PickableGroup, drawn as a group"""


class StaticGroup(grouping.Grouping, x3d.StaticGroup):
    """X3D's StaticGroup, drawn as a group"""


class CADFace(x3d.CADFace):
    """X3D's CADFace: a face of a CAD part, drawn as its `shape`

    Setting `shape` sends
    :data:`~OpenGLContext.scenegraph.switch.CHILDREN_CHANGE_SIGNAL`, so the
    render pass walks the new shape.
    """

    def __init__(self, *args: Any, **named: Any) -> None:
        super().__init__(*args, **named)
        dispatcher.connect(self._onShapeChange, signal=('set', type(self).shape), sender=self)

    def _onShapeChange(self, value: Any = None) -> None:
        dispatcher.send(signal=CHILDREN_CHANGE_SIGNAL, sender=self)

    def renderedChildren(self, types: Any = (nodetypes.Children, nodetypes.Rendering)) -> list:
        """The shape, or nothing where there is none"""
        shape = self.shape
        return [shape] if shape and grouping.of_types(shape, types) else []

    def boundingVolume(self, mode: Any = None) -> Any:
        """The shape's bounds; unbounded where it has none"""
        current = boundingvolume.getCachedVolume(self)
        if current is not None:
            return current
        dependencies: list = [(self, 'shape')]
        shape = self.shape
        try:
            if not shape or not hasattr(shape, 'boundingVolume'):
                raise boundingvolume.UnboundedObject(self)
            volume = shape.boundingVolume(mode)
            dependencies.append((volume, None))
        except boundingvolume.UnboundedObject:
            volume = boundingvolume.UnboundedVolume()
        return boundingvolume.cacheVolume(self, volume, dependencies)
