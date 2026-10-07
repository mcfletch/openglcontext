"""X3D's grouping nodes that draw their children as a Group does

CADAssembly and CADLayer group the parts of a CAD model (ISO/IEC 19775-1,
32), PickableGroup the geometry a picking sensor may test (38). Their other
fields are carried and not used in drawing.
"""
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import grouping

__all__ = ['CADAssembly', 'CADLayer', 'PickableGroup']


class CADAssembly(grouping.Grouping, x3d.CADAssembly):
    """X3D's CADAssembly, drawn as a group"""


class CADLayer(grouping.Grouping, x3d.CADLayer):
    """X3D's CADLayer, drawn as a group"""


class PickableGroup(grouping.Grouping, x3d.PickableGroup):
    """X3D's PickableGroup, drawn as a group"""
