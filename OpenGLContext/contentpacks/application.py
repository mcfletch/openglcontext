"""One application's content: its registry, its store, and where its art is.

Every application that fetches its art asks the same four things: which packs
does it offer, where is its store, what must a first run fetch, and where is
the art now. :class:`Application` answers them from a namespace and the
registry the application ships:

    >>> from OpenGLContext.contentpacks import Application
    >>> CONTENT = Application('glisteel', 'glisteel/packs.json',   # doctest: +SKIP
    ...                       base='glisteel/cars', fallback='glisteel/assets')
    >>> CONTENT.ensure_base(consent=ask_on_console())          # doctest: +SKIP
    >>> ART = CONTENT.library()                                 # doctest: +SKIP

Where the art is, is asked at each use rather than stored when a module is
imported: a first run imports the application before its base pack has been
fetched, and a path computed then names a directory the pack is not in.
:meth:`Application.base_directory` and :meth:`Application.library` answer
from the machine as it is when they are called.

:func:`ask_on_console` and :func:`console_progress` are the consent and the
progress of a command-line first run; a window shows
:meth:`Application.base_job` on :class:`OpenGLContext.ui.contentscreen.ContentScreen`.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, TextIO

from . import catalog, fetch
from .pack import ContentPack, human_bytes
from .store import CONTENT_OVERRIDE, ContentStore

if TYPE_CHECKING:
    from OpenGLContext.loaders.assets import AssetLibrary

__all__ = ['Application', 'Consent', 'NotInstalled', 'ask_on_console',
           'console_progress']

#: What ``consent`` is: shown the packs a fetch would bring, it answers
#: whether to go ahead.
Consent = Callable[[Sequence[ContentPack]], bool]


class NotInstalled(LookupError):
    """The application's own art is not on this machine, and nothing ships it."""


