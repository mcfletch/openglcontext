"""Write the call stack at a chosen point to a file

For a call that happens too often, or too deep inside a toolkit, to sit a
debugger in: :func:`logContext` appends the frames that reached it to
:data:`LOG_NAME` in the current directory.
"""
import traceback
from typing import IO, Optional

#: Name of the file the frames are appended to, in the current directory.
LOG_NAME = 'callcontext.txt'

_log: Optional[IO[str]] = None


def _file() -> IO[str]:
    """The open log, made on the first call rather than at import"""
    global _log
    if _log is None:
        _log = open(LOG_NAME, 'w')
    return _log


def close() -> None:
    """Close the log, so a later call starts a new one"""
    global _log
    if _log is not None:
        _log.close()
        _log = None


def logContext() -> None:
    """Log the calling context to the context log-file"""
    log = _file()
    for (path, line, function, text) in traceback.extract_stack()[:-1]:
        log.write("%s %s:%s %s\n" % (function, path, line, text))
    log.write('____________________________________________\n')
    log.flush()
