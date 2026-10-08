"""X3D documents read into the engine's scenegraph

`.x3d` and `.x3dz` (XML), `.x3dv` and `.x3dvz` (ClassicVRML), `.x3dj`
(JSON) and `.x3db` (the compressed binary encoding) are read by `vrml.x3d`, which builds each node from the engine's class
for it where the engine implements the X3D node (:func:`prototypes`) and from
the X3D declaration otherwise. The scene is an
:class:`~OpenGLContext.scenegraph.scenegraph.X3DScene`, so a context draws it
as it draws a VRML97 world. What the read found wrong is in the scene's
`problems` and in the log, once per problem, at its severity.
"""
import logging
from typing import Any, ClassVar

from vrml import x3d as vrml_x3d
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders import base

log = logging.getLogger(__name__)

__all__ = ['X3DHandler', 'defaultHandler', 'prototypes']

#: X3D nodes whose name the engine's registry gives to another class (the
#: VRML97 NURBS extension's `Polyline2D`, `NurbsCurve`, `NurbsCurve2D` and
#: `Contour2D`), by name: (module, class).
X3D_ONLY = {
    'Polyline2D': ('OpenGLContext.scenegraph.geometry2d', 'Polyline2D'),
    'NurbsCurve': ('OpenGLContext.scenegraph.nurbsx3d', 'NurbsCurve'),
    'NurbsCurve2D': ('OpenGLContext.scenegraph.nurbsx3d', 'NurbsCurve2D'),
    'Contour2D': ('OpenGLContext.scenegraph.nurbsx3d', 'Contour2D'),
}

#: How each problem's severity is logged.
_LEVELS = {'error': logging.ERROR, 'warning': logging.WARNING, 'info': logging.INFO}


def prototypes() -> "dict[str, type]":
    """The engine's node classes by X3D name, for each X3D node it implements

    A registered class counts when it derives from the X3D declaration of its
    name; the others (a node of the same name with other fields) are left to
    the declaration, or to the class :data:`X3D_ONLY` names. `X3DScene` is
    the engine's scene class.
    """
    import importlib  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import basenodes  # noqa: PLC0415 the registry fills at first import
    from OpenGLContext.scenegraph.scenegraph import X3DScene  # noqa: PLC0415 beside the registry
    found: "dict[str, type]" = {}
    for name, cls in basenodes.PROTOTYPES.items():
        declared = x3d.CONCRETE_NODES.get(name)
        if declared is not None and isinstance(cls, type) and issubclass(cls, declared):
            found[name] = cls
    for name, (module, attribute) in X3D_ONLY.items():
        found[name] = getattr(importlib.import_module(module), attribute)
    found['X3DScene'] = X3DScene
    return found


class X3DHandler(base.BaseHandler):
    """Reads an X3D document of any encoding into the engine's nodes"""

    def vocabulary(self) -> "dict[str, type]":
        """The node classes the document is built from, by name"""
        return prototypes()

    def parse(self, data: Any, baseURL: str, *args: Any, **named: Any) -> "tuple[bool, Any]":
        """The scene the document builds; raises ValueError for one that cannot be read"""
        try:
            scene = vrml_x3d.loads(data, name=baseURL or '', prototypes=self.vocabulary())
        except (ValueError, SyntaxError) as err:
            raise ValueError('%s is not a readable X3D document: %s' % (baseURL, err)) from err
        for problem in scene.problems:
            log.log(_LEVELS.get(str(problem.severity), logging.WARNING), '%s: %s',
                    baseURL, problem)
        return True, scene


def defaultHandler() -> X3DHandler:
    """The handler `plugins.Loader` registers for the X3D suffixes"""
    return X3DHandler()
