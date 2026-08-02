"""Opening a VRML97 world (``.wrl`` / ``.wrz`` / ``.vrml`` / ``.wrl.gz``).

A VRML file is a *world*, not a model: it is authored complete, with its own
sky, its own lights and its own viewpoints, in coordinates where the ground is
at y=0 and standing at the origin means something.  Everything else about
reading it is what every scenegraph format needs, and lives in
:class:`~OpenGLContext.viewer.adapters.scenegraph.SceneGraphAdapter`.

Opened this way a world gets everything the viewer offers a glTF: framing,
loading in the background, camera cycling, the caption, screenshots, the settled
capture and walking with gravity.
"""
from OpenGLContext.viewer.adapters.scenegraph import SceneGraphAdapter

__all__ = ['VRMLAdapter']


class VRMLAdapter(SceneGraphAdapter):
    """A VRML97 world: authored complete, in coordinates that mean something."""

    name = 'vrml97'

    #: Never re-centred.  A world's ground plane is at y=0 and its viewpoints
    #: are in its own space; moving it would put both somewhere else.
    recentres = False
