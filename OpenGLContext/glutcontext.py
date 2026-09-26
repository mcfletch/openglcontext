"""GLUT: :class:`~OpenGLContext.context.Context` on the glut window system

``GLUTContext`` is ``Context`` with ``windowsystem = 'glut'`` chosen.  The
window, its callbacks and its loop are
:mod:`OpenGLContext.windowsystem.glut`'s, and a definition that names
another window system wins over the class.
"""
from OpenGLContext.context import Context
from OpenGLContext.windowsystem.glut import (
    ensureGlutInitialised, glutInitialised,
)

__all__ = ('GLUTContext', 'ensureGlutInitialised', 'glutInitialised')


class GLUTContext(Context):
    """A Context on the glut window system"""

    windowSystemName = 'glut'
