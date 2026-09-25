"""Which module opened each file a test's code opened, held to the sanctioned openers.

A path a document names reaches the disk through the engine's resolver, which
holds it to the directory it was named in; a file written goes through
:mod:`OpenGLContext.atomicfiles`. A module that opens a file by any other
route is either a new opener nobody has checked or a path that skipped the
check. The static rules (OGC111, OGC121) and the checked path types reach
most of these; this reaches what they cannot, at run time, over everything a
suite exercises.

:class:`OpenAudit` is a ``sys.audit`` hook for the ``open`` event. For each
open it finds the innermost frame of the stack in one of the *checked*
packages, and records a finding where that frame's module is not one of the
*sanctioned* openers. What is not recorded:

- an open made where no checked module is on the stack (the test's own
  files, pytest's, a library used directly);
- an open made by the import system or by traceback formatting on a checked
  module's behalf (a module imported inside a function, a traceback logged);
- a file inside a checked package's own directory: the package's data;
- a file descriptor rather than a path.

A module names a sanctioned opener by its dotted name, and a package's name
sanctions every module in it. The hook costs about a microsecond an open.

Under pytest the plugin installs it for the session when the ``open_audit``
ini setting is ``fail`` (each test that opened a file from outside the
sanctioned openers fails) or ``report`` (every such open is listed once at
the end of the run); ``open_audit_checked`` and ``open_audit_sanctioned``
list the packages and the modules. See ``docs/testing.rst``.
"""
from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from types import FrameType
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = ['OpenAudit', 'OpenFinding', 'installed']

#: Modules whose frames between an open and the checked module mean the open
#: was made on that module's behalf, not by it: importing, and formatting a
#: traceback from source.
_ON_BEHALF = ('importlib', '_frozen_importlib', '_frozen_importlib_external',
              'zipimport', 'linecache', 'traceback', 'tokenize', 'inspect')


def _within(name: str, prefixes: Tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + '.') for prefix in prefixes)


@dataclass(frozen=True)
class OpenFinding:
    """One open from a module outside the sanctioned openers."""

    module: str
    line: int
    path: str
    mode: str

    def __str__(self) -> str:
        return '%s:%d opened %r (%s)' % (self.module, self.line, self.path, self.mode)


class OpenAudit:
    """The ``open`` audit hook, and what it has found since it was last taken.

    ``checked`` are the packages (or modules) whose opens are audited,
    ``sanctioned`` the modules (or packages) that may open files.
    """

    def __init__(self, checked: Iterable[str], sanctioned: Iterable[str]) -> None:
        self.checked = tuple(checked)
        self.sanctioned = tuple(sanctioned)
        self.enabled = False
        self._found: List[OpenFinding] = []
        self._lock = threading.Lock()
        self._roots = self._package_roots()

    def _package_roots(self) -> Tuple[str, ...]:
        roots = []
        for name in self.checked:
            module = sys.modules.get(name.split('.')[0])
            where = getattr(module, '__file__', None)
            if where:
                roots.append(os.path.dirname(os.path.realpath(where)) + os.sep)
        return tuple(roots)

    def hook(self, event: str, args: Tuple[Any, ...]) -> None:
        """The audit hook: record an ``open`` the rules do not allow."""
        if event != 'open' or not self.enabled:
            return
        path = args[0]
        if not isinstance(path, (str, bytes, os.PathLike)):
            return
        opener = self.opener(sys._getframe(1))
        if opener is None:
            return
        module, line = opener
        text = os.fsdecode(path)
        if self._roots and os.path.realpath(text).startswith(self._roots):
            return
        mode = args[1] if len(args) > 1 and isinstance(args[1], str) else 'r'
        with self._lock:
            self._found.append(OpenFinding(module, line, text, mode))

    def opener(self, frame: Optional[FrameType]) -> Optional[Tuple[str, int]]:
        """The unsanctioned checked module an open is attributed to, and its line.

        None where the innermost checked frame is sanctioned, where the open is
        made on its behalf, or where no checked module is on the stack.
        """
        on_behalf = False
        while frame is not None:
            name = frame.f_globals.get('__name__', '') or ''
            if _within(name, self.checked):
                if on_behalf or _within(name, self.sanctioned):
                    return None
                return name, frame.f_lineno
            if _within(name, _ON_BEHALF):
                on_behalf = True
            frame = frame.f_back
        return None

    def take(self) -> List[OpenFinding]:
        """What was found since the last take, and forget it."""
        with self._lock:
            found, self._found = self._found, []
        return found


_INSTALLED: Dict[str, OpenAudit] = {}


def installed(checked: Iterable[str], sanctioned: Iterable[str]) -> OpenAudit:
    """The process's :class:`OpenAudit`, installed as an audit hook once.

    An audit hook cannot be removed, so one is installed for the process and
    later calls set what it checks and switch it on.
    """
    audit = _INSTALLED.get('audit')
    if audit is None:
        audit = _INSTALLED['audit'] = OpenAudit(checked, sanctioned)
        sys.addaudithook(audit.hook)
    else:
        audit.checked, audit.sanctioned = tuple(checked), tuple(sanctioned)
        audit._roots = audit._package_roots()
    audit.enabled = True
    return audit
