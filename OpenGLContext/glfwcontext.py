"""GLFW: :class:`~OpenGLContext.context.Context` on the glfw window system

``GLFWContext`` is ``Context`` with ``windowsystem = 'glfw'`` chosen.  The
window, its callbacks and its loop are
:mod:`OpenGLContext.windowsystem.glfw`'s, and a definition that names
another window system wins over the class.
"""
from OpenGLContext.context import Context
from OpenGLContext.windowsystem.glfw import fullscreenMonitor

__all__ = ('GLFWContext', 'fullscreenMonitor')


class GLFWContext(Context):
    """A Context on the glfw window system"""

    windowSystemName = 'glfw'
