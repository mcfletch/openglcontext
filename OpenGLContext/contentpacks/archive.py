"""Unpacking an archive nobody here wrote, and checking it is the one meant.

A content pack arrives from a URL a registry named, so its member names are
untrusted input: an archive decides for itself what it calls its entries, and
a name like ``../../.bashrc`` is a write outside the directory it was extracted
into. Every name is therefore resolved against the destination **before
anything is written**, and one that lands outside stops the whole extraction --
an archive carrying such a name is not one to take the rest of on trust.

:func:`write` is the other half, for whoever publishes a pack: an archive whose
bytes are a function of the content and of nothing else, so the digest a
registry records is one a rebuild reaches again.
"""

from __future__ import annotations

import gzip
import hashlib
import os
import sys
import tarfile
import zipfile
from collections.abc import Sequence

from OpenGLContext import atomicfiles
from OpenGLContext.loaders import resolver

__all__ = ['DigestMismatch', 'EPOCH', 'LFS_POINTER', 'MAX_ENTRIES',
           'MAX_EXPANSION', 'MINIMUM_UNPACKED', 'TooLarge', 'UnreadableArchive',
           'UnsafeArchive', 'check_digest', 'digest', 'extract', 'unpacked_limit', 'write']

#: How much of a file is hashed at a time. A base pack is tens of megabytes and
#: is not held in memory to digest it.
BLOCK = 1024 * 1024

#: How much larger than its download a pack may unpack to. Content is mostly
#: already compressed -- PNG, GLB, Ogg -- so a real pack barely expands at all:
#: a baked glisteel track is 57 MB unpacked against 48 MB compressed, which is
#: 1.2. Ten is generous for anything genuinely compressible and nowhere near
#: what an archive of zeroes reaches, which is a thousandfold and upwards.
MAX_EXPANSION = 10

#: The smallest unpacking budget, so a small pack is not held to a small number.
MINIMUM_UNPACKED = 64 * 1024 * 1024

#: How many members one archive may hold. A million empty files is a denial of
#: service of its own -- inodes, directory entries and the time to write them --
#: and no content pack here is within two orders of magnitude of it.
MAX_ENTRIES = 100000

#: The modification time every entry :func:`write` stores carries, and the one
#: in the gzip header above them. The date is arbitrary and fixed: what matters
#: is that it does not move, since a time that did would put the hour of the
#: build into a digest that is meant to describe the content.
EPOCH = 1600000000


class TooLarge(IOError):
    """More than the caller allowed: to download, or to unpack to.

    An ``IOError`` like every other way this can fail, so that a caller
    reporting "the content did not arrive" has one family to catch.
    """


def unpacked_limit(approximate_bytes: int) -> int:
    """How much a pack of this download size may write."""
    return max(int(approximate_bytes * MAX_EXPANSION), MINIMUM_UNPACKED)


class UnsafeArchive(IOError):
    """An entry would have been written outside the destination."""


class UnreadableArchive(IOError):
    """The file is not the archive it was said to be, or is damaged."""


class DigestMismatch(IOError):
    """The bytes that arrived are not the bytes the registry named."""


def extract(path: str, directory: str, kind: str,
            max_bytes: int | None = MINIMUM_UNPACKED,
            max_entries: int = MAX_ENTRIES,
            cancel: resolver.Cancel | None = None) -> str:
    """Extract the archive at ``path`` into ``directory``; return ``directory``.

    ``kind`` is ``zip`` or ``tar``, from the pack's own declaration rather than
    from the file name -- a release asset may be called anything. A tarball's
    compression is detected by the reader, so one ``tar`` covers ``.tar``,
    ``.tar.gz``, ``.tar.bz2`` and ``.tar.xz``.

    What the archive would write is judged before it writes any of it. A cap
    on the download says nothing about the unpacking: a megabyte of zeroes
    deflates to almost nothing, so an archive well inside any transfer limit can
    fill a disk. ``max_bytes`` is that second limit -- see
    :func:`unpacked_limit` -- and defaults to :data:`MINIMUM_UNPACKED`; pass
    None for no limit. ``max_entries`` bounds the count, since a million empty
    files costs nothing to send and plenty to write.

    The sizes are read from the archive's own headers, and a tarball's headers
    are counted and summed as they are read, so an archive over either limit
    is refused at the first header past it and nothing is created. Both readers
    are bounded by the declared sizes when they extract, so a header that
    understates its member yields a short file or a checksum failure rather
    than an overrun.

    ``cancel`` is asked before each member is written; when it answers true
    the extraction stops with :class:`~OpenGLContext.loaders.resolver.FetchCancelled`,
    leaving whatever was written so far for the caller's staging to discard.
    """
    if kind == 'zip':
        _extract_zip(path, directory, max_bytes, max_entries, cancel)
    elif kind == 'tar':
        _extract_tar(path, directory, max_bytes, max_entries, cancel)
    else:
        raise ValueError('no reader for a %r archive' % (kind,))
    return directory


