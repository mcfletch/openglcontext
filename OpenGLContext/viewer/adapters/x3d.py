"""Opening an X3D world (``.x3d``, ``.x3dv``, ``.x3dj`` and their compressed forms).

An X3D document is a world as a VRML97 one is: authored complete, with its own
lights and viewpoints, in coordinates that mean something.
:class:`~OpenGLContext.viewer.adapters.scenegraph.SceneGraphAdapter` does the
reading and presenting; the document's ``head`` metadata is a notice beside
those of its ``WorldInfo`` nodes.
"""
from typing import Any

from OpenGLContext.loaders.notices import Notice
from OpenGLContext.viewer.adapters.base import ViewerScene
from OpenGLContext.viewer.adapters.scenegraph import SceneGraphAdapter

__all__ = ['X3DAdapter', 'head_notice']

#: Which ``meta`` name fills each part of a notice; the first one present wins.
META_NOTICE = {
    'title': ('title',),
    'creator': ('creator', 'author'),
    'copyright': ('rights', 'copyright'),
    'licence': ('license', 'licence'),
    'source': ('reference', 'identifier'),
}


def head_notice(scene: Any) -> Notice:
    """The notice an X3D document's ``meta`` statements state"""
    found: "dict[str, str]" = {}
    for item in getattr(scene, 'meta', ()):
        name = str(item.name).strip().lower()
        content = str(item.content).strip()
        if content and name not in found:
            found[name] = content
    return Notice(**{part: next((found[name] for name in names if name in found), '')
                     for part, names in META_NOTICE.items()})


class X3DAdapter(SceneGraphAdapter):
    """An X3D world, read in any of its encodings"""

    name = 'x3d'

    #: Never re-centred: the world's viewpoints are in its own space.
    recentres = False

    def sceneFrom(self, sceneGraph: Any) -> ViewerScene:
        """The world as :class:`SceneGraphAdapter` presents it, with its head's notice first"""
        presented = super().sceneFrom(sceneGraph)
        notice = head_notice(sceneGraph)
        if notice:
            presented.notices = [notice] + list(presented.notices)
        return presented
