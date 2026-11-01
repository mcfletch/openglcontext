"""GLUT context with a pop-up menu of worlds to load

The middle button opens a menu of the VRML97 worlds in ``wrls`` and the URLs
of ``resources/test_vrml_set.txt``, from the working directory, as the
engine's suite runs from ``tests/``; see
:meth:`OpenGLContext.windowsystem.glut.GLUTWindowSystem.createWorldMenu`.
"""
from OpenGLContext.glutcontext import GLUTContext


class VRMLContext(GLUTContext):
    """A GLUT context whose main loop starts with the world menu attached"""

    glutWorldMenu = True
    glutWorlds = 'wrls'
    glutWorldURLs = 'resources/test_vrml_set.txt'


BaseContext = VRMLContext
