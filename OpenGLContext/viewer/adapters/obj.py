"""Opening a Wavefront OBJ model (``.obj``).

OBJ is geometry and materials and nothing else -- no cameras, no lights, no sky
-- so a viewer supplies all three and frames the model itself.  Reading it is
:class:`~OpenGLContext.viewer.adapters.scenegraph.SceneGraphAdapter`'s job; what
is specific to the format is that it describes an *object*.
"""
from OpenGLContext.viewer.adapters.scenegraph import SceneGraphAdapter

__all__ = ['OBJAdapter']


class OBJAdapter(SceneGraphAdapter):
    """A Wavefront OBJ: one object, in coordinates of its own choosing."""

    name = 'obj'

    #: An OBJ's origin is wherever the modeller left it -- often far from the
    #: geometry -- so a viewer is free to move it to the middle of the frame.
    recentres = True
