"""The wx window system's Context, under the name ``VRMLContext``

Every Context has the event managers, the camera and the scene loading, so
this name is :class:`~OpenGLContext.wxcontext.wxContext`.
"""
from OpenGLContext.wxcontext import wxContext

VRMLContext = wxContext

__all__ = ('VRMLContext',)
