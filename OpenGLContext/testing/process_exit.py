"""Forced-exit helper that flushes coverage first.

Regression and capture code runs inside a GL render callback in a subprocess
and has to end the process *now*: ``sys.exit`` raises ``SystemExit``, which the
windowing event loop swallows, so the exit has to be ``os._exit``. That skips
``atexit`` handlers, which is how ``coverage run`` writes its data file, so the
active coverage data is saved explicitly before the hard exit and a subprocess
still reports what it ran.
"""

import os
from typing import NoReturn

__all__ = ['flush_and_exit']


def flush_and_exit(code: int) -> NoReturn:
    """Flush any active coverage collector, then hard-exit with ``code``.

    Safe to call when coverage is not running (the save is skipped).
    """
    try:
        import coverage

        cov = coverage.Coverage.current()
        if cov is not None:
            cov.save()
    except Exception:
        pass
    os._exit(code)
