"""Tk: :class:`~OpenGLContext.context.Context` on the tk window system

``TkContext`` is ``Context`` with ``windowsystem = 'tk'`` chosen.  The
widget, its callbacks and its loop are :mod:`OpenGLContext.windowsystem.tk`'s,
and a definition that names another window system wins over the class.  To put
a view inside an existing Tk application, give it the widget to sit in::

    context = TkContext(parent=someFrame)
    context.window.pack(fill='both', expand=True)
"""
import warnings
from typing import Any

from OpenGLContext.context import Context
from OpenGLContext.windowsystem.tk import FRAME_INTERVAL, attributesFromDefinition

__all__ = ('FRAME_INTERVAL', 'TkContext', 'attributesFromDefinition')


class TkContext(Context):
    """A Context on the tk window system"""

    windowSystemName = 'tk'

    @property
    def frame(self) -> Any:
        """The ``GLFrame`` the view draws into: :attr:`window`, by the name
        this class also answers to for one release"""
        warnings.warn(
            'TkContext.frame is the view\'s window; use context.window',
            DeprecationWarning, stacklevel=2)
        return self.window
