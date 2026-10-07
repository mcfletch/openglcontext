"""X3D documents read into the engine's scenegraph

`.x3d` and `.x3dz` (XML), `.x3dv` and `.x3dvz` (ClassicVRML) and `.x3dj`
(JSON) are read by `vrml.x3d`, which builds each node from the engine's class
for it where the engine implements the X3D node (:func:`prototypes`) and from
the X3D declaration otherwise. The scene is an
:class:`~OpenGLContext.scenegraph.scenegraph.X3DScene`, so a context draws it
as it draws a VRML97 world. What the read found wrong is in the scene's
`problems` and in the log, once per problem, at its severity.
"""
import logging
from typing import Any

from vrml import x3d as vrml_x3d
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders import base

log = logging.getLogger(__name__)

__all__ = ['X3DHandler', 'defaultHandler', 'prototypes']

#: How each problem's severity is logged.
_LEVELS = {'error': logging.ERROR, 'warning': logging.WARNING, 'info': logging.INFO}


def prototypes() -> "dict[str, type]":
    """The engine's node classes by X3D name, for each X3D node it implements

    A registered class counts when it derives from the X3D declaration of its
    name; the others (a node of the same name with other fields) are left to
    the declaration. `X3DScene` is the engine's scene class.
    """
    from OpenGLContext.scenegraph import basenodes  # noqa: PLC0415 the registry fills at first import
    from OpenGLContext.scenegraph.scenegraph import X3DScene  # noqa: PLC0415 beside the registry
    found: "dict[str, type]" = {}
    for name, cls in basenodes.PROTOTYPES.items():
        declared = x3d.CONCRETE_NODES.get(name)
        if declared is not None and isinstance(cls, type) and issubclass(cls, declared):
            found[name] = cls
    found['X3DScene'] = X3DScene
    return found


class X3DHandler(base.BaseHandler):
    """Reads an X3D document of any encoding into the engine's nodes"""

    filename_extensions = ('.x3d', '.x3dz', '.x3dv', '.x3dvz', '.x3dj')

    def parse(self, data: Any, baseURL: str, *args: Any, **named: Any) -> "tuple[bool, Any]":
        """The scene the document builds; raises ValueError for one that cannot be read"""
        try:
            scene = vrml_x3d.loads(data, name=baseURL or '', prototypes=prototypes())
        except (ValueError, SyntaxError) as err:
            raise ValueError('%s is not a readable X3D document: %s' % (baseURL, err)) from err
        for problem in scene.problems:
            log.log(_LEVELS.get(str(problem.severity), logging.WARNING), '%s: %s',
                    baseURL, problem)
        return True, scene


def defaultHandler() -> X3DHandler:
    """The handler `plugins.Loader` registers for the X3D suffixes"""
    return X3DHandler()