class Application:
    """One application's content packs.

    ``namespace`` names the store and the packs, ``catalog`` is the path of
    the registry the application ships, and ``base`` the key of the pack
    holding its own art, if it has one. ``fallback`` is a directory holding
    that art without a pack (an application's ``assets`` in a checkout, say),
    used while the pack is not installed and only if it exists. ``root`` puts
    the store somewhere other than the per-user default, and ``cache_dir`` the
    download cache (the resolver's per-user one by default). ``added`` also
    reads the registries added to the store
    (:meth:`ContentStore.load_registries`).
    """

    def __init__(self, namespace: str, catalog: str, base: str | None = None,
                 fallback: str | None = None, root: str | None = None,
                 added: bool = False, cache_dir: str | None = None) -> None:
        self.namespace = namespace
        self.catalog = catalog
        self.base = base
        self.fallback = fallback
        self.root = root
        self.added = added
        self.cache_dir = cache_dir
        self._registry: list[ContentPack] | None = None
        self._library: AssetLibrary | None = None

    def __repr__(self) -> str:
        return 'Application(%r, %r)' % (self.namespace, self.catalog)

    def store(self, root: str | None = None) -> ContentStore:
        """The application's store: at ``root``, else where it was made to be."""
        return ContentStore(self.namespace, root=root or self.root)

    def registry(self) -> list[ContentPack]:
        """Every pack this build offers, read once and kept.

        The shipped registry, and the store's added ones where the application
        reads them. :meth:`reload` reads them again.
        """
        if self._registry is None:
            groups = [catalog.load(self.catalog)]
            if self.added:
                groups.append(self.store().load_registries())
            self._registry = catalog.merge(*groups)
        return self._registry

    def reload(self) -> None:
        """Read the registries again at the next :meth:`registry`."""
        self._registry = None

    def base_pack(self) -> ContentPack | None:
        """The pack holding the application's own art, or None."""
        if self.base is None:
            return None
        return catalog.pack_for_key(self.base, self.registry())

    def base_directory(self, store: ContentStore | None = None) -> str:
        """Where the application's own art is, as of now.

        The base pack's root once it is installed, else ``fallback`` where
        that directory exists. :class:`NotInstalled` otherwise, naming the
        pack and the ways to put it here.
        """
        pack = self.base_pack()
        if pack is not None:
            root = (store or self.store()).root_for(pack)
            if root is not None:
                return root
        if self.fallback is not None and os.path.isdir(self.fallback):
            return self.fallback
        raise NotInstalled(
            '%s is not on this machine: fetch it (a first run with a network '
            'connection does), or point %s at a directory holding %s/%s'
            % (pack.title if pack is not None else self.base,
               CONTENT_OVERRIDE, self.namespace,
               pack.directory if pack is not None else '...'))

    def library(self) -> AssetLibrary:
        """The application's art as an asset library, one for the process.

        Its root is :meth:`base_directory`, asked at each use, so models are
        read from the base pack from the moment it is installed.
        """
        # Imported here: the loaders are for a program that draws, and a
        # release command or a fetch has no use for them.
        from OpenGLContext.loaders.assets import AssetLibrary
        if self._library is None:
            self._library = AssetLibrary(self.base_directory)
        return self._library

    def needed_to_start(self, store: ContentStore | None = None
                        ) -> list[ContentPack]:
        """What a first run has to fetch before the application can start.

        Each base pack not on this machine and what it needs; empty on every
        run after the first. The list to ask consent for.
        """
        return fetch.missing_base(self.registry(), store or self.store())

    def base_job(self, store: ContentStore | None = None,
                 on_progress: Callable[[], None] | None = None,
                 cache_dir: str | None = None) -> fetch.FetchJob:
        """A download of :meth:`needed_to_start`, run off the frame loop.

        Each pack lands within the base pack that needs it, as
        :func:`~OpenGLContext.contentpacks.fetch.base_fetches` pairs them.
        """
        where = store or self.store()
        return fetch.FetchJob(fetch.base_fetches(self.registry(), where), where,
                              cache_dir=cache_dir or self.cache_dir,
                              on_progress=on_progress)

    def ensure_base(self, consent: Consent | None = None,
                    progress: Callable[[int, int | None], None] | None = None,
                    store: ContentStore | None = None,
                    cache_dir: str | None = None) -> bool:
        """Fetch what a first run needs, in the foreground; whether it is here.

        True when nothing was missing or everything arrived; False when
        ``consent`` declined. ``consent`` is shown the packs first, and without
        one they are fetched. A failed download raises what
        :func:`~OpenGLContext.contentpacks.fetch.fetch_pack` raises: an
        ``IOError`` for content that did not arrive, whole.
        """
        where = store or self.store()
        wanted = fetch.base_fetches(self.registry(), where)
        if not wanted:
            return True
        if consent is not None and not consent(self.needed_to_start(where)):
            return False
        for pack, within in wanted:
            fetch.fetch_pack(pack, where, progress=progress, cancel=None,
                             cache_dir=cache_dir or self.cache_dir,
                             within=within)
        return True


def ask_on_console(assume_yes: bool = False, stream: TextIO | None = None,
                   answer: Callable[[str], str] | None = None) -> Consent:
    """A consent that lists the packs on ``stream`` and asks yes or no.

    Each pack's title, size and terms, then the total. ``assume_yes`` prints
    the list and goes ahead, for a script. ``answer`` reads the reply
    (``input`` by default). End of input, or anything but a yes, declines.
    """
    def consent(packs: Sequence[ContentPack]) -> bool:
        out = stream if stream is not None else sys.stdout
        total = sum(pack.approximate_bytes for pack in packs)
        out.write('This needs a download of %s:\n' % (human_bytes(total),))
        for pack in packs:
            out.write('  %s (%s) - %s\n' % (pack.title, pack.human_size(),
                                             pack.copyright))
        if assume_yes:
            out.flush()
            return True
        out.flush()
        try:
            said = (answer or input)('Download it now? [y/N] ')
        except EOFError:
            return False
        return said.strip().lower() in ('y', 'yes')
    return consent


def console_progress(stream: TextIO | None = None,
                     step: int = 5) -> Callable[[int, int | None], None]:
    """A progress callback printing every ``step`` per cent on one line."""
    shown = [-step]

    def progress(done: int, total: int | None) -> None:
        if not total:
            return
        at = min(100, int(done * 100 / total))
        if at >= shown[0] + step:
            shown[0] = at
            out = stream if stream is not None else sys.stdout
            out.write('\r  %3d%%' % (at,))
            out.flush()
    return progress