def _check_cancel(cancel: resolver.Cancel | None) -> None:
    if cancel is not None and cancel():
        raise resolver.FetchCancelled('the unpacking was cancelled')


class _Budget:
    """The entry count and byte total an archive is allowed, spent as its
    headers are read."""

    def __init__(self, path: str, max_bytes: int | None,
                 max_entries: int) -> None:
        self.path, self.max_bytes, self.max_entries = path, max_bytes, max_entries
        self.entries = self.total = 0

    def spend(self, size: int) -> None:
        self.entries += 1
        if self.entries > self.max_entries:
            raise TooLarge('%s holds more than %d entries, the most one archive '
                           'is unpacked from' % (self.path, self.max_entries))
        self.total += size
        if self.max_bytes is not None and self.total > self.max_bytes:
            raise TooLarge('%s would unpack to more than %d bytes, the most it '
                           'is allowed' % (self.path, self.max_bytes))


def write(directory: str, path: str, compresslevel: int = 9) -> str:
    """Archive the tree at ``directory`` as the ``.tar.gz`` ``path``; its path.

    The bytes are a function of the content and of nothing else, so the digest
    a registry records is one a rebuild reaches again: entries are written in
    sorted order, each carrying :data:`EPOCH` rather than its own modification
    time, no owner, no group and one mode; and the gzip container above them
    carries the same fixed time and none of the name it was given. Two builds
    of the same files, on different machines and in different checkouts, reach
    the same digest, so a release rebuilt from its tag can be shown to be the
    release.

    Files only: directories arrive as the parents of the entries inside them,
    which is what a pack is. Names are stored relative to ``directory``, so a
    pack unpacks as its own root wherever the store puts it. A symbolic link
    anywhere in the tree is refused with its name, since an installer refuses
    a link and a linked directory would otherwise be left out; copy the file
    into the tree instead.

    A Git LFS pointer is refused too, naming every one found: a checkout made
    without ``git lfs pull`` holds a small text file in place of each large
    one, under the same name, and an archive of those would install and fail
    only when a file is opened.

    The archive is written beside ``path`` and moved into place when complete,
    so a refused or interrupted write leaves the previous build where it was.
    """
    names = _entries(directory)
    _refuse_pointers(directory, names)
    with atomicfiles.staged_file(path, 'wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw,
                           compresslevel=compresslevel,
                           mtime=EPOCH) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|') as handle:
                for name in names:
                    full = os.path.join(directory, *name.split('/'))
                    info = handle.gettarinfo(full, name)
                    info.mtime = EPOCH
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    info.mode = 0o644
                    with open(full, 'rb') as content:
                        handle.addfile(info, content)
    return path


def _entries(directory: str) -> list[str]:
    """The names ``write`` stores, in the order it stores them.

    The disk's own order is whatever a filesystem happened to hand back, and it
    differs between two checkouts of one tree; sorting is what makes the archive
    the same archive on both.

    Sorted as a tar stores them -- separated by ``/`` -- rather than as the
    platform spells a path. Windows' ``\\`` sorts after the digits and the
    capitals where ``/`` sorts before them, so sorting the local spelling would
    put ``a/b`` and ``a0`` in one order here and the other order there, and the
    same content would digest differently on the two.

    A symbolic link, to a file or to a directory, is an ``IOError`` naming it.
    """
    names: list[str] = []
    for root, directories, files in os.walk(directory):
        for leaf in directories + files:
            full = os.path.join(root, leaf)
            if os.path.islink(full):
                raise IOError(
                    '%s is a symbolic link; a pack holds files, so copy what '
                    'it points at into the tree' % (full,))
        names.extend(
            os.path.relpath(os.path.join(root, leaf), directory).replace(
                os.sep, '/') for leaf in files)
    return sorted(names)


#: How a Git LFS pointer file begins.
LFS_POINTER = b'version https://git-lfs.github.com/spec/v1'


