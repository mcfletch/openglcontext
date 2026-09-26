"""The GLUT window system's Context, under the name ``GLUTInteractiveContext``

Every Context has the event managers, the camera and the scene loading, so
this name is :class:`~OpenGLContext.glutcontext.GLUTContext`.
"""
from OpenGLContext.glutcontext import GLUTContext

GLUTInteractiveContext = GLUTContext

__all__ = ('GLUTInteractiveContext',)
