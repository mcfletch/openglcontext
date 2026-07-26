"""Saving key bindings, and finding out what a key is already bound to.

A rebinding a player makes has to survive the process, so it goes in a file
under the **per-user app-data directory** -- the same place the default font and
backend preferences live -- as JSON, which someone will eventually edit by hand
and should not have to fight.

Loading is deliberately forgiving.  A file naming a mode or a command this build
no longer has is a saved file from an older version, not an error, so the
entries that still resolve are applied and the rest are dropped.  The
alternative -- refusing the whole file -- loses every binding a player set
because one of them went away.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

__all__ = ['bindings_path', 'save_bindings', 'load_bindings', 'reset_bindings',
           'conflicts', 'BINDINGS_FILE']

#: What the file is called, wherever it is kept.
BINDINGS_FILE = 'keybindings.json'


def bindings_path(directory: Optional[str] = None) -> str:
    """Where bindings are saved: a named directory, or the user's own."""
    if directory is None:
        from OpenGLContext.contextconfig import ContextConfigMixin
        directory = ContextConfigMixin.getUserAppDataDirectory()
    return os.path.join(directory, BINDINGS_FILE)


def save_bindings(navigation: Any, path: Optional[str] = None) -> str:
    """Write every declared binding to ``path``; returns where it went."""
    path = path or bindings_path()
    stored: Dict[str, Dict[str, Any]] = {}
    for mode_name, binding in navigation.binding_table():
        stored.setdefault(mode_name, {})[binding.command] = {
            'keys': list(binding.keys),
            'modifier': str(binding.modifier),
        }
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, mode=0o770, exist_ok=True)
    with open(path, 'w') as target:
        json.dump(stored, target, indent=2, sort_keys=True)
    return path


def load_bindings(navigation: Any, path: Optional[str] = None) -> bool:
    """Apply a saved file; False if there was nothing usable to apply."""
    path = path or bindings_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path) as source:
            stored = json.load(source)
    except (ValueError, OSError):
        log.warning("ignoring unreadable key bindings in %s", path,
                    exc_info=True)
        return False
    if not isinstance(stored, dict):
        return False
    for mode in navigation.modes():
        saved = stored.get(str(mode.name))
        if not isinstance(saved, dict):
            continue
        for binding in mode.bindings:
            entry = saved.get(binding.command)
            if not isinstance(entry, dict):
                continue
            binding.keys = [str(key) for key in entry.get('keys', ())]
            binding.modifier = str(entry.get('modifier', ''))
    return True


def reset_bindings(navigation: Any, path: Optional[str] = None) -> None:
    """Put every binding back to the mode's declared default.

    The keys are copied into the existing ``KeyBinding`` nodes rather than the
    list being replaced, so anything already holding one -- a settings row, a
    HUD, a watcher -- keeps working and sees the change.

    The saved file goes too: a reset that a restart undoes is not a reset.
    """
    for mode in navigation.modes():
        defaults = {binding.command: binding
                    for binding in mode.defaultBindings()}
        kept = []
        for binding in mode.bindings:
            default = defaults.pop(binding.command, None)
            if default is None:
                continue            # a command this build no longer declares
            binding.keys = list(default.keys)
            binding.modifier = str(default.modifier)
            kept.append(binding)
        # Anything the defaults declare and the mode had lost comes back.
        kept.extend(defaults.values())
        if len(kept) != len(mode.bindings):
            mode.bindings = kept
    target = path or bindings_path()
    try:
        os.remove(target)
    except OSError:
        pass


def conflicts(table: Sequence[Tuple[str, Any]], key: str, modifier: str = '',
              mode: Optional[str] = None, skip: Any = None
              ) -> List[Tuple[str, Any]]:
    """Bindings that already claim a key, and would fight over it.

    Two things narrow what counts as a fight:

    * **Only within one mode.**  Walking and flying are never in force at the
      same moment, so both binding `w` to forward is the normal case rather
      than a clash.  Pass ``mode`` to ask about one mode's own bindings.
    * **The modifier is part of the binding's identity**, not a detail: `ctrl`
      and an arrow tilts the view while the arrow alone walks, and both are
      wanted at once.

    ``skip`` excludes the binding being edited, which would otherwise report a
    conflict with itself.
    """
    found = []
    for mode_name, binding in table:
        if binding is skip:
            continue
        if mode is not None and mode_name != mode:
            continue
        if str(binding.modifier) != str(modifier):
            continue
        if key in list(binding.keys):
            found.append((mode_name, binding))
    return found