def _refuse_pointers(directory: str, names: Sequence[str]) -> None:
    """An ``IOError`` naming every Git LFS pointer among ``names``."""
    found = []
    for name in names:
        with open(os.path.join(directory, *name.split('/')), 'rb') as handle:
            if handle.read(len(LFS_POINTER)) == LFS_POINTER:
                found.append(name)
    if found:
        raise IOError(
            '%d files under %s are Git LFS pointers rather than content (%s); '
            'run `git lfs pull` in the checkout and build again'
            % (len(found), directory, ', '.join(found[:5])
               + (', ...' if len(found) > 5 else '')))


def digest(path: str) -> str:
    """The SHA-256 of the file at ``path``, as a registry states it.

    Read in blocks: a base pack is tens of megabytes and is not held in memory
    to hash it.
    """
    found = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(BLOCK), b''):
            found.update(block)
    return found.hexdigest()


def check_digest(path: str, expected: str) -> None:
    """Refuse ``path`` unless it hashes to ``expected``; an empty one asks
    nothing.

    A pack hosted by somebody else states no digest, and there is nothing to
    check. One we publish states its own, and a truncated or substituted
    download is then a refusal here rather than a rendering fault somewhere
    later.
    """
    if not expected:
        return
    found = digest(path)
    if found != expected.lower():
        raise DigestMismatch(
            '%s hashes to %s, and the registry names %s'
            % (path, found, expected.lower()))


def _extract_zip(path: str, directory: str, max_bytes: int | None,
                 max_entries: int, cancel: resolver.Cancel | None) -> None:
    root = os.path.realpath(directory)
    budget = _Budget(path, max_bytes, max_entries)
    try:
        with zipfile.ZipFile(path) as zip_file:
            entries = zip_file.infolist()
            for entry in entries:
                budget.spend(entry.file_size)
                _refuse_escape(entry.filename, root, directory)
            os.makedirs(directory, exist_ok=True)
            for entry in entries:
                _check_cancel(cancel)
                zip_file.extract(entry, directory)
    except zipfile.BadZipFile as error:
        raise UnreadableArchive('%s is not readable as a zip: %s'
                                % (path, error)) from error


def _require_filters(path: str) -> None:
    """Refuse to read a tarball on an interpreter without extraction filters.

    ``filter='data'`` is what refuses links out of the tree and device nodes,
    and it arrived in Python 3.10.12, 3.11.4 and 3.12. On an earlier patch
    release there is no safe way to extract somebody else's tarball.
    """
    if not hasattr(tarfile, 'data_filter'):
        raise UnreadableArchive(
            '%s is a tarball, and this Python (%s) has no tarfile extraction '
            'filters to unpack one safely; they are in Python 3.10.12, 3.11.4, '
            '3.12 and later' % (path, sys.version.split()[0]))


def _extract_tar(path: str, directory: str, max_bytes: int | None,
                 max_entries: int, cancel: resolver.Cancel | None) -> None:
    """Extract a tarball, refusing any entry that escapes ``directory``.

    ``filter='data'`` is what refuses the entries a name check cannot see: a
    symbolic link pointing out of the tree, a hard link to a file outside it, a
    device node, and the permission and ownership bits an archive should not be
    choosing. Its refusals are raised as :class:`UnsafeArchive` so a caller has
    one exception to catch whatever the container was.

    The headers are read one at a time and spent against the budget as they
    arrive; reading past a member in a compressed stream decompresses it, so
    stopping at the first overrun is what bounds the work as well as the disk.
    """
    _require_filters(path)
    root = os.path.realpath(directory)
    budget = _Budget(path, max_bytes, max_entries)
    try:
        with tarfile.open(path) as tar:
            members = []
            for member in tar:
                budget.spend(member.size)
                _refuse_escape(member.name, root, directory)
                members.append(member)
            os.makedirs(directory, exist_ok=True)
            for member in members:
                _check_cancel(cancel)
                tar.extract(member, directory, filter='data')
    except tarfile.FilterError as error:
        raise UnsafeArchive('%s holds an entry that would not be safe to '
                            'write: %s' % (path, error)) from error
    except (tarfile.TarError, EOFError) as error:
        # EOFError as well as TarError: a download that stopped early reaches
        # the decompressor rather than the tar reader, and gzip and xz raise
        # EOFError where an uncompressed or bzip2 tarball raises ReadError.
        raise UnreadableArchive('%s is not readable as a tarball: %s'
                                % (path, error)) from error


def _refuse_escape(name: str, root: str, directory: str) -> None:
    """Refuse ``name`` unless it resolves to somewhere inside ``root``."""
    target = os.path.realpath(os.path.join(root, name))
    if os.path.isabs(name) or not (target == root
                                   or target.startswith(root + os.sep)):
        raise UnsafeArchive('archive entry %r would be written outside %s'
                            % (name, directory))
