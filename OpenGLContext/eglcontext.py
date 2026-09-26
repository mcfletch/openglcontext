"""EGL: :class:`~OpenGLContext.context.Context` rendering offscreen on EGL

``EGLContext`` is ``Context`` with ``windowsystem = 'egl'`` chosen; the
pbuffer, the device choice and the helpers below are
:mod:`OpenGLContext.windowsystem.egl`'s, where they are documented.  A
definition that names another window system wins over the class.
``windowsystem='offscreen'`` asks for this on Linux and a WGL pbuffer on
Windows.  See ``docs/offscreen.rst``.
"""
from OpenGLContext.context import Context
from OpenGLContext.windowsystem.egl import (
    DEVICE_VARIABLE, PROFILES, EGLContextError, PbufferContext, chooseConfig,
    chooseDevice, closeDisplay, configAttributes, contextAttributes,
    createContext, createPbufferSurface, definitionAttributes, devices,
    openDisplay, prefersSoftware, selectDevice,
)

__all__ = (
    'DEVICE_VARIABLE',
    'EGLContext',
    'EGLContextError',
    'PROFILES',
    'PbufferContext',
    'chooseConfig',
    'chooseDevice',
    'closeDisplay',
    'configAttributes',
    'contextAttributes',
    'createContext',
    'createPbufferSurface',
    'definitionAttributes',
    'devices',
    'openDisplay',
    'prefersSoftware',
    'selectDevice',
)


class EGLContext(Context):
    """A Context that renders offscreen, on an EGL device"""

    windowSystemName = 'egl'

    def close(self) -> None:
        """Release the GL objects, the context, the surface and the display.

        :meth:`~OpenGLContext.context.Context.releaseWindow`, under the name a
        pbuffer's owner reaches for.  Safe to call twice.
        """
        self.releaseWindow()
