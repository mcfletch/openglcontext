"""The GLUT window system's Context, under the name ``VRMLContext``

Every Context has the event managers, the camera and the scene loading, so
this name is :class:`~OpenGLContext.glutcontext.GLUTContext`.
"""
from OpenGLContext.glutcontext import GLUTContext

VRMLContext = GLUTContext

__all__ = ('VRMLContext',)
