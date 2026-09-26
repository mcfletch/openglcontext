"""The WGL window system's Context, under the name ``VRMLContext``

Every Context has the event managers, the camera and the scene loading, so
this name is :class:`~OpenGLContext.wglcontext.WGLContext`.
"""
from OpenGLContext.wglcontext import WGLContext

VRMLContext = WGLContext

__all__ = ('VRMLContext',)
