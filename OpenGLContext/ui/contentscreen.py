"""The screen a player downloads content on: what is offered, its terms, how far.

A content pack is tens to hundreds of megabytes of somebody's work under
somebody's terms, so the screen that fetches one says, before the button is
pressed, what the choice costs (the whole set it pulls in, not the one pack
named) and whose it is; and after, how far the download has got, whether it
failed or was stopped, and a way to stop it.

:class:`ContentScreen` is that screen over the engine's
:class:`~OpenGLContext.contentpacks.fetch.FetchJob`. The caller says what is on
offer and makes the job when the player chooses; the screen shows the job and
is refreshed from the frame loop::

    screen = ContentScreen(
        content.offered(), wanted=content.wanted_for,
        on_fetch=lambda pack: FetchJob(content.wanted_for(pack), store,
                                       within=pack),
        on_finished=lambda job: screen.offer(content.offered()))
    context.pushOverlay(screen.panel)
    ...
    screen.poll()                       # once a frame, from OnIdle or OnDraw

For a first run, ``together=True`` offers every pack as one set, which is the
form a base pack and what it needs take. Building the screen touches no GL.
"""

from __future__ import annotations

from gettext import gettext as _
from collections.abc import Callable, Sequence
from typing import Any, Optional

from OpenGLContext.contentpacks.fetch import FetchJob
from OpenGLContext.contentpacks.pack import ContentPack, human_bytes
from OpenGLContext.ui.layout import Column, Row
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import (
    PRIMARY,
    Button,
    Label,
    ProgressBar,
    Select,
    Separator,
    Spacer,
)

__all__ = ['ALL_HERE', 'ContentScreen', 'DONE', 'STOPPED', 'offer_text',
           'progress_text']

#: What the screen says when nothing is left to fetch.
ALL_HERE = _('Everything on offer is already here.')

#: What a job the player stopped says.
STOPPED = _('Stopped.')

#: What a job that finished says.
DONE = _('Done.')

#: How wide the screen is, in characters.
COLUMNS = 64

#: Given one pack, the set choosing it fetches (it first, then what it needs).
Wanted = Callable[[ContentPack], Sequence[ContentPack]]


