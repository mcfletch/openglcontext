"""Downloading content packs without freezing the window.

A texture pack is 450 MB. Fetching one on the frame loop's thread stops the
window dead for minutes -- no redraw, no cancel, and on most desktops an
eventual "this application is not responding" from the window manager.

So the work happens on a worker thread and **the frame loop polls**:
:meth:`FetchJob.poll` is called once a frame, publishes whatever the worker has
managed since the last call, and is the *only* place anything the worker wrote
is read. That single rule is the whole of the thread safety here, and it is why
a caller needs no lock of its own: everything a caller touches --
:attr:`~FetchJob.finished`, :attr:`~FetchJob.fraction`, :attr:`~FetchJob.roots`
-- is written by ``poll`` on the caller's own thread.

The consequence is worth stating plainly because it looks like a bug and is
not: a job whose worker has run to completion still reports itself unfinished
until it is polled. A frame loop that stops polling stops learning, which is
correct -- there is nobody to tell.

:func:`fetch_pack` is the same work without the thread, for a command line or a
test.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Sequence

from OpenGLContext.loaders import resolver

from . import archive, catalog
from .pack import ContentPack
from .store import ContentStore

log = logging.getLogger(__name__)

__all__ = ['Cancelled', 'FLOOR', 'FetchJob', 'HEADROOM', 'REGISTRY_LIMIT',
           'TooLarge', 'fetch_limit', 'fetch_pack', 'fetch_registry',
           'missing_base']

#: How much larger than its published size a pack is allowed to be. A size
#: drifts between releases, and a fetch that fails on the last megabyte is worse
#: than one that never started.
HEADROOM = 1.5

#: The smallest cap any fetch runs under. The resolver's own default is the
#: right limit for an asset of unknown size, so a pack smaller than it gains
#: nothing by asking for less.
FLOOR = resolver.DEFAULT_MAX_RESOURCE_BYTES

#: The cap a registry bundle is fetched under, well below the one a content pack
#: gets. A registry is a document and some thumbnails, and one arriving at the
#: size of the content it describes is not a registry -- there is no size
#: declared in advance to judge it against, so the judgement is made here.
REGISTRY_LIMIT = 16 * 1024 * 1024

#: What one pack's fetch is called with: the pack, a progress callback taking
#: bytes-so-far and an optional total, and a predicate that goes true when the
#: user has cancelled. Returns the pack's unpacked content root.
Fetch = Callable[[ContentPack, Callable[[int, int | None], None],
                  Callable[[], bool]], str]


class Cancelled(Exception):
    """The user asked for the download to stop.

    Distinct from a failure so the two can be reported differently: nothing went
    wrong, and telling somebody their own decision was an error is a poor way to
    answer it.
    """


#: Past a cap: too much to download, or too much to unpack to. One class for
#: both, and :mod:`~OpenGLContext.contentpacks.archive` owns it, so a caller
#: reporting "the content did not arrive" catches one thing. The resolver states
#: an over-cap download as a ``ValueError``, which is right for a size limit in
#: general and wrong for one of several ways one fetch can fail.
TooLarge = archive.TooLarge


def fetch_limit(approximate_bytes: int) -> int:
    """The byte cap to fetch a pack of this size under."""
    return max(int(approximate_bytes * HEADROOM), FLOOR)


def missing_base(packs: Sequence[ContentPack],
                 store: ContentStore) -> list[ContentPack]:
    """What a first run has to fetch before the application can start.

    Every ``base`` pack not already on this machine, and whatever those are
    incomplete without -- a base pack may be split, and half of one is not a
    floor. Empty where an application ships all of its own art, which is the
    answer for anything that declares no base pack.
    """
    wanted: list[ContentPack] = []
    for pack in packs:
        if not pack.base:
            continue
        for one in catalog.with_needed(pack, packs):
            if one not in wanted:
                wanted.append(one)
    return store.missing(wanted)


def fetch_registry(url: str, store: ContentStore, progress: Any = None,
                   cancel: Any = None,
                   cache_dir: str | None = None) -> list[ContentPack]:
    """Fetch a registry bundle and return the packs it declares.

    What an application does when it is pointed at somebody else's set of
    content: the bundle is a document and its thumbnails, so this gives a
    chooser a picture of everything on offer while downloading none of it.

    The bundle is kept under the store's own registries directory, so a later
    run finds it without being pointed at it again, and its packs are held to
    the same namespacing rule as the shipped registry's.
    """
    log.info('fetching the registry at %s', resolver.safe_url(url))
    try:
        downloaded = resolver.fetch_to_cache(
            url, cache_dir=cache_dir, max_bytes=REGISTRY_LIMIT,
            progress=progress, cancel=cancel)
    except resolver.FetchCancelled as error:
        raise Cancelled(str(error)) from error
    except ValueError as error:
        raise TooLarge('the registry at %s is over the %d bytes a registry is '
                       'fetched under: %s' % (resolver.safe_url(url),
                                              REGISTRY_LIMIT, error)) from error
    kept = store.keep_registry(downloaded, url)
    return catalog.load_bundle(kept, store.unpacked_registry(kept))


def fetch_pack(pack: ContentPack, store: ContentStore,
               progress: Any = None, cancel: Any = None,
               cache_dir: str | None = None) -> str:
    """Fetch and unpack one pack; return its content root.

    A pack already on this machine is returned without touching the network, and
    its progress is reported as finished, so a caller drawing a bar sees it fill
    whether or not anything was downloaded.

    The digest is checked before anything is written into the store, so a
    truncated or substituted download is a refusal here rather than content that
    renders wrongly later, and the unpacking is bounded by what the pack said
    its size was -- a cap on the transfer says nothing about what the transfer
    expands to.
    """
    existing = store.root_for(pack)
    if existing is not None:
        _report(progress, pack.approximate_bytes, pack.approximate_bytes)
        return existing
    log.info('fetching %s (%s)', pack.key, pack.human_size())
    try:
        downloaded = resolver.fetch_to_cache(
            pack.url, cache_dir=cache_dir,
            max_bytes=fetch_limit(pack.approximate_bytes),
            progress=progress, cancel=cancel)
    except resolver.FetchCancelled as error:
        raise Cancelled(str(error)) from error
    except ValueError as error:
        # The one ValueError this path can reach: the resolver's size check.
        raise TooLarge('%s is larger than the %d bytes its declared size of %s '
                       'allows: %s' % (pack.key,
                                       fetch_limit(pack.approximate_bytes),
                                       pack.human_size(), error)) from error
    archive.check_digest(downloaded, pack.sha256)
    return archive.extract(downloaded, store.directory_for(pack), pack.archive,
                           max_bytes=archive.unpacked_limit(
                               pack.approximate_bytes))


def _report(progress: Any, done: int, total: int | None) -> None:
    if progress is not None:
        progress(done, total)


class FetchJob:
    """One user-consented download of one or more packs, run off the frame loop.

    **One bar for the job, not one per pack.** A user who consents to three
    packs agreed to a single download of their combined size; a bar that fills
    and resets three times reads as three failures. :attr:`fraction` therefore
    spans the whole set, weighted by the sizes the user was shown.
    """

    def __init__(self, packs: Sequence[ContentPack], store: ContentStore,
                 fetch: Fetch | None = None, cache_dir: str | None = None,
                 on_progress: Callable[[], None] | None = None) -> None:
        self.packs = list(packs)
        self.store = store
        self.cache_dir = cache_dir
        self._fetch: Fetch = fetch if fetch is not None else (
            lambda pack, progress, cancel: fetch_pack(
                pack, store, progress, cancel, cache_dir=cache_dir))
        #: Called after each :meth:`poll` that saw something change, so a caller
        #: can ask for a redraw without polling for a difference.
        self.on_progress = on_progress

        #: How much of the job the user consented to, in bytes.
        self.total_bytes = sum(pack.approximate_bytes for pack in self.packs)

        # -- published by poll(), read by the frame loop ---------------------
        #: Whether the worker has finished, as of the last poll.
        self.finished = False
        #: The error that stopped it, or None. A cancellation is not one.
        self.failed: BaseException | None = None
        #: Whether it stopped because the user said so.
        self.cancelled = False
        #: The content roots of the packs that did arrive.
        self.roots: list[str] = []
        #: How far along, 0 to 1.
        self.fraction = 1.0 if not self.packs else 0.0
        #: A line for the user: which pack, and how far.
        self.state = 'ready'

        # -- written by the worker, read only under _lock ---------------------
        self._lock = threading.Lock()
        self._done_bytes = 0
        self._current = ''
        self._roots: list[str] = []
        self._failed: BaseException | None = None
        self._cancelled = False
        self._ended = False
        self._stop = False
        self._thread: threading.Thread | None = None

    def start(self) -> 'FetchJob':
        """Begin now, on a worker thread; returns self, so it can be chained.

        :meth:`poll` starts the job itself, so most callers never need this: a
        job nobody polls is one nobody is waiting for. Use it where the download
        should be under way before the next frame is drawn.
        """
        if self._thread is None and self.packs:
            self._thread = threading.Thread(target=self._work, daemon=True,
                                            name='contentpacks-fetch')
            self._thread.start()
        return self

    def cancel(self) -> None:
        """Ask the worker to stop. Acted on between chunks.

        What the *user* asked for, which is not the same as what happened:
        :attr:`cancelled` says the job stopped because of it, and like
        everything else a caller reads it is published by :meth:`poll`.
        """
        with self._lock:
            self._stop = True

    def human_total(self) -> str:
        """How much this job is, as the user consented to read it."""
        return '%d MB' % (round(self.total_bytes / 1e6),)

    def poll(self) -> None:
        """Publish what the worker has managed, and start it the first time.

        Called once a frame. Cheap enough to call whether or not anything is
        happening: it takes one lock and copies a handful of values.
        """
        if self.finished:
            return
        if not self.packs:
            # Nothing to start a thread for, and starting one would make
            # "finished after the first poll" depend on the scheduler.
            self.finished, self.state = True, 'nothing to fetch'
            return
        self.start()
        with self._lock:
            done, current = self._done_bytes, self._current
            roots, failed = list(self._roots), self._failed
            cancelled, ended = self._cancelled, self._ended
        fraction = 1.0 if not self.total_bytes else min(
            1.0, done / float(self.total_bytes))
        changed = (fraction != self.fraction or current != self.state
                   or ended != self.finished)
        self.fraction, self.roots = fraction, roots
        self.failed, self.cancelled = failed, cancelled
        self.state = current or self.state
        self.finished = ended
        if ended and failed is None and not cancelled:
            self.fraction = 1.0
        if changed and self.on_progress is not None:
            self.on_progress()

    def _work(self) -> None:
        """The worker. Everything it writes is written under the lock."""
        try:
            for pack in self.packs:
                with self._lock:
                    if self._stop:
                        raise Cancelled('the download was stopped')
                    self._current = pack.title
                    before = self._done_bytes
                root = self._fetch(pack, self._progress(before), self._stopping)
                with self._lock:
                    self._roots.append(root)
                    self._done_bytes = before + pack.approximate_bytes
        except Cancelled:
            with self._lock:
                self._cancelled = True
        except BaseException as error:      # published, never raised at a caller
            log.warning('fetching content failed: %s', error)
            with self._lock:
                self._failed = error
        finally:
            with self._lock:
                self._ended = True

    def _progress(self, before: int) -> Callable[[int, int | None], None]:
        """One pack's progress, as a position within the whole job."""
        def report(done: int, total: int | None) -> None:
            with self._lock:
                self._done_bytes = before + done
        return report

    def _stopping(self) -> bool:
        with self._lock:
            return self._stop
