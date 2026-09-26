"""Pygame: :class:`~OpenGLContext.context.Context` on the pygame window system

``PygameContext`` is ``Context`` with ``windowsystem = 'pygame'`` chosen.  The
window, its callbacks and its loop are
:mod:`OpenGLContext.windowsystem.pygame`'s, and a definition that names
another window system wins over the class.
"""
from OpenGLContext.context import Context


class PygameContext(Context):
    """A Context on the pygame window system"""

    windowSystemName = 'pygame'
