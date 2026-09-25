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

import http.client
import logging
import os
import threading
import urllib.parse
from typing import Any, Callable, Sequence

from OpenGLContext.loaders import resolver

from . import archive, catalog
from .pack import ContentPack
from .store import ContentStore

log = logging.getLogger(__name__)

__all__ = ['Cancelled', 'FLOOR', 'FetchJob', 'HEADROOM', 'REGISTRY_LIMIT',
           'TooLarge', 'base_fetches', 'fetch_limit', 'fetch_pack',
           'fetch_registry', 'missing_base', 'wanted_for']

#: How much larger than its published size a pack is allowed to be. A size
#: drifts between releases, and a fetch that fails on the last megabyte is worse
#: than one that never started.
HEADROOM = 1.5

#: The smallest cap any fetch runs under. The resolver's own default is the
#: right limit for an asset of unknown size, so a pack smaller than it gains
#: nothing by asking for less.
FLOOR = resolver.DEFAULT_MAX_RESOURCE_BYTES

#: The cap a registry bundle is fetched under, well below the one a content pack
#: gets, and the one it is unpacked under.
REGISTRY_LIMIT = catalog.REGISTRY_LIMIT

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
#: an over-cap download as :class:`~OpenGLContext.loaders.resolver.ResourceTooLarge`,
#: a ``ValueError``, which is right for a size limit in general and wrong for
#: one of several ways one fetch can fail.
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

    The list to show the user for consent: titles, sizes and terms. What a
    base pack needs lands within that base pack, so fetch the set through
    :func:`base_fetches`, which pairs each pack with the one it lands in.
    """
    wanted: list[ContentPack] = []
    for one, _within in base_fetches(packs, store):
        if one not in wanted:
            wanted.append(one)
    return wanted


def base_fetches(packs: Sequence[ContentPack], store: ContentStore
                 ) -> list[tuple[ContentPack, ContentPack]]:
    """What a first run fetches, each paired with the base pack it lands in.

    ``(pack, within)`` for every base pack not on this machine and every pack
    it needs, where ``within`` is that base pack -- the pack itself, for the
    base pack. :class:`FetchJob` takes the pairs as they are, and a caller
    fetching in the foreground passes each ``within`` to :func:`fetch_pack`.
    A pack two base packs need is fetched into each.
    """
    wanted: list[tuple[ContentPack, ContentPack]] = []
    for base in packs:
        if not base.base:
            continue
        for one in store.missing(catalog.with_needed(base, packs), within=base):
            wanted.append((one, base))
    return wanted


def fetch_registry(url: str, store: ContentStore, progress: Any = None,
                   cancel: Any = None,
                   cache_dir: str | None = None) -> list[ContentPack]:
    """Fetch a registry bundle and return the packs it declares.

    What an application does when it is pointed at somebody else's set of
    content: the bundle is a document and its thumbnails, so this gives a
    chooser a picture of everything on offer while downloading none of it.

    The bundle is kept under the store's own registries directory, so a later
    run finds it without being pointed at it again, and its packs are held to
    the same namespacing rule as the shipped registry's. It is kept only once
    it loads: one that does not is refused and leaves the store as it was, so
    a bad URL or a publisher's typo cannot stop the store's other registries
    loading.
    """
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme != 'https' and not (scheme == 'http' and resolver.is_local(url)):
        raise IOError('a registry is fetched over https, and %s is not an '
                      'https URL' % (resolver.safe_url(url),))
    log.info('fetching the registry at %s', resolver.safe_url(url))
    try:
        downloaded = resolver.fetch_to_cache(
            url, cache_dir=cache_dir, max_bytes=REGISTRY_LIMIT,
            progress=progress, cancel=cancel,
            redirects=resolver.PUBLIC_HOSTS)
    except resolver.FetchCancelled as error:
        raise Cancelled(str(error)) from error
    except resolver.ResourceTooLarge as error:
        raise TooLarge('the registry at %s is over the %d bytes a registry is '
                       'fetched under: %s' % (resolver.safe_url(url),
                                              REGISTRY_LIMIT, error)) from error
    except http.client.HTTPException as error:
        raise IOError('the registry at %s did not arrive: %r'
                      % (resolver.safe_url(url), error)) from error
    kept = store.registry_path(url)
    packs = catalog.load_bundle(downloaded, store.unpacked_registry(kept))
    store.keep_registry(downloaded, url)
    return packs


def wanted_for(chosen: ContentPack, packs: Sequence[ContentPack],
               store: ContentStore) -> list[ContentPack]:
    """What choosing ``chosen`` has to fetch: it, and what it needs.

    Asked of the machine as it stands, and asked **within the choice**: content
    a pack is incomplete without unpacks into that pack's own directory, so the
    same art already under one track is still to be written under another. A
    caller hands the answer to :class:`FetchJob` with the same ``within``.
    """
    return store.missing(catalog.with_needed(chosen, packs), within=chosen)


def fetch_pack(pack: ContentPack, store: ContentStore,
               progress: Any = None, cancel: Any = None,
               cache_dir: str | None = None,
               within: ContentPack | None = None) -> str:
    """Fetch and unpack one pack; return its content root.

    A pack already on this machine is returned without touching the network, and
    its progress is reported as finished, so a caller drawing a bar sees it fill
    whether or not anything was downloaded.

    ``within`` names the pack this one is being fetched for, and is what puts a
    needed pack's content under it rather than beside it -- see
    :meth:`~OpenGLContext.contentpacks.store.ContentStore.directory_for`. The
    download is cached under the URL either way, so art shared by four tracks
    is transferred once.

    The digest is checked before anything is written into the store, so a
    truncated or substituted download is a refusal here rather than content that
    renders wrongly later, and the unpacking is bounded by what the pack said
    its size was -- a cap on the transfer says nothing about what the transfer
    expands to.
    """
    existing = store.root_for(pack, within)
    if existing is not None:
        _report(progress, pack.approximate_bytes, pack.approximate_bytes)
        return existing
    log.info('fetching %s (%s)', pack.key, pack.human_size())
    downloaded = _download(pack, cache_dir, progress, cancel)
    try:
        archive.check_digest(downloaded, pack.sha256)
    except archive.DigestMismatch:
        # A publisher replacing a release's assets keeps the URL and changes
        # the bytes, and the download cache is keyed by URL: the copy here may
        # be the build before this one, or a damaged file. Fetch it once more.
        log.info('the cached copy of %s is not the one the registry names; '
                 'fetching it again', pack.key)
        _evict(downloaded)
        downloaded = _download(pack, cache_dir, progress, cancel)
        try:
            archive.check_digest(downloaded, pack.sha256)
        except archive.DigestMismatch:
            _evict(downloaded)
            raise
    try:
        return store.install(pack, downloaded, within, cancel=cancel)
    except resolver.FetchCancelled as error:
        raise Cancelled(str(error)) from error


def _download(pack: ContentPack, cache_dir: str | None,
              progress: resolver.Progress | None,
              cancel: resolver.Cancel | None) -> str:
    """The pack's archive in the download cache, fetched if it is not there."""
    try:
        return resolver.fetch_to_cache(
            pack.url, cache_dir=cache_dir,
            max_bytes=fetch_limit(pack.approximate_bytes),
            progress=progress, cancel=cancel,
            redirects=resolver.PUBLIC_HOSTS)
    except resolver.FetchCancelled as error:
        raise Cancelled(str(error)) from error
    except resolver.ResourceTooLarge as error:
        raise TooLarge('%s is larger than the %d bytes its declared size of %s '
                       'allows: %s' % (pack.key,
                                       fetch_limit(pack.approximate_bytes),
                                       pack.human_size(), error)) from error
    except http.client.HTTPException as error:
        # A transfer cut short (IncompleteRead) or a URL http.client will not
        # send; an IOError, like every other way the content does not arrive.
        raise IOError('%s did not arrive: %r' % (pack.key, error)) from error


