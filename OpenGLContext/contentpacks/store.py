"""Where one application's content packs live on this machine.

A store is named after the application, because two games installed together
share the engine's download cache but not their content. It answers "is this
pack already here" before anything asks the user or touches the network, so a
pack is fetched once and every later run simply finds it.

Nothing here creates a directory: asking where a file belongs is not a reason to
make one. The fetch that writes content makes what it needs.
"""

from __future__ import annotations

import glob
import hashlib
import os
import shutil
import urllib.parse
from typing import Iterable, Sequence

from OpenGLContext import userpaths

from .pack import ContentPack

__all__ = ['CONTENT_OVERRIDE', 'ContentStore']

#: Directories searched before the store, separated by the platform's path
#: separator. A packaged build, an air-gapped machine or a CI job points this at
#: a local copy of the content and fetches nothing.
CONTENT_OVERRIDE = 'OPENGLCONTEXT_CONTENT'

#: What the store is called under the application's own directory.
CONTENT = 'content'

#: Where content lands, under the store. Packs sit under this by namespace,
#: which is what keeps them out of :data:`REGISTRIES` however a namespace is
#: spelled.
PACKS = 'packs'

#: Where registries a build did not ship are read from, under the store.
REGISTRIES = 'registries'

#: Where a registry bundle's content is extracted, under that.
UNPACKED = '.unpacked'


class ContentStore:
    """The content directory of one application.

    ``search`` names directories looked in before the store, and defaults to
    whatever :data:`CONTENT_OVERRIDE` holds. A caller that has its own answer --
    a packaged application shipping content beside its executable -- passes it
    rather than setting an environment variable.
    """

    def __init__(self, application: str, root: str | None = None,
                 search: Sequence[str] | None = None) -> None:
        self.application = application
        self.root = root or os.path.join(
            userpaths.appdatadirectory(), application, CONTENT)
        self.search = list(search) if search is not None else _from_environment()

    def directory_for(self, pack: ContentPack,
                      within: ContentPack | None = None) -> str:
        """Where this pack unpacks, whether or not it is there yet.

        **Under the pack's namespace, not under its bare ``directory``.** Only a
        pack's *key* is namespaced by the catalogue, and a key is not where
        content lands: a registry may name any ``directory`` it likes, so an
        added one could otherwise declare the name a shipped pack uses and write
        over its content. Partitioning by namespace makes that impossible rather
        than forbidden, and leaves two packs of the *same* publisher free to
        share a tree on purpose -- which is how a world and the art it needs
        arrive as one directory.

        ``within`` is that case: content another pack is incomplete without
        unpacks into *that* pack's directory rather than into one of its own,
        because the paths inside a world resolve against the world's own root.
        The archive is fetched once and cached; what repeats is the extraction,
        so a second track carrying the same art costs disk and no download.
        """
        owner = within if within is not None else pack
        return os.path.join(self.root, PACKS, owner.namespace, owner.directory)

    def root_for(self, pack: ContentPack,
                 within: ContentPack | None = None) -> str | None:
        """This pack's unpacked content root, or None if it is not here.

        The searched directories are tried before the store, so a machine
        pointed at a local copy never consults what a previous run downloaded.
        They are laid out the same way -- ``<namespace>/<directory>`` -- since a
        flat one would be the hole :meth:`directory_for` closes.

        With ``within``, the question is whether the content is under *that*
        pack -- the marker is the needed pack's own, and the directory is the
        one that needs it, so one track having the art says nothing about
        another.
        """
        owner = within if within is not None else pack
        for base in self.search:
            where = os.path.join(base, owner.namespace, owner.directory)
            if _unpacked(where, pack.marker):
                return where
        where = os.path.join(self.root, PACKS, owner.namespace, owner.directory)
        return where if _unpacked(where, pack.marker) else None

    def installed(self, packs: Iterable[ContentPack],
                  within: ContentPack | None = None) -> list[ContentPack]:
        """Those of ``packs`` already on this machine, in the order asked."""
        return [pack for pack in packs
                if self.root_for(pack, within) is not None]

    def missing(self, packs: Iterable[ContentPack],
                within: ContentPack | None = None) -> list[ContentPack]:
        """Those of ``packs`` that would have to be fetched."""
        return [pack for pack in packs if self.root_for(pack, within) is None]

    def registries(self) -> list[str]:
        """Registry files added to this store, in a settled order.

        What lets a community set, a mirror or a work-in-progress bake be
        offered by the same chooser without a release. Either form counts: a
        plain ``.json`` whose pictures sit beside it, or a ``.zip`` bundling
        both. Held to the same namespacing rule as the shipped one.
        """
        where = os.path.join(self.root, REGISTRIES)
        found: list[str] = []
        for suffix in ('*.json', '*.zip'):
            found.extend(glob.glob(os.path.join(where, suffix)))
        return sorted(found)

    def keep_registry(self, path: str, url: str) -> str:
        """Copy a fetched registry bundle in beside the added ones; its path.

        **Keyed by the whole URL, not by its last segment.** Two sources both
        publishing ``registry.zip`` would otherwise be one file here, the second
        fetch silently replacing the first and every pack it had offered. The
        URL's own name is kept after the key so somebody looking in the store
        can still tell what is there and remove it by hand.

        A second fetch of the same URL lands on the same file, which is how a
        registry is refreshed.
        """
        key = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
        named = os.path.basename(urllib.parse.urlparse(url).path)
        stem = os.path.splitext(named)[0] or 'registry'
        where = os.path.join(self.root, REGISTRIES)
        os.makedirs(where, exist_ok=True)
        kept = os.path.join(where, '%s-%s.zip' % (key, stem))
        shutil.copyfile(path, kept)
        return kept

    def unpacked_registry(self, path: str) -> str:
        """Where a registry bundle's content is extracted to.

        Named after the bundle rather than hashed, so somebody looking at the
        store can tell which registry a directory of thumbnails came from.
        """
        name = os.path.splitext(os.path.basename(path))[0]
        return os.path.join(self.root, REGISTRIES, UNPACKED, name)

    def load_registries(self) -> list[ContentPack]:
        """Every pack the added registries declare, bundles unpacked.

        A registry that will not load is refused with its own name in the
        message rather than skipped: one silently dropped is one nobody can see
        the absence of, which is the whole reason validation is strict.
        """
        from . import catalog        # here: catalog reads a store's registries
        packs: list[ContentPack] = []
        for path in self.registries():
            try:
                if path.endswith('.zip'):
                    packs.extend(catalog.load_bundle(
                        path, self.unpacked_registry(path)))
                else:
                    packs.extend(catalog.load(path))
            except catalog.BadCatalog as error:
                raise catalog.BadCatalog('%s: %s' % (path, error)) from error
        return packs


def _from_environment() -> list[str]:
    """The directories :data:`CONTENT_OVERRIDE` names, if any."""
    named = os.environ.get(CONTENT_OVERRIDE, '')
    return [part for part in named.split(os.pathsep) if part]


def _unpacked(where: str, marker: str) -> bool:
    """Whether a pack's content is sitting in ``where``.

    The marker is what proves it: a fetch that died half way leaves a directory
    behind, and a directory is not content. Where a pack names no marker, the
    directory existing and holding something is the whole of the proof there is.
    """
    if marker:
        return os.path.exists(os.path.join(where, marker))
    return os.path.isdir(where) and bool(os.listdir(where))
