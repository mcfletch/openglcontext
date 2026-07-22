"""Forced-exit helper that flushes coverage first.

Regression/capture code runs inside a GL render callback in a subprocess and
has to terminate the process *now* -- a normal ``sys.exit`` raises SystemExit
that the windowing event loop swallows, so the historical code called
``os._exit``. But ``os._exit`` skips ``atexit`` handlers, which is exactly how
``coverage run`` flushes its data file; the result was subprocess coverage
never being written (the ~9% figure in PROJECT-PLAN). This helper saves the
active coverage data explicitly, then hard-exits, keeping both properties.
"""

import os

__all__ = ['flush_and_exit']


def flush_and_exit(code: int) -> None:
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
