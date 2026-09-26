"""wx: :class:`~OpenGLContext.context.Context` on the wx window system

``wxContext`` is ``Context`` with ``windowsystem = 'wx'`` chosen, taking the
wx window to sit in as its first argument.  The canvas, its callbacks and its
loop are :mod:`OpenGLContext.windowsystem.wx`'s, and ``context.window`` is the
``GLCanvas`` an application places in its layout::

    view = wxContext(splitter)
    sizer.Add(view.window, 1, wx.EXPAND)
"""
from typing import Any

from OpenGLContext.context import Context
from OpenGLContext.windowsystem.wx import getDefaultIcons, getIcon

__all__ = ('getIcon', 'wxContext')


class wxContext(Context):
    """A Context on the wx window system"""

    windowSystemName = 'wx'

    def __init__(self, parent: Any = None, definition: Any = None,
                 **named: Any) -> None:
        """parent -- the wx window the canvas sits in; None for a frame of
            its own
        definition -- as for :class:`~OpenGLContext.context.Context`
        named -- individual definition fields
        """
        super().__init__(definition, parent=parent, **named)

    @classmethod
    def getDefaultIcons(cls) -> Any:
        """The OpenGLContext icons as a wx.IconBundle; see
        :func:`OpenGLContext.windowsystem.wx.getDefaultIcons`"""
        return getDefaultIcons()
