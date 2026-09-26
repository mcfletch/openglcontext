"""GLUT context with a pop-up menu of worlds to load

The middle button opens a menu of the VRML97 worlds under
``OpenGLContext/tests/wrls`` and the URLs of the test set; see
:meth:`OpenGLContext.windowsystem.glut.GLUTWindowSystem.createWorldMenu`.
"""
from OpenGLContext.glutcontext import GLUTContext


class VRMLContext(GLUTContext):
    """A GLUT context whose main loop starts with the world menu attached"""

    glutWorldMenu = True


BaseContext = VRMLContext
