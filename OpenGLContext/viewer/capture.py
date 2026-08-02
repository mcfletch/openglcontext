"""Rendering one frame to a file and quitting.

A viewer asked for a capture is not being watched, so it can take its time: it
draws repeatedly until the scene has settled -- the adaptive analytic-sky IBL
converges over several frames, exactly as it does live -- and only then grabs
the frame.  A capture taken on the first frame would be of a half-lit scene, and
would differ from run to run.
"""
import sys
from typing import TYPE_CHECKING, Any, Optional

__all__ = ['SettleCaptureMixin']


class SettleCaptureMixin(object):
    """Gives a context a settle-then-capture-then-quit mode."""

    #: The capture in progress, or None for an ordinary interactive run.
    settleCapture: Optional[Any] = None
    #: Seconds the model took to load, reported alongside the capture.
    loadSeconds: Any = ''

    if TYPE_CHECKING:
        frameCounter: Any

        def OnQuit(self, event: Any = None) -> Any: ...

    def setupCapture(self, path: Optional[str], delay: float = 0.5,
                     frames: int = 10) -> None:
        """Arrange to capture to ``path`` once the scene has settled.

        ``path`` of None leaves the context interactive.  ``delay`` is how long
        to let the scene converge and ``frames`` the fewest frames to draw
        first, so a fast machine does not capture before the renderer has done
        its adaptive work.
        """
        if not path:
            self.settleCapture = None
            return
        from OpenGLContext.capture import SettleCapture
        self.settleCapture = SettleCapture(path, delay=delay, min_frames=frames)

    @property
    def capturing(self) -> bool:
        """Whether this run exists to take a picture rather than be looked at."""
        return self.settleCapture is not None

    def tickCapture(self) -> bool:
        """Offer the finished frame to the capture.  Returns whether it took it.

        Call from ``SwapBuffers`` **before** the swap, for the same reason as a
        screenshot: the back buffer is only the frame just drawn until it is
        swapped away.
        """
        if self.settleCapture is None:
            return False
        return bool(self.settleCapture.tick())

    def finishCapture(self) -> None:
        """Report what the capture cost and quit.

        The line is machine-readable because the regression harness records it
        per model: a load that suddenly takes twice as long, or a frame rate
        that halves, is a regression worth seeing even when the picture is
        unchanged.
        """
        rate = ''
        counter = getattr(self, 'frameCounter', None)
        if counter is not None:
            try:
                rate = counter.recentFps()
            except Exception:
                rate = ''
        sys.stdout.write('CAPTURE_STATS load_seconds=%s fps=%s\n'
                         % (self.loadSeconds, rate))
        sys.stdout.flush()
        self.OnQuit()
