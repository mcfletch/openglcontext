"""WGL: :class:`~OpenGLContext.context.Context` rendering offscreen on Windows

``WGLContext`` is ``Context`` with ``windowsystem = 'wgl'`` chosen; the
pbuffer and the helpers below are :mod:`OpenGLContext.windowsystem.wgl`'s,
where they are documented.  A definition that names another window system
wins over the class.  ``windowsystem='offscreen'`` asks for this on Windows
and EGL elsewhere.  See ``docs/offscreen.rst``.
"""
from OpenGLContext.context import Context
from OpenGLContext.windowsystem.wgl import (
    ACCELERATION_VARIABLE, WGLContextError, acceleration, available,
    bufferSizes, profileFor,
)

__all__ = (
    'ACCELERATION_VARIABLE',
    'WGLContext',
    'WGLContextError',
    'acceleration',
    'available',
    'bufferSizes',
    'profileFor',
)


class WGLContext(Context):
    """A Context that renders offscreen, on a WGL pbuffer"""

    windowSystemName = 'wgl'

    def close(self) -> None:
        """Release the GL objects, the context and the pbuffer.

        :meth:`~OpenGLContext.context.Context.releaseWindow`, under the name a
        pbuffer's owner reaches for.  Safe to call twice.
        """
        self.releaseWindow()
