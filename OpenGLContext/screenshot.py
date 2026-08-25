"""The screenshot key every context has, and where the picture goes.

:class:`~OpenGLContext.context.Context` mixes this in and binds it, so a game, a
viewer or a demo has a working screenshot key with no configuration at all.  F2
is what a player reaches for; Alt+S is what the demos here have always used, and
both do the same thing.  An application that wants F2 for something of its own
sets :attr:`ScreenshotMixin.screenshotKey` to another key, or to ``''`` for none.

**The key only asks.**  A key handler runs between frames, and by then the back
buffer no longer holds the frame the player was looking at: the driver has
recycled it, and reading it returns an older frame or nothing at all.  So the
handler raises a flag and asks for a redraw, and the picture is taken from
:meth:`~OpenGLContext.context.Context.presentFrame` -- the one moment the frame
is both finished and still in the back buffer, immediately before the swap.

The file lands in the user's picture folder
(:func:`OpenGLContext.userpaths.picturesdirectory`), named for the window title
so that a folder holding shots from several applications says which took which.
"""
import logging
import os
import re
import sys
from typing import TYPE_CHECKING, Any, Optional, Tuple

from OpenGLContext import userpaths

log = logging.getLogger(__name__)

__all__ = ['ScreenshotMixin', 'filenameSafe']

#: Characters no filename may hold on one platform or another, plus whitespace.
#: Windows rejects the punctuation outright; the separators would make the title
#: into a path.
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f\s]+')


def filenameSafe(title: str) -> str:
    """``title`` as something a file can be called, or '' if nothing is left.

    Runs of anything a filename cannot hold become a single hyphen, so
    ``Twitchy: GLitchy Bang Bang`` files as ``Twitchy-GLitchy-Bang-Bang``.  A
    leading dot would hide the picture on Unix and is trimmed with the rest.
    """
    return _UNSAFE.sub('-', title or '').strip('-. ')


class ScreenshotMixin(object):
    """A key that saves the frame, read back before the buffers are swapped."""

    #: The key that takes a screenshot; ``''`` binds none.
    screenshotKey: str = '<F2>'
    #: How a screenshot with no name of its own is named.  ``%(name)s`` is the
    #: window title, ``%(count)04i`` counts up until it finds a free name.
    screenshotTemplate: str = '%(name)s-%(count)04i.png'
    #: Whether a screenshot has been asked for and not yet taken.  A class
    #: attribute, so a context that never asks reads it without setting it.
    _screenshotPending: bool = False

    if TYPE_CHECKING:
        contextDefinition: Any

        def addEventHandler(self, kind: str, **named: Any) -> Any: ...
        def triggerRedraw(self, force: int = 0) -> Any: ...
        def getViewPort(self) -> Tuple[int, int]: ...
        def getApplicationName(self) -> str: ...

    # -- asking for one ---------------------------------------------------
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
        moving there is no next frame to take a picture of until something asks
        for one.
        """
        self._screenshotPending = True
        self.triggerRedraw(1)

    def takePendingScreenshot(self) -> bool:
        """Save the frame if one was asked for; whether it saved.

        Called with the finished frame still in the back buffer, from
        :meth:`~OpenGLContext.context.Context.presentFrame`.
        """
        if not self._screenshotPending:
            return False
        self._screenshotPending = False
        self.OnSaveImage()
        return True

    # -- taking it --------------------------------------------------------
    def OnSaveImage(
        self,
        event: Any = None,
        template: Optional[str] = None,
        script: Optional[str] = None,
        date: Optional[str] = None,
        overwrite: bool = False,
    ) -> Tuple[int, int]:
        """Save the current frame to disk, and say what size it was.

        The file goes to the user's picture folder, named for the window title:
        ``GLinting-Steel-0001.png``.  ``%(count)04i`` counts up until it finds a
        name nothing is using, so pressing the key twice keeps both shots.

        ``template`` names the file, defaulting to :attr:`screenshotTemplate`;
        an absolute one is obeyed as it stands, a relative one is taken as a
        name in :meth:`screenshotDirectory`.  It is filled from ``%(name)s``,
        ``%(count)04i``, ``%(script)s``, ``%(date)s`` and the frame's
        ``%(width)i`` and ``%(height)i``.

        ``script`` names the program the shot is of, for a caller -- the
        regression harness is one -- that is taking a picture on behalf of
        something other than itself; ``%(name)s`` is then that program's name
        rather than the window title.

        Returns ``(0, 0)`` when nothing was written, which is what a caller that
        retries watches for.
        """
        from OpenGLContext.capture import ensure_pillow, read_back_buffer, save_png
        if ensure_pillow() is None:
            return (0, 0)
        width, height = self.getViewPort()
        if not width or not height:
            return (int(width), int(height))
        name = self._screenshotName(script) if script is not None \
            else self.screenshotTitle()
        pixels, width, height = read_back_buffer()
        if date is None:
            import datetime

            date = datetime.datetime.now().isoformat()
        pattern = template or self.screenshotTemplate
        values = {'name': name, 'script': script or sys.argv[0], 'date': date,
                  'width': width, 'height': height, 'count': 0}
        directory = None
        for count in range(1, 10000):
            values['count'] = count
            test = pattern % values
            if not os.path.isabs(test):
                if directory is None:
                    directory = self.screenshotDirectory()
                test = os.path.join(directory, test)
            if overwrite or (not os.path.exists(test)):
                log.warning("Saving to file: %s", test)
                if save_png(test, pixels):
                    return (width, height)
                return (0, 0)
            log.info("Existing file: %s", test)
        return (0, 0)

    # -- where it goes ----------------------------------------------------
    def screenshotDirectory(self) -> str:
        """The directory a screenshot with no path of its own is written to.

        The user's picture folder, made if it is not there yet, because that is
        where they will look for it.  A machine with no home directory to hold
        one -- a service account, a stripped container -- gets the working
        directory, which is the only other place the caller can be assumed to
        have meant.
        """
        try:
            directory = userpaths.picturesdirectory()
            os.makedirs(directory, exist_ok=True)
        except OSError:
            log.info('No picture folder available; saving to the working directory')
            return os.getcwd()
        return directory

    def screenshotTitle(self) -> str:
        """The name this application's screenshots are filed under.

        The window title, which is the name the person pressing the key has been
        looking at.  An application that sets none is named for the program
        running, which is what tells one viewer's shots from another's.
        """
        definition = getattr(self, 'contextDefinition', None)
        title = filenameSafe(getattr(definition, 'title', '') or '')
        return title or self._screenshotName(sys.argv[0])

    def _screenshotName(self, script: Optional[str]) -> str:
        """A filename-safe name for a program, given how it was run.

        The basename of ``script`` without its extension.  One that is not a
        path at all -- ``-c``, or empty -- falls back to the application name,
        because the point is a name a file can have.
        """
        base = os.path.splitext(os.path.basename(script or ''))[0]
        if not base or base.startswith('-'):
            return self.getApplicationName()
        return filenameSafe(base) or self.getApplicationName()
