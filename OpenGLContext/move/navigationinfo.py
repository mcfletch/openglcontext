"""What a scene's bound NavigationInfo asks of the context -- no GL

X3D's ``NavigationInfo`` (ISO/IEC 19775-1, 23.4.4) is bound as viewpoints are
(:mod:`vrml.x3d.binding`). The engine reads two of its fields:

- ``headlight``: true adds a headlight to the scene's own lights, false leaves
  it off (:func:`headlight`). A scene with no NavigationInfo has the headlight
  only where it has no lights.
- ``type``: the navigation types the document asks for, in order of
  preference, as the engine's movement modes (:data:`MODES`). When a
  NavigationInfo is bound, the first of them the context's declared
  navigation offers is selected (:func:`apply`); ``ANY`` and the types with
  no engine mode leave the choice with the player. A context with no
  declared movement modes keeps its own navigation.

``speed``, ``avatarSize``, ``visibilityLimit`` and the transition fields are
not read.
"""
from __future__ import annotations

import weakref
from collections.abc import Sequence
from typing import Any, Optional

__all__ = ['MODES', 'apply', 'chosen_mode', 'headlight', 'requested_modes']

#: The engine's movement modes for each of X3D's navigation types, by name.
MODES: dict[str, tuple[str, ...]] = {
    'WALK': ('walk', 'fps'),
    'FLY': ('fly',),
    'EXAMINE': ('examine',),
    'LOOKAT': ('examine',),
    'EXPLORE': ('examine',),
    'NONE': (),
}

#: The NavigationInfo last applied to each context.
_applied: weakref.WeakKeyDictionary[Any, Any] = weakref.WeakKeyDictionary()


def requested_modes(info: Any) -> Optional[list[str]]:
    """The engine's mode names `info`'s types ask for, in order; None for ``ANY`` first

    Types are read without case or quotes. ``NONE`` asks for no mode; a
    type with no engine mode is passed over. ``ANY`` after other types ends
    the list.
    """
    found: list[str] = []
    for value in info.type:
        name = str(value).strip().strip('"').upper()
        if name == 'ANY':
            return found if found else None
        for mode in MODES.get(name, ()):
            if mode not in found:
                found.append(mode)
    return found


def chosen_mode(info: Any, offered: Sequence[str]) -> Optional[str]:
    """The first mode `info` asks for that is among `offered`, or None"""
    for name in requested_modes(info) or ():
        if name in offered:
            return name
    return None


def headlight(info: Any, lights: int) -> bool:
    """Whether a frame with `lights` of the scene's own lights has the headlight

    `info` is the bound NavigationInfo, or None where the scene has none.
    """
    if info is None:
        return lights == 0
    return bool(info.headlight)


def apply(context: Any, info: Any) -> None:
    """Select the mode `info` asks for on `context`, once for each NavigationInfo bound

    `context` answers ``getNavigation()``: its navigation manager, or None
    where it declares no movement modes.
    """
    if _applied.get(context) is info:
        return
    _applied[context] = info
    manager = context.getNavigation()
    if manager is None or info is None:
        return
    name = chosen_mode(info, [mode.name for mode in manager.selectable()])
    if name is not None:
        manager.select(name)
