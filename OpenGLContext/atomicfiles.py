"""Writing a file or a directory so that it appears whole or not at all.

A write interrupted part way -- a full disk, a crash, a killed daemon thread,
Ctrl-C -- leaves whatever it had written so far, and a later run that finds the
path takes it for the finished thing. Everything here writes somewhere else
first, in the same directory so the two are on one filesystem, and moves the
result into place with one rename once it is complete:

* :func:`write_bytes`, :func:`write_text` and :func:`copy_file` replace a
  file's content, and :func:`staged_file` is the same for a caller that writes
  its content itself;
* :func:`staged_directory` builds a directory and swaps it in for the one at
  the path, so what was there before is gone as a whole rather than
  overwritten file by file;
* :func:`file_lock` is held around a check-then-write by two processes that
  may both be doing it, such as two copies of a game installing one content
  pack.

    >>> from OpenGLContext import atomicfiles
    >>> with atomicfiles.file_lock(where + '.lock'):          # doctest: +SKIP
    ...     if not installed(where):
    ...         with atomicfiles.staged_directory(where) as staging:
    ...             unpack_into(staging)
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
import threading
import time
from typing import IO, Any, Iterator

__all__ = ['copy_file', 'file_lock', 'replace_directory', 'staged_directory',
           'staged_file', 'write_bytes', 'write_text']

#: What a staging directory's name starts with after the target's own name.
PARTIAL = '.partial-'

#: What a directory being replaced is renamed to while its successor moves in.
RETIRED = '.retired-'

#: How long a lock waits between attempts where the platform cannot block.
_POLL_SECONDS = 0.05


@contextlib.contextmanager
def staged_file(path: str, mode: str = 'wb',
                encoding: str | None = None) -> Iterator[IO[Any]]:
    """An open file whose content replaces ``path`` when the block completes.

    The file is a temporary one beside ``path``; an exception inside the block
    removes it and leaves ``path`` as it was. An existing file's permission bits
    are kept, and a new one gets what the umask gives any other new file.
    """
    if 'w' not in mode:
        raise ValueError('a staged file is written: %r has no "w"' % (mode,))
    directory, name = os.path.split(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, prefix='.%s.' % (name,),
                                         suffix='.tmp')
    try:
        with os.fdopen(handle, mode, encoding=encoding) as target:
            yield target
            target.flush()
            os.fsync(target.fileno())
        _give_mode(temporary, path)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def write_bytes(path: str, data: bytes) -> str:
    """Replace the file at ``path`` with ``data``; returns ``path``."""
    with staged_file(path, 'wb') as target:
        target.write(data)
    return path


def write_text(path: str, text: str, encoding: str = 'utf-8') -> str:
    """Replace the file at ``path`` with ``text``; returns ``path``."""
    with staged_file(path, 'w', encoding=encoding) as target:
        target.write(text)
    return path


def copy_file(source: str, path: str) -> str:
    """Replace the file at ``path`` with a copy of ``source``; returns ``path``."""
    with open(source, 'rb') as origin, staged_file(path, 'wb') as target:
        shutil.copyfileobj(origin, target)
    return path


@contextlib.contextmanager
def staged_directory(path: str) -> Iterator[str]:
    """A new, empty directory that takes the place of ``path`` on completion.

    The block fills the directory it is given. When it completes, whatever was
    at ``path`` is removed and the staged directory is renamed into its place;
    when it raises, the staged directory is removed and ``path`` is untouched.
    A reader sees the old directory, then briefly none, then the new one --
    never a mixture of the two.

    Staging directories are named ``.<name>.partial-*`` beside ``path``. Any
    left by a process that was killed are removed when the next one begins, so
    this is to be used under :func:`file_lock` wherever two processes can stage
    the same path at once.
    """
    parent, name = os.path.split(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    _remove_leftovers(parent, name)
    staging = tempfile.mkdtemp(prefix='.%s%s' % (name, PARTIAL), dir=parent)
    try:
        yield staging
        replace_directory(staging, path)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def replace_directory(source: str, path: str) -> str:
    """Move the directory ``source`` to ``path``, removing what was there.

    ``source`` must be on the filesystem ``path`` is on, which a sibling is.
    The old directory is renamed aside first and removed once the new one is in
    place, so a failure to move the new one in puts the old one back.
    """
    parent, name = os.path.split(os.path.abspath(path))
    retired = None
    if os.path.lexists(path):
        retired = tempfile.mkdtemp(prefix='.%s%s' % (name, RETIRED), dir=parent)
        os.rmdir(retired)
        os.replace(path, retired)
    try:
        os.replace(source, path)
    except BaseException:
        if retired is not None:
            os.replace(retired, path)
        raise
    if retired is not None:
        shutil.rmtree(retired, ignore_errors=True)
    return path


def _remove_leftovers(parent: str, name: str) -> None:
    """Remove staging and retired directories a killed process left for ``name``."""
    prefixes = ('.%s%s' % (name, PARTIAL), '.%s%s' % (name, RETIRED))
    try:
        entries = os.listdir(parent)
    except OSError:
        return
    for entry in entries:
        if entry.startswith(prefixes):
            shutil.rmtree(os.path.join(parent, entry), ignore_errors=True)


def _give_mode(temporary: str, path: str) -> None:
    """Give ``temporary`` the permission bits ``path`` has, or a new file's."""
    try:
        shutil.copymode(path, temporary)
    except OSError:
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(temporary, 0o666 & ~umask)


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: str) -> threading.Lock:
    """One in-process lock per lock file, whatever the platform's lock does
    between two handles of one process."""
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(path, threading.Lock())


@contextlib.contextmanager
def file_lock(path: str) -> Iterator[None]:
    """Hold an exclusive lock on the file ``path`` for the length of the block.

    Between processes and between threads alike: a second holder waits until
    the first leaves its block. The file is created if it is not there and is
    left in place afterwards, since removing a lock file races with the next
    process opening it. The lock goes with the process, so one killed while
    holding it releases it.
    """
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _thread_lock(path):
        handle = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _lock(handle)
            try:
                yield
            finally:
                _unlock(handle)
        finally:
            os.close(handle)


if sys.platform == 'win32':                                 # pragma: no cover
    import msvcrt

    def _lock(handle: int) -> None:
        while True:
            try:
                msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(_POLL_SECONDS)

    def _unlock(handle: int) -> None:
        os.lseek(handle, 0, os.SEEK_SET)
        msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(handle: int) -> None:
        fcntl.flock(handle, fcntl.LOCK_EX)

    def _unlock(handle: int) -> None:
        fcntl.flock(handle, fcntl.LOCK_UN)
