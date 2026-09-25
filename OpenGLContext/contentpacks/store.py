"""Where one application's content packs live on this machine.

A store is named after the application, because two games installed together
share the engine's download cache but not their content. It answers "is this
pack already here" before anything asks the user or touches the network, so a
pack is fetched once and every later run simply finds it.

Asking where a file belongs creates no directory; :meth:`ContentStore.install`
is what writes content, and it makes what it needs.

An install is staged: the archive is unpacked beside the pack's directory and
moved into place once it is whole, under a lock so two processes of one
application do not unpack into one directory at once, and with a record of
what was installed (the key, the URL and the digest) that
:meth:`ContentStore.root_for` compares with the registry's current entry.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import tempfile
import urllib.parse
from typing import Any, Iterable, Sequence

from OpenGLContext import atomicfiles, userpaths
from OpenGLContext.loaders import resolver

from . import archive
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

#: The directory inside a pack's directory holding what was installed there:
#: one record per pack, named after its key.
RECORDS = '.contentpacks'


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
        return os.path.join(self.root, PACKS, *_place(owner))

    def root_for(self, pack: ContentPack,
                 within: ContentPack | None = None) -> str | None:
        """This pack's unpacked content root, or None if it is not here.

        The searched directories are tried before the store, so a machine
        pointed at a local copy never consults what a previous run downloaded.
        They are laid out the same way -- ``<namespace>/<directory>`` -- since a
        flat one would be the hole :meth:`directory_for` closes. Content there
        is somebody's own copy, and its marker is all that is asked of it.

        In the store, an install left a record of the pack it installed, and
        that record has to be this pack: the same digest where the pack names
        one, else the same URL. A registry that names a rebuilt pack therefore
        reads it as not here, and it is fetched again. A directory holding the
        marker and no record is taken as placed there by hand.

        With ``within``, the question is whether the content is under *that*
        pack -- the marker is the needed pack's own, and the directory is the
        one that needs it, so one track having the art says nothing about
        another.
        """
        owner = within if within is not None else pack
        for base in self.search:
            where = os.path.join(base, *_place(owner))
            if _unpacked(where, pack.marker):
                return where
        where = self.directory_for(pack, within)
        if not _unpacked(where, pack.marker):
            return None
        record = _read_record(where, pack.key)
        if record is not None and not _describes(record, pack):
            return None
        return where

    def install(self, pack: ContentPack, path: str,
                within: ContentPack | None = None, replace: bool = False,
                cancel: resolver.Cancel | None = None) -> str:
        """Unpack the archive at ``path`` as ``pack``; its content root.

        The caller has checked the archive's digest. It is unpacked into a
        staging directory beside the pack's own and moved into place when it is
        whole, so an extraction that is refused, cancelled or killed part way
        leaves no pack behind. A pack of its own replaces its directory as a
        whole, so nothing of a previous version survives; one unpacked
        ``within`` another has the files its previous version installed there
        removed first, and its record written last.

        Two processes installing into one directory take turns, and the second
        finds the first one's pack and returns it. ``replace`` installs even
        where the pack is already here. ``cancel`` is asked between members.
        """
        where = self.directory_for(pack, within)
        with atomicfiles.file_lock(_lock_for(where)):
            if not replace and self._here(pack, within):
                return where
            limit = archive.unpacked_limit(pack.approximate_bytes)
            if within is None:
                with atomicfiles.staged_directory(where) as staging:
                    archive.extract(path, staging, pack.archive,
                                    max_bytes=limit, cancel=cancel)
                    _write_record(staging, pack, files=None)
            else:
                self._install_within(pack, path, where, limit, cancel)
        return where

    def _here(self, pack: ContentPack, within: ContentPack | None) -> bool:
        """Whether the store itself -- not a searched directory -- holds it."""
        where = self.directory_for(pack, within)
        if not _unpacked(where, pack.marker):
            return False
        record = _read_record(where, pack.key)
        return record is None or _describes(record, pack)

    def _install_within(self, pack: ContentPack, path: str, where: str,
                        limit: int, cancel: resolver.Cancel | None) -> None:
        """Merge a needed pack's files into the directory of the one needing it.

        A record saying the install is under way is written before the first
        file moves, and the complete one after the last, so an install that
        stops between the two reads as not here.
        """
        parent, name = os.path.split(where)
        os.makedirs(where, exist_ok=True)
        staging = tempfile.mkdtemp(prefix='.%s%s' % (name, atomicfiles.PARTIAL),
                                   dir=parent)
        try:
            archive.extract(path, staging, pack.archive, max_bytes=limit,
                            cancel=cancel)
            files = _files_under(staging)
            previous = _read_record(where, pack.key)
            _write_record(where, pack, files=files, complete=False)
            if previous is not None:
                _remove_files(where, previous.get('files') or ())
            for name in files:
                target = os.path.join(where, *name.split('/'))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(os.path.join(staging, *name.split('/')), target)
            _write_record(where, pack, files=files)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def remove(self, pack: ContentPack,
               within: ContentPack | None = None) -> None:
        """Remove this pack's content from the store.

        A pack of its own takes its directory with it, and everything under
        it. One unpacked ``within`` another loses the files its record lists
        and nothing else, so the pack that needed it stays whole. Nothing in a
        searched directory is touched.
        """
        where = self.directory_for(pack, within)
        with atomicfiles.file_lock(_lock_for(where)):
            if within is None:
                atomicfiles.remove_directory(where)
                return
            record = _read_record(where, pack.key)
            if record is not None:
                _remove_files(where, record.get('files') or ())
                os.remove(_record_path(where, pack.key))

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

    def registry_path(self, url: str) -> str:
        """Where a registry bundle fetched from ``url`` is kept.

        Keyed by the whole URL, not by its last segment. Two sources both
        publishing ``registry.zip`` would otherwise be one file here, the second
        fetch silently replacing the first and every pack it had offered. The
        URL's own name is kept after the key so somebody looking in the store
        can still tell what is there and remove it by hand.
        """
        key = hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]
        named = os.path.basename(urllib.parse.urlparse(url).path)
        stem = os.path.splitext(named)[0] or 'registry'
        return os.path.join(self.root, REGISTRIES, '%s-%s.zip' % (key, stem))

    def keep_registry(self, path: str, url: str) -> str:
        """Copy a fetched registry bundle in beside the added ones; its path.

        Kept at :meth:`registry_path`, replacing the file there whole: a second
        fetch of the same URL is how a registry is refreshed.
        """
        return atomicfiles.copy_file(path, self.registry_path(url))

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


def _place(pack: ContentPack) -> tuple[str, str]:
    """The namespace and directory a pack's content is under, without case.

    A filesystem that ignores case -- macOS's by default, and Windows' -- makes
    ``Glisteel`` and ``glisteel`` one directory, so they are one everywhere.
    """
    return pack.namespace.casefold(), pack.directory.casefold()


def _unpacked(where: str, marker: str) -> bool:
    """Whether a pack's content is sitting in ``where``.

    The marker is what proves it; where a pack names no marker, the directory
    existing and holding something is what there is to go on.
    """
    if marker:
        return os.path.exists(os.path.join(where, marker))
    return os.path.isdir(where) and bool(os.listdir(where))


def _lock_for(where: str) -> str:
    """The lock file for installs into ``where``: beside it, so it survives the
    directory being replaced."""
    parent, name = os.path.split(where)
    return os.path.join(parent, '.%s.lock' % (name,))


def _record_path(where: str, key: str) -> str:
    return os.path.join(where, RECORDS,
                        key.casefold().replace('/', '+') + '.json')


def _read_record(where: str, key: str) -> dict[str, Any] | None:
    """The install record for ``key`` in ``where``, or None if there is none.

    One that cannot be read is answered as an install that did not finish.
    """
    path = _record_path(where, key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return {'complete': False}
    return record if isinstance(record, dict) else {'complete': False}


def _write_record(where: str, pack: ContentPack, files: list[str] | None,
                  complete: bool = True) -> None:
    record: dict[str, Any] = {'key': pack.key, 'url': pack.url,
                              'sha256': pack.sha256, 'complete': complete}
    if files is not None:
        record['files'] = files
    atomicfiles.write_text(_record_path(where, pack.key),
                           json.dumps(record, indent=1, sort_keys=True))


def _describes(record: dict[str, Any], pack: ContentPack) -> bool:
    """Whether an install record is of this pack, finished."""
    if record.get('complete') is not True:
        return False
    if pack.sha256:
        return bool(record.get('sha256') == pack.sha256)
    return bool(record.get('url') == pack.url)


def _files_under(directory: str) -> list[str]:
    """Every file under ``directory``, as ``/``-separated relative names."""
    return sorted(
        os.path.relpath(os.path.join(root, leaf), directory).replace(os.sep, '/')
        for root, _, files in os.walk(directory) for leaf in files)


def _remove_files(where: str, names: Iterable[str]) -> None:
    """Remove the files a record lists, and directories they leave empty.

    A name from a record is checked to stay inside ``where`` before anything
    is removed, since a record is a file on disk like any other.
    """
    root = os.path.realpath(where)
    emptied: set[str] = set()
    for name in names:
        target = os.path.realpath(os.path.join(where, *str(name).split('/')))
        if not target.startswith(root + os.sep):
            continue
        try:
            os.remove(target)
        except FileNotFoundError:
            continue
        emptied.add(os.path.dirname(target))
    for directory in sorted(emptied, key=len, reverse=True):
        while directory != root and directory.startswith(root + os.sep):
            try:
                os.rmdir(directory)
            except OSError:
                break
            directory = os.path.dirname(directory)
