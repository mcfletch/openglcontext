"""The Pygame window system's Context, under the name ``VRMLContext``

Every Context has the event managers, the camera and the scene loading, so
this name is :class:`~OpenGLContext.pygamecontext.PygameContext`.
"""
from OpenGLContext.pygamecontext import PygameContext

VRMLContext = PygameContext

__all__ = ('VRMLContext',)
