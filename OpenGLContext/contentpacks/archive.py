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
import tarfile
import zipfile

__all__ = ['DigestMismatch', 'EPOCH', 'MAX_ENTRIES', 'MAX_EXPANSION',
           'MINIMUM_UNPACKED', 'TooLarge', 'UnreadableArchive', 'UnsafeArchive',
           'check_digest', 'digest', 'extract', 'unpacked_limit', 'write']

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
            max_bytes: int | None = None,
            max_entries: int = MAX_ENTRIES) -> str:
    """Extract the archive at ``path`` into ``directory``; return ``directory``.

    ``kind`` is ``zip`` or ``tar``, from the pack's own declaration rather than
    from the file name -- a release asset may be called anything. A tarball's
    compression is detected by the reader, so one ``tar`` covers ``.tar``,
    ``.tar.gz``, ``.tar.bz2`` and ``.tar.xz``.

    **What the archive would write is judged before it writes any of it.** A cap
    on the download says nothing about the unpacking: a megabyte of zeroes
    deflates to almost nothing, so an archive well inside any transfer limit can
    fill a disk. ``max_bytes`` is that second limit -- see
    :func:`unpacked_limit` -- and ``max_entries`` bounds the count, since a
    million empty files costs nothing to send and plenty to write.

    The sizes are read from the archive's own headers, which is what makes the
    refusal free: nothing is created when one is refused. Both readers here are
    bounded by those declared sizes when they extract, so a header that
    understates its member yields a short file or a checksum failure rather than
    an overrun.
    """
    if kind == 'zip':
        _extract_zip(path, directory, max_bytes, max_entries)
    elif kind == 'tar':
        _extract_tar(path, directory, max_bytes, max_entries)
    else:
        raise ValueError('no reader for a %r archive' % (kind,))
    return directory


def _refuse_the_size(sizes: list[int], max_bytes: int | None,
                     max_entries: int, path: str) -> None:
    """Refuse an archive by what it would write, before it writes anything."""
    if len(sizes) > max_entries:
        raise TooLarge('%s holds %d entries, and %d is the most one archive is '
                       'unpacked from' % (path, len(sizes), max_entries))
    total = sum(sizes)
    if max_bytes is not None and total > max_bytes:
        raise TooLarge('%s would unpack to %d bytes, over the %d it is allowed'
                       % (path, total, max_bytes))


def write(directory: str, path: str, compresslevel: int = 9) -> str:
    """Archive the tree at ``directory`` as the ``.tar.gz`` ``path``; its path.

    **The bytes are a function of the content and of nothing else**, which is
    what makes the digest a registry records worth recording: entries are
    written in sorted order, each carrying :data:`EPOCH` rather than its own
    modification time, no owner, no group and one mode; and the gzip container
    above them carries the same fixed time and none of the name it was given.
    Two builds of the same files, on different machines and in different
    checkouts, reach the same digest -- so a release rebuilt from its tag can be
    shown to be the release, and a pack that did change says so.

    Files only: directories arrive as the parents of the entries inside them,
    which is what a pack is. Names are stored relative to ``directory``, so a
    pack unpacks as its own root wherever the store puts it.
    """
    with open(path, 'wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw,
                           compresslevel=compresslevel,
                           mtime=EPOCH) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|') as handle:
                for name in _entries(directory):
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
    """
    return sorted(
        os.path.relpath(os.path.join(root, leaf), directory).replace(os.sep,
                                                                    '/')
        for root, _, files in os.walk(directory) for leaf in files)


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

    A pack hosted by somebody who may replace the file under the same URL states
    no digest, and there is nothing to check. One we publish states its own, and
    a truncated or substituted download is then a refusal here rather than a
    rendering fault somewhere later.
    """
    if not expected:
        return
    found = digest(path)
    if found != expected.lower():
        raise DigestMismatch(
            '%s hashes to %s, and the registry names %s'
            % (path, found, expected.lower()))


def _extract_zip(path: str, directory: str, max_bytes: int | None,
                 max_entries: int) -> None:
    root = os.path.abspath(directory)
    try:
        with zipfile.ZipFile(path) as zip_file:
            entries = zip_file.infolist()
            for entry in entries:
                _refuse_escape(entry.filename, root, directory)
            _refuse_the_size([entry.file_size for entry in entries],
                             max_bytes, max_entries, path)
            os.makedirs(directory, exist_ok=True)
            zip_file.extractall(directory)
    except zipfile.BadZipFile as error:
        raise UnreadableArchive('%s is not readable as a zip: %s'
                                % (path, error)) from error


def _extract_tar(path: str, directory: str, max_bytes: int | None,
                 max_entries: int) -> None:
    """Extract a tarball, refusing any entry that escapes ``directory``.

    ``filter='data'`` is what refuses the entries a name check cannot see: a
    symbolic link pointing out of the tree, a hard link to a file outside it, a
    device node, and the permission and ownership bits an archive should not be
    choosing. Its refusals are raised as :class:`UnsafeArchive` so a caller has
    one exception to catch whatever the container was.
    """
    root = os.path.abspath(directory)
    try:
        with tarfile.open(path) as tar:
            members = tar.getmembers()
            for member in members:
                _refuse_escape(member.name, root, directory)
            _refuse_the_size([member.size for member in members],
                             max_bytes, max_entries, path)
            os.makedirs(directory, exist_ok=True)
            tar.extractall(directory, filter='data')
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
    target = os.path.abspath(os.path.join(root, name))
    if os.path.isabs(name) or not (target == root
                                   or target.startswith(root + os.sep)):
        raise UnsafeArchive('archive entry %r would be written outside %s'
                            % (name, directory))
