"""The EGL window system's Context, under the name ``VRMLContext``

Every Context has the event managers, the camera and the scene loading, so
this name is :class:`~OpenGLContext.eglcontext.EGLContext`.
"""
from OpenGLContext.eglcontext import EGLContext

VRMLContext = EGLContext

__all__ = ('VRMLContext',)