class ContentScreen:
    """What is on offer, what it costs, whose it is, and how far a fetch is.

    ``packs`` is what is on offer. ``wanted(pack)`` is the whole set choosing
    one pulls in, which is the size shown; without it a pack stands for itself.
    ``together`` offers every pack as one set rather than one at a time.
    ``on_fetch(pack)`` is called when the player presses Download, with the
    chosen pack (the first, with ``together``), and returns the
    :class:`~OpenGLContext.contentpacks.fetch.FetchJob` it started, or None.
    ``on_finished(job)`` is called once when that job ends, however it ended,
    and ``on_close()`` once when the screen is closed. ``heading`` is a line
    shown above the offer (the size of the whole catalogue, say). ``job`` is a
    download
    already under way (one a closed screen started) to show from the start;
    one that has already ended is shown and not reported again.

    The last job's result stays on the screen until the next download starts,
    so a failure and a stop are shown rather than replaced by an idle screen.
    """

    def __init__(self, packs: Sequence[ContentPack],
                 on_fetch: Optional[Callable[[ContentPack],
                                             Optional[FetchJob]]] = None,
                 wanted: Optional[Wanted] = None,
                 on_finished: Optional[Callable[[FetchJob], None]] = None,
                 on_close: Optional[Callable[[], None]] = None,
                 title: str = '', together: bool = False,
                 columns: int = COLUMNS,
                 job: Optional[FetchJob] = None,
                 heading: str = '') -> None:
        self.packs: list[ContentPack] = []
        self.wanted = wanted
        self.together = together
        self.on_fetch = on_fetch
        self.on_finished = on_finished
        self.on_close = on_close
        #: The download under way, or the last one, until the next starts.
        self.job: Optional[FetchJob] = job
        self._reported = job is not None and job.finished
        self._closed = False

        self.chooser = Select(name='offered')
        self.chooser.on_change = lambda _widget: self._describe()
        self.caption = Label(text='', wrap=True, name='offer')
        # A bar and the words: the bar is how far, the words are which pack
        # and what went wrong.
        self.progress = ProgressBar(fraction=0.0, text='', name='progress')
        self.fetch_button = Button(text=_('Download'), name='fetch',
                                   role=PRIMARY)
        self.stop_button = Button(text=_('Stop'), name='stop')
        self.close_button = Button(text=_('Close'), name='close')
        self.fetch_button.on_activate = lambda _widget: self._start()
        self.stop_button.on_activate = lambda _widget: self._stop()
        self.close_button.on_activate = lambda _widget: self._close()
        body: list[Any] = [self.caption, self.progress, Separator(top=6),
                           Row(spacing=8, name='buttons', children=[
                               self.fetch_button, self.stop_button, Spacer(),
                               self.close_button])]
        if not together:
            body.insert(0, self.chooser)
        #: The line above the offer; empty shows none.
        self.heading = Label(text=heading, wrap=True, name='heading')
        if heading:
            body.insert(0, self.heading)
        self.panel = Panel(title=title or _('Content'), scrim=True, modal=True,
                           preferredColumns=columns,
                           children=[Column(spacing=4, children=body)])
        self.panel.on_close = lambda _panel: self._closing()
        self.offer(packs)
        if job is not None:
            self.progress.fraction = float(job.fraction)
            self.progress.text = progress_text(job)

    # -- what is on offer ---------------------------------------------------

    def offer(self, packs: Sequence[ContentPack]) -> None:
        """Put ``packs`` on offer, keeping the choice where it is still there."""
        self.packs = list(packs)
        keys = [pack.key for pack in self.packs]
        was = self.chooser.value
        self.chooser.options = keys or ['']
        self.chooser.optionLabels = [
            '%s — %s' % (pack.title, pack.human_size())
            for pack in self.packs] or [ALL_HERE]
        self.chooser.value = was if was in keys else (keys[0] if keys else '')
        self._describe()
        self._enable()

    def chosen(self) -> Optional[ContentPack]:
        """The pack a Download would fetch for; the first with ``together``."""
        if not self.packs:
            return None
        if not self.together:
            for pack in self.packs:
                if pack.key == self.chooser.value:
                    return pack
        return self.packs[0]

    def whole(self) -> list[ContentPack]:
        """Every pack a Download would fetch."""
        if self.together:
            return list(self.packs)
        pack = self.chosen()
        if pack is None:
            return []
        return list(self.wanted(pack)) if self.wanted is not None else [pack]

    # -- the frame loop -----------------------------------------------------

    def poll(self) -> bool:
        """Poll the job and show what it has done; whether anything changed.

        Called once a frame. ``on_finished`` is called the first time the job
        is seen to have ended.
        """
        job = self.job
        if job is None:
            return False
        was = (self.progress.fraction, self.progress.text)
        job.poll()
        self.progress.fraction = float(job.fraction)
        self.progress.text = progress_text(job)
        self._enable()
        if job.finished and not self._reported:
            self._reported = True
            if self.on_finished is not None:
                self.on_finished(job)
        return (self.progress.fraction, self.progress.text) != was

    @property
    def running(self) -> bool:
        """Whether a download is under way."""
        return self.job is not None and not self.job.finished

    # -- the buttons --------------------------------------------------------

    def _start(self) -> None:
        pack = self.chosen()
        if pack is None or self.running or self.on_fetch is None:
            return
        job = self.on_fetch(pack)
        if job is None:
            return
        self.job, self._reported = job.start(), False
        self.progress.fraction, self.progress.text = 0.0, progress_text(job)
        self._enable()

    def _stop(self) -> None:
        if self.running and self.job is not None:
            self.job.cancel()

    def _close(self) -> None:
        self.panel.close(False)

    def _closing(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.on_close is not None:
            self.on_close()

    def _describe(self) -> None:
        self.caption.text = offer_text(self.chosen(), self.whole())

    def _enable(self) -> None:
        self.fetch_button.enabled = bool(self.packs) and not self.running
        self.stop_button.enabled = self.running


def offer_text(pack: Optional[ContentPack],
               whole: Sequence[ContentPack] = ()) -> str:
    """One choice as a player reads it before agreeing to fetch it.

    The title and the size of ``whole``, the set the choice fetches; the
    pack's notes; each other pack in the set with its size; and the terms of
    every pack in it. :data:`ALL_HERE` for no pack.
    """
    if pack is None:
        return ALL_HERE
    whole = list(whole) or [pack]
    total = sum(one.approximate_bytes for one in whole)
    said = ['%s — %s' % (pack.title, human_bytes(total))]
    if pack.notes:
        said.append(pack.notes)
    for one in whole:
        if one.key != pack.key:
            said.append(_('with %s — %s') % (one.title, one.human_size()))
    for one in whole:
        if one.copyright and one.copyright not in said:
            said.append(one.copyright)
    return '\n'.join(said)


def progress_text(job: Optional[FetchJob]) -> str:
    """How far a download has got, or how it ended.

    A job the player stopped and a job that failed are said differently: a
    stop is the player's decision and a failure names its reason.
    """
    if job is None:
        return ''
    if job.finished:
        if job.cancelled:
            return STOPPED
        if job.failed is not None:
            return _('Could not download: %s') % (job.failed,)
        return DONE
    return '%s — %d%%' % (job.state, round(float(job.fraction) * 100))
