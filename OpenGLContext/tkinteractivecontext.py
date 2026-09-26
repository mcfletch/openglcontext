"""The Tk window system's Context, under the name ``TkInteractiveContext``

Every Context has the event managers, the camera and the scene loading, so
this name is :class:`~OpenGLContext.tkcontext.TkContext`.
"""
from OpenGLContext.tkcontext import TkContext

TkInteractiveContext = TkContext

__all__ = ('TkInteractiveContext',)