def _evict(path: str) -> None:
    """Remove a cached download that is not the one wanted."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


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

    def __init__(self,
                 packs: Sequence[ContentPack | tuple[ContentPack,
                                                     ContentPack | None]],
                 store: ContentStore,
                 fetch: Fetch | None = None, cache_dir: str | None = None,
                 on_progress: Callable[[], None] | None = None,
                 within: ContentPack | None = None) -> None:
        #: Each pack, and the pack it lands within (None for its own place).
        #: ``packs`` may give that pairing itself, as :func:`base_fetches`
        #: does; a bare pack takes ``within``.
        self.wanted: list[tuple[ContentPack, ContentPack | None]] = [
            one if isinstance(one, tuple) else (one, within) for one in packs]
        self.packs = [one for one, _ in self.wanted]
        self.store = store
        self.cache_dir = cache_dir
        #: The pack this job was started for, where it was started for one.
        self.within = within
        self._fetch_within: Callable[[ContentPack, ContentPack | None,
                                      resolver.Progress, resolver.Cancel], str]
        if fetch is not None:
            self._fetch_within = (
                lambda pack, _within, progress, cancel: fetch(
                    pack, progress, cancel))
        else:
            self._fetch_within = (
                lambda pack, where, progress, cancel: fetch_pack(
                    pack, store, progress, cancel, cache_dir=cache_dir,
                    within=where))
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
        if ended:
            if cancelled:
                self.state = 'cancelled'
            elif failed is not None:
                self.state = 'failed: %s' % (failed,)
            else:
                self.state, self.fraction = 'done', 1.0
        if changed and self.on_progress is not None:
            self.on_progress()

    def _work(self) -> None:
        """The worker. Everything it writes is written under the lock."""
        try:
            for pack, within in self.wanted:
                with self._lock:
                    if self._stop:
                        raise Cancelled('the download was stopped')
                    self._current = pack.title
                    before = self._done_bytes
                root = self._fetch_within(pack, within, self._progress(before),
                                          self._stopping)
                with self._lock:
                    self._roots.append(root)
                    self._done_bytes = before + pack.approximate_bytes
        except Cancelled:
            with self._lock:
                self._cancelled = True
        except BaseException as error:      # published, never raised at a caller
            log.warning('fetching content failed: %s', error, exc_info=error)
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
