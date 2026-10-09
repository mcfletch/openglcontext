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
import os
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Optional

from vrml import node
from vrml import x3d as vrml_x3d
from vrml.x3d import files, readers
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders import base
from OpenGLContext.loaders.resolver import Resolver, is_url

log = logging.getLogger(__name__)

__all__ = ['ContainedPrototypes', 'X3DHandler', 'defaultHandler', 'prototypes']

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


class ContainedPrototypes:
    """Reads the files a document's EXTERNPROTO URLs name, as the document's other references are read

    A document read from a file reads prototypes from files under its own
    folder (or a content root); one read from a URL, from its own origin
    (:class:`~OpenGLContext.loaders.resolver.Resolver`). Each file is read
    once per load, and a file naming prototypes in others is read the same
    way, to :data:`vrml.x3d.files.MAX_PROTOTYPE_DEPTH` files deep. A URL the
    policy refuses, or a file that cannot be read, is logged and the next URL
    is tried.
    """

    def __init__(self, prototypes: Mapping[str, type], depth: int = 0,
                 scenes: Optional[dict[str, Any]] = None) -> None:
        self.prototypes = prototypes
        self.depth = depth
        self.scenes: dict[str, Any] = {} if scenes is None else scenes

    def __call__(self, urls: Sequence[str], baseURL: str, name: str) -> Optional[type]:
        if self.depth >= files.MAX_PROTOTYPE_DEPTH or not baseURL:
            return None
        resolver = (Resolver(base_url=baseURL) if is_url(baseURL)
                    else Resolver(base_dir=os.path.dirname(os.path.abspath(baseURL))))
        for url in urls:
            reference, _, fragment = str(url).partition('#')
            if not reference:
                continue
            scene = self._scene(resolver, reference, baseURL)
            if scene is None:
                continue
            found = scene.getProto(fragment or name)
            if found is not None and found not in node.PENDING_PROTOTYPES:
                return found  # type: ignore[no-any-return]  # a prototype class the scene declared
        return None

    def _scene(self, resolver: Resolver, reference: str, baseURL: str) -> Any:
        try:
            location = str(resolver.resolve(reference))
        except IOError as err:
            log.warning('%s: EXTERNPROTO %s is not read: %s', baseURL, reference, err)
            return None
        if location not in self.scenes:
            self.scenes[location] = None
            try:
                data = resolver.fetch(reference)
            except (IOError, ValueError) as err:
                log.warning('%s: EXTERNPROTO %s is not read: %s', baseURL, reference, err)
                return None
            self.scenes[location] = readers.read(
                data, name=location, prototypes=self.prototypes,
                extern_resolver=ContainedPrototypes(self.prototypes, self.depth + 1, self.scenes))
        return self.scenes[location]


class X3DHandler(base.BaseHandler):
    """Reads an X3D document of any encoding into the engine's nodes"""

    def vocabulary(self) -> "dict[str, type]":
        """The node classes the document is built from, by name"""
        return prototypes()

    def parse(self, data: Any, baseURL: str, *args: Any, **named: Any) -> "tuple[bool, Any]":
        """The scene the document builds; raises ValueError for one that cannot be read"""
        try:
            vocabulary = self.vocabulary()
            scene = vrml_x3d.loads(data, name=baseURL or '', prototypes=vocabulary,
                                   extern_resolver=ContainedPrototypes(vocabulary))
        except (ValueError, SyntaxError) as err:
            raise ValueError('%s is not a readable X3D document: %s' % (baseURL, err)) from err
        for problem in scene.problems:
            log.log(_LEVELS.get(str(problem.severity), logging.WARNING), '%s: %s',
                    baseURL, problem)
        return True, scene


def defaultHandler() -> X3DHandler:
    """The handler `plugins.Loader` registers for the X3D suffixes"""
    return X3DHandler()
