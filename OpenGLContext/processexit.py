"""Ending the process at once, with what it wrote flushed first.

A capture, the regression harness and a game's own bounded run end the process
from inside a GL render callback, and have to end it *now*: ``sys.exit`` raises
``SystemExit``, which the windowing event loop swallows, so the exit is
``os._exit``. That skips the interpreter's shutdown, which is where buffered
standard output and error are written and where ``atexit`` handlers run --
``coverage run`` writes its data file from one. So :func:`flush_and_exit`
saves any active coverage data and flushes both streams before the hard exit.

This module imports nothing of the engine, so a shipped game ends through it
without importing the test machinery.
"""

import contextlib
import importlib
import logging
import os
import sys
from types import ModuleType
from typing import NoReturn

try:
    _coverage: ModuleType | None = importlib.import_module('coverage')
except ImportError:   # an optional tool: without it there is nothing to save
    _coverage = None

__all__ = ['flush_and_exit']

log = logging.getLogger(__name__)


def flush_and_exit(code: int) -> NoReturn:
    """Save any coverage data, flush standard output and error, then exit with ``code``.

    The exit happens whatever the save raises (it is logged), and whether or
    not a stream can be flushed: one replaced by None, closed, or a pipe
    nobody reads any more.
    """
    if _coverage is not None:
        try:
            collector = _coverage.Coverage.current()
            if collector is not None:
                collector.save()
        except Exception:
            log.exception('coverage data was not saved before the exit')
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError, ValueError):
            stream.flush()
    os._exit(code)
