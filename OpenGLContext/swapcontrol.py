"""Whether a buffer swap waits for the display's refresh.

The setting is :attr:`ContextDefinition.vsync`; what a *backend* has to do about
it differs. GLFW, Qt and SDL each name it themselves, and this is for the ones
that do not -- GLUT and wxPython -- which have to ask the window system through
whichever of its extensions is present.

Waiting caps the frame rate at the display's, which is what a game wants and a
benchmark does not. It also matters on Wayland, where a vsynced swap blocks on a
compositor frame callback that a leaked GL context from an abnormally-terminated
process can wedge, so the test suite turns it off and one bad run cannot stall
every later swap.

Call :func:`set_swap_interval` with the window's GL context **current**: both
paths read the drawable the calling thread is bound to.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List

log = logging.getLogger(__name__)

__all__ = ['set_swap_interval']


def set_swap_interval(interval: int) -> bool:
    """Set the swap interval for the current context; answer whether it took

    interval -- 0 to swap as fast as the driver will, 1 to wait for one
        refresh.  Larger values are passed through, and mean that many
        refreshes where the platform supports them.

    False means no extension for it was available -- a driver without it, a
    platform PyOpenGL has no binding for, or no current context -- and the swap
    keeps whatever interval the driver chose.  It is a report rather than an
    error: a frame rate that is capped when it was asked not to be is a
    surprising benchmark, not a broken program.
    """
    interval = int(interval)
    for attempt in _ATTEMPTS:
        try:
            if attempt(interval):
                return True
        except Exception:
            log.debug('%s could not set the swap interval', attempt.__name__,
                      exc_info=True)
    return False


def _glx(interval: int) -> bool:
    """GLX_EXT_swap_control, which is X11 with a desktop GL driver"""
    from OpenGL import GLX
    from OpenGL.GLX.EXT import swap_control

    if not swap_control.glXSwapIntervalEXT:
        return False
    display: Any = GLX.glXGetCurrentDisplay()
    drawable: Any = GLX.glXGetCurrentDrawable()
    if not display or not drawable:
        return False                    # no context current on this thread
    swap_control.glXSwapIntervalEXT(display, drawable, interval)
    return True


def _egl(interval: int) -> bool:
    """eglSwapInterval, which is Wayland and X11-on-EGL alike"""
    from OpenGL import EGL

    display: Any = EGL.eglGetCurrentDisplay()
    if not display:
        return False
    return bool(EGL.eglSwapInterval(display, interval))


#: Tried in turn until one answers.  GLX first because a GLUT or wx window on
#: X11 is the case this exists for, and because EGL's call succeeds against a
#: display that is not the one being drawn into.
_ATTEMPTS: List[Callable[[int], bool]] = [_glx, _egl]
