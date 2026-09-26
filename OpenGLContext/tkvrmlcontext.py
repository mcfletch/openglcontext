"""The Tk window system's Context, under the name ``VRMLContext``

Every Context has the event managers, the camera and the scene loading, so
this name is :class:`~OpenGLContext.tkcontext.TkContext`.
"""
from OpenGLContext.tkcontext import TkContext

VRMLContext = TkContext

__all__ = ('VRMLContext',)
