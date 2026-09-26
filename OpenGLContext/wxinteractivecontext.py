"""The wx window system's Context, under the name ``wxInteractiveContext``

Every Context has the event managers, the camera and the scene loading, so
this name is :class:`~OpenGLContext.wxcontext.wxContext`.
"""
from OpenGLContext.wxcontext import wxContext

wxInteractiveContext = wxContext

__all__ = ('wxInteractiveContext',)
