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
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

__all__ = ['bindings_path', 'save_bindings', 'load_bindings', 'reset_bindings',
           'snapshot', 'restore', 'forget_saved', 'conflicts', 'BINDINGS_FILE']

#: What the file is called, wherever it is kept.
BINDINGS_FILE = 'keybindings.json'


def bindings_path(directory: Optional[str] = None) -> str:
    """Where bindings are saved: a named directory, or the user's own."""
    if directory is None:
        from OpenGLContext.contextconfig import ContextConfigMixin
        directory = ContextConfigMixin.getUserAppDataDirectory()
    return os.path.join(directory, BINDINGS_FILE)


def save_bindings(navigation: Any, path: Optional[str] = None) -> str:
    """Write every declared binding to ``path``; returns where it went.

    **Written whole or not at all.**  What is at stake is every binding the
    player has, and ``open(path, 'w')`` truncates before it writes: a save
    interrupted half-way through leaves a file that will not parse, which
    ``load_bindings`` reports by logging a warning and quietly starting from
    the defaults.  So the new file is written beside the old one and moved over
    it, which is atomic on every platform this runs on.
    """
    path = path or bindings_path()
    stored: Dict[str, Dict[str, Any]] = {}
    for mode_name, binding in navigation.binding_table():
        stored.setdefault(mode_name, {})[binding.command] = {
            'keys': [str(key) for key in binding.keys],
            'modifier': str(binding.modifier),
        }
    directory = os.path.dirname(path) or '.'
    # The player's own directory, and only theirs: it is under the per-user
    # app-data location and nothing else has any business reading it.
    os.makedirs(directory, mode=0o700, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, prefix='.keybindings-',
                                         suffix='.json')
    try:
        with os.fdopen(handle, 'w') as target:
            json.dump(stored, target, indent=2, sort_keys=True)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:                         # pragma: no cover - vanished
            pass
        raise
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
            where = '%s.%s' % (mode.name, binding.command)
            keys = _keyList(entry.get('keys'), where)
            if keys is not None:
                binding.keys = keys
            binding.modifier = _modifier(entry.get('modifier', ''), where)
    return True


def _keyList(value: Any, where: str) -> Optional[List[str]]:
    """A saved ``keys`` entry, or None if it is not one.

    A string is refused rather than iterated: ``"wasd"`` is somebody meaning
    one binding and getting four, which is the mistake a file this docstring
    invites people to edit by hand actually produces.
    """
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        log.warning("ignoring the keys for %s: expected a list of key names, "
                    "found %r", where, value)
        return None
    return [str(key) for key in value]


def _modifier(value: Any, where: str) -> str:
    """A saved ``modifier``, or empty if it is not one this build knows.

    An unrecognised modifier is worse than none: nothing ever reports it as
    held, so the binding is silently unreachable for the rest of the session.
    """
    from OpenGLContext.move.modes import MODIFIER_INDEX
    if not isinstance(value, str):
        log.warning("ignoring the modifier for %s: expected a name, found %r",
                    where, value)
        return ''
    if value and value not in MODIFIER_INDEX:
        log.warning("ignoring the modifier %r for %s: expected one of %s",
                    value, where, ', '.join(sorted(MODIFIER_INDEX)))
        return ''
    return value


def snapshot(navigation: Any) -> Dict[str, Dict[str, Any]]:
    """Every binding as it stands, in a form :func:`restore` can put back.

    What makes the binding page's Cancel real.  Plain data rather than the
    nodes themselves, so a reset that rebuilds a mode's bindings can still be
    undone.
    """
    kept: Dict[str, Dict[str, Any]] = {}
    for mode_name, binding in navigation.binding_table():
        kept.setdefault(mode_name, {})[str(binding.command)] = {
            'keys': [str(key) for key in binding.keys],
            'modifier': str(binding.modifier),
        }
    return kept


def restore(navigation: Any, kept: Dict[str, Dict[str, Any]]) -> None:
    """Put the bindings back as :func:`snapshot` found them."""
    for mode in navigation.modes():
        saved = kept.get(str(mode.name))
        if not saved:
            continue
        for binding in mode.bindings:
            entry = saved.get(str(binding.command))
            if entry is None:
                continue
            binding.keys = list(entry['keys'])
            binding.modifier = entry['modifier']


def forget_saved(path: Optional[str] = None) -> None:
    """Remove the saved file, so the declared defaults are what loads."""
    try:
        os.remove(path or bindings_path())
    except OSError:
        pass


def reset_bindings(navigation: Any, path: Optional[str] = None) -> None:
    """Put every binding back to the mode's declared default.

    The keys are copied into the existing ``KeyBinding`` nodes rather than the
    list being replaced, so anything already holding one -- a settings row, a
    HUD, a watcher -- keeps working and sees the change.

    Passing ``path`` removes the saved file as well, for a caller resetting
    outright rather than as one edit on a page that can still be cancelled.
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
    if path is not None:
        forget_saved(path)


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
