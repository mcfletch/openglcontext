"""The key that writes the finished frame to a picture.

Every context gets one: :class:`~OpenGLContext.context.Context` mixes this in
and binds it, so a game, a viewer or a demo has a screenshot key without asking
for one.

**The key only asks.**  A key handler runs between frames, and by then the back
buffer no longer holds the frame the player was looking at -- the driver has
recycled it, and on some drivers reading it returns the frame before last.  So
the handler sets a flag and requests a redraw, and the render pass takes the
picture at the one moment the frame is both finished and still in the back
buffer: immediately before the swap, in ``FlatPass.presentFrame``.

The file is written by :meth:`~OpenGLContext.context.Context.OnSaveImage`,
which names it after the running program and puts it in the working directory.
"""
from typing import TYPE_CHECKING, Any, Tuple

__all__ = ['ScreenshotMixin']


class ScreenshotMixin(object):
    """A key that saves the frame, read back before the buffers are swapped."""

    #: The key that takes a screenshot.  An application that wants F2 for
    #: something of its own sets this to ``''`` and nothing is bound.
    screenshotKey: str = '<F2>'

    #: Whether a screenshot has been asked for and not yet taken.  A class
    #: attribute so a context that never asks reads it without setting it.
    _screenshotPending: bool = False

    if TYPE_CHECKING:
        def addEventHandler(self, kind: str, **named: Any) -> Any: ...
        def triggerRedraw(self, force: int = 0) -> Any: ...
        def OnSaveImage(self, event: Any = None) -> Tuple[int, int]: ...

    def setupScreenshotKey(self) -> None:
        """Bind :attr:`screenshotKey`, if there is one.

        A key-down rather than a ``keypress``: a keypress *is* character input,
        and a function key produces no character, so a keypress binding for one
        is accepted, registered, and then never fires.
        """
        if self.screenshotKey:
            self.addEventHandler('keyboard', name=self.screenshotKey, state=1,
                                 function=self.requestScreenshot)

    def requestScreenshot(self, event: Any = None) -> None:
        """Ask for the next frame to be saved.

        The redraw is what makes the key work on a still scene: with nothing
        moving there is no next frame to save until something asks for one.
        """
        self._screenshotPending = True
        self.triggerRedraw(1)

    def takePendingScreenshot(self) -> bool:
        """Save the frame if one was asked for.  Returns whether it saved.

        Call with the finished frame still in the back buffer, before the swap.
        """
        if not self._screenshotPending:
            return False
        self._screenshotPending = False
        self.OnSaveImage()
        return True
