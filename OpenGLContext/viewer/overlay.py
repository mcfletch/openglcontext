"""A key that saves the frame to a picture.

The caption that used to live here is now
:mod:`OpenGLContext.viewer.caption`, drawn as a HUD layer by the UI library
along with everything else on the screen.  What is left is the one thing that
is genuinely about the *frame* rather than about the interface: reading the back
buffer before it is swapped away.
"""
import os
import sys
from typing import TYPE_CHECKING, Any

__all__ = ['ScreenshotMixin']


class ScreenshotMixin(object):
    """Gives a context a key that writes the frame to a PNG."""

    #: Key that takes a screenshot; '' binds none.
    screenshotKey: str = '<F2>'
    #: ``strftime`` pattern for the file name, in the working directory.
    screenshotName: str = "gltf-%Y-%m-%dT%H-%M-%S.png"

    _screenshotPending: bool = False

    if TYPE_CHECKING:
        def addEventHandler(self, kind: str, **named: Any) -> Any: ...
        def triggerRedraw(self, force: int = 0) -> Any: ...

    def setupScreenshots(self) -> None:
        """Bind the screenshot key."""
        if self.screenshotKey:
            self.addEventHandler('keyboard', name=self.screenshotKey,
                                 function=self.requestScreenshot)

    def requestScreenshot(self, event: Any = None) -> None:
        """Ask for the next frame to be saved."""
        self._screenshotPending = True
        self.triggerRedraw(1)

    def takePendingScreenshot(self) -> bool:
        """Save the frame if one was asked for.  Returns whether it saved.

        Call from ``SwapBuffers`` **before** the swap: read back afterwards and
        the buffer has already been recycled, which in this container returns
        the previous frame.
        """
        if not self._screenshotPending:
            return False
        self._screenshotPending = False
        self.saveScreenshot()
        return True

    def saveScreenshot(self) -> None:  # pragma: no cover - GL framebuffer read-back
        """Write the current frame to a dated PNG in the working directory."""
        from datetime import datetime
        from OpenGLContext.capture import capture_to_png
        path = os.path.join(os.getcwd(), datetime.now().strftime(self.screenshotName))
        if capture_to_png(path, skip_blank=False):
            sys.stdout.write("Saved screenshot %s\n" % path)
        else:
            sys.stderr.write("Screenshot failed (Pillow missing?).\n")
        sys.stdout.flush()
