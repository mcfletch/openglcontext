"""What a scene's bound NavigationInfo asks of the context -- no GL

X3D's ``NavigationInfo`` (ISO/IEC 19775-1, 23.4.4) is bound as viewpoints are
(:mod:`vrml.x3d.binding`). The engine reads these of its fields:

- ``headlight``: true adds a headlight to the scene's own lights, false leaves
  it off (:func:`headlight`). A document with no NavigationInfo has X3D's
  default one, so the headlight; a scene built in code with none has the
  headlight only where it has no lights.
- ``type``: the navigation types the document asks for, in order of
  preference, as the engine's movement modes (:data:`MODES`). When a
  NavigationInfo is bound, the first of them the context's declared
  navigation offers is selected (:func:`apply`); ``ANY`` and the types with
  no engine mode leave the choice with the player. A context with no
  declared movement modes keeps its own navigation.
- ``visibilityLimit``, where positive, is the far clipping distance from the
  time the NavigationInfo is bound (:func:`clip`).
- ``speed`` scales the declared modes' speeds relative to X3D's default of 1,
  so 1 leaves the engine's own speeds and 2 doubles them
  (:func:`speed_factor`).
- ``avatarSize`` (radius, eye height, step height) sizes the walking avatar
  (:func:`avatar_of`, ``context.navigationAvatar``).
- ``transitionType`` and ``transitionTime`` say how the camera moves to a
  viewpoint bound after the first (:func:`transition_of`,
  :class:`OpenGLContext.passes.viewpointbinding.ViewpointTransition`), and
  ``transitionComplete`` is sent when it arrives.
"""
from __future__ import annotations

import weakref
from collections.abc import Sequence
from typing import Any, Optional

__all__ = ['MODES', 'TRANSITIONS', 'apply', 'avatar_of', 'chosen_mode', 'clip', 'headlight',
           'requested_modes', 'speed_factor', 'transition_of']

#: The engine's movement modes for each of X3D's navigation types, by name.
MODES: dict[str, tuple[str, ...]] = {
    'WALK': ('walk', 'fps'),
    'FLY': ('fly',),
    'EXAMINE': ('examine',),
    'LOOKAT': ('examine',),
    'EXPLORE': ('examine',),
    'NONE': (),
}

#: X3D's transition types, the first the engine knows of being used.
TRANSITIONS = ('TELEPORT', 'LINEAR', 'ANIMATE')

#: The fields each mode's speeds are held in.
SPEEDS = ('walkSpeed', 'runSpeed', 'flySpeed', 'boostSpeed', 'swimSpeed')

#: X3D's avatarSize default: collision radius, eye height, step height.
AVATAR = (0.25, 1.6, 0.75)

#: Each mode's own speeds, before any NavigationInfo scaled them.
_base_speeds: weakref.WeakKeyDictionary[Any, dict[str, float]] = weakref.WeakKeyDictionary()

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


def headlight(info: Any, lights: int, document: bool = False) -> bool:
    """Whether a frame with `lights` of the scene's own lights has the headlight

    `info` is the bound NavigationInfo, or None where the scene has none;
    `document` says the scene was read from a VRML97 or X3D document.
    """
    if info is None:
        return document or lights == 0
    return bool(info.headlight)


def speed_factor(info: Any) -> float:
    """What `info`'s speed multiplies the modes' speeds by: speed over X3D's default 1"""
    return max(float(info.speed), 0.0)


def avatar_of(info: Any) -> tuple[float, float, float]:
    """(collision radius, eye height, step height) from `info`'s avatarSize, X3D's defaults filling in"""
    given = [float(value) for value in info.avatarSize][:3]
    radius, eye, step = given + list(AVATAR[len(given):])
    return (radius, eye, step)


def transition_of(info: Any) -> tuple[str, float]:
    """(type, seconds) of the move to a newly bound viewpoint

    The first of `info`'s transition types that is one of
    :data:`TRANSITIONS`, LINEAR where none is; a TELEPORT, or a time of 0 or
    less, is a jump. None for no NavigationInfo: LINEAR over a second.
    """
    if info is None:
        return ('LINEAR', 1.0)
    kind = 'LINEAR'
    for value in info.transitionType:
        name = str(value).strip().strip('"').upper()
        if name in TRANSITIONS:
            kind = name
            break
    seconds = float(info.transitionTime)
    if kind == 'TELEPORT' or seconds <= 0:
        return ('TELEPORT', 0.0)
    return (kind, seconds)


def _scale_speeds(manager: Any, factor: float) -> None:
    """Set each declared mode's speeds to its own times `factor`"""
    for mode in manager.modes():
        base = _base_speeds.get(mode)
        if base is None:
            base = _base_speeds[mode] = {name: float(getattr(mode, name)) for name in SPEEDS
                                         if hasattr(mode, name)}
        for name, value in base.items():
            setattr(mode, name, value * factor)


def clip(platform: Any, info: Any) -> None:
    """Give `platform` `info`'s visibilityLimit as its far distance, where positive"""
    if info is not None and float(info.visibilityLimit) > 0:
        platform.setClipping(far=float(info.visibilityLimit))


def apply(context: Any, info: Any) -> None:
    """Apply `info` to `context` once for each NavigationInfo bound

    The far clipping distance of the context's ``platform`` (:func:`clip`),
    the avatar size (``context.navigationAvatar``), the modes' speeds and the
    movement mode `info` asks for. `context` answers
    ``getNavigation()``: its navigation manager, or None where it declares no
    movement modes.
    """
    if _applied.get(context) is info:
        return
    _applied[context] = info
    platform = getattr(context, 'platform', None)
    if platform is not None:
        clip(platform, info)
    context.navigationAvatar = None if info is None else avatar_of(info)
    manager = context.getNavigation()
    if manager is None or info is None:
        return
    _scale_speeds(manager, speed_factor(info))
    name = chosen_mode(info, [mode.name for mode in manager.selectable()])
    if name is not None:
        manager.select(name)
