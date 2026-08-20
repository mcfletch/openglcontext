"""The file a session recorder writes into.

JSON lines, one record to a line, each on disk before the next is offered: a
game killed outright -- which is how a game being diagnosed usually ends --
keeps everything up to the moment it went.

Two things a journal must never be: the reason a game will not start, and the
reason a disk fills.  A path that cannot be written is a warning and a disabled
journal.  A session that runs all day meets a ceiling, past which the ordinary
traffic of input and frame times stops while exceptions, marks and the ending
still get through -- the ceiling exists to keep the failure, not to lose it.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

__all__ = ['DEFAULT_MAX_BYTES', 'ESSENTIAL', 'SessionJournal', 'as_data',
           'default_path']

#: How large a journal may grow before the ordinary traffic stops.  A session
#: at sixty frames a second writes a few kilobytes a minute, so this is days of
#: play; it is here for the recording nobody switched off again.
DEFAULT_MAX_BYTES = 128 * 1024 * 1024

#: The records that are written whatever the file already weighs.  Everything
#: the ceiling drops can be summarised from what is already there; none of
#: these can be reconstructed from anything.
ESSENTIAL = frozenset(('header', 'exception', 'mark', 'end', 'truncated'))


def as_data(value: Any) -> Any:
    """``value`` as something JSON can hold.

    A game marks where somebody was and how much was left of them, and both of
    those are numbers out of numpy rather than out of Python -- an array and a
    scalar that ``json`` refuses, which would cost the mark that was made to
    explain the failure.  Arrays become their numbers and scalars become theirs;
    anything else becomes its text, which is worth more to a reader than the
    record not being there.
    """
    for name in ('tolist', 'item'):
        method = getattr(value, name, None)
        if callable(method):
            try:
                return method()
            except (TypeError, ValueError):
                pass
    return str(value)


class SessionJournal:
    """One session's records, appended to a file as they are made.

    path -- where to write. Parent directories are created.
    header -- what to say about this session on the first line: whatever the
        caller knows about the application, beyond the process facts recorded
        here.
    max_bytes -- the ceiling; ``None`` for none.
    """

    def __init__(self, path: Any, header: Optional[Dict[str, Any]] = None,
                 max_bytes: Optional[int] = DEFAULT_MAX_BYTES,
                 now: Any = None) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._now = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
        #: True once opening or writing has failed; nothing is attempted after.
        self.disabled = False
        #: True once the ceiling has been reached.
        self.saturated = False
        #: Records written, and bytes they took.
        self.written = 0
        self.bytes = 0
        self._handle: Any = None
        self._open(header or {})

    # -- the file ---------------------------------------------------------
    def _open(self, header: Dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = self.path.open('w')
        except OSError as error:
            log.warning('cannot record telemetry to %s (%s); '
                        'this session will not be recorded', self.path, error)
            self.disabled = True
            return
        record = {
            'kind': 'header',
            'version': 1,
            'started': self._now().isoformat(),
            'pid': os.getpid(),
            'argv': list(sys.argv),
            'python': sys.version.split()[0],
            'platform': sys.platform,
        }
        record.update(header)
        self(record)

    def __call__(self, record: Dict[str, Any]) -> None:
        """Append one record.  This is what a recorder is given as its writer."""
        if self.disabled:
            return
        kind = record.get('kind')
        if self.saturated and kind not in ESSENTIAL:
            return
        try:
            line = json.dumps(record, default=as_data) + '\n'
        except (TypeError, ValueError):
            # One record that will not serialise -- a mark carrying something
            # that is not data -- must not take the rest of the session with it.
            log.debug('cannot serialise a telemetry record: %r', record)
            return
        try:
            self._handle.write(line)
            self._handle.flush()
        except (OSError, ValueError) as error:
            log.warning('cannot append to the telemetry journal %s (%s); '
                        'no more will be recorded', self.path, error)
            self.disabled = True
            return
        self.written += 1
        self.bytes += len(line)
        if (self.max_bytes is not None and not self.saturated
                and self.bytes >= self.max_bytes and kind not in ESSENTIAL):
            self.saturated = True
            log.warning('the telemetry journal %s has reached %d bytes; '
                        'recording exceptions and marks only from here',
                        self.path, self.bytes)
            self({'kind': 'truncated', 'bytes': self.bytes})

    def close(self) -> None:
        """Finish with the file. Safe to call twice."""
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                log.debug('could not close %s', self.path, exc_info=True)
        self.disabled = True


def default_path(name: str = 'session') -> Path:
    """Where a journal goes when the caller named no file.

    Under the user's application-data directory, dated and stamped with the
    process, so successive runs accumulate rather than overwriting each other:
    the interesting session is rarely the one that has just finished.
    """
    from OpenGLContext import userpaths
    try:
        root = Path(userpaths.appdatadirectory())
    except OSError:
        import tempfile
        root = Path(tempfile.gettempdir())
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    return root / 'OpenGLContext' / 'telemetry' / (
        '%s-%s-%d.jsonl' % (name, stamp, os.getpid()))
