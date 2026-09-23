"""What the pointer does in one view, and what says so.

Each view has its own navigation: the gestures its camera can be moved by, and
the bindings that say which button raises each. A plan view and an elevation
pan and zoom; a camera that turns also rotates about what it is looking at.
The commands are:

``pan``
    Carry the world with the pointer. A plan view and an elevation slide in
    their own plane; a camera that turns carries what it is looking at across
    the view.
``rotate``
    Swing the camera about what it is looking at, for a camera that turns.
``zoomin`` / ``zoomout``
    One notch towards the scene or away from it, about the pointer in a view
    with a scale and along the line of sight in one without.
``zoomdrag``
    The same zoom, driven by a drag rather than by the wheel -- dragging up
    comes closer. Offered by every camera and bound to nothing, so a view that
    wants it says so.

The bindings are :class:`~OpenGLContext.move.modes.KeyBinding` nodes, the same
ones the movement modes carry, and a mouse button is named as the event system
names it (``<mouse-0>``, and :data:`~OpenGLContext.events.mouseevents.WHEEL_UP`
for a notch). So the bindings screen rebinds these like any other command, the
binding file saves them, and an application changes one in a line::

    navigation = view.navigation
    navigation.rebind(ROTATE, ['<mouse-2>'])       # right-drag turns the view
    navigation.rebind(ZOOM_DRAG, ['<mouse-1>'])    # middle-drag zooms
    navigation.rebind(PAN, [])                     # this view does not pan

:class:`~OpenGLContext.multiview.gestures.ViewGestures` reads the pointer and
asks the navigation of the view the pointer is in; nothing here touches GL or
events.
"""
from __future__ import annotations

from gettext import gettext as _
from typing import Any, List, Optional, Sequence, Tuple

import math

from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP, button_name
from OpenGLContext.move.modes import MODIFIER_INDEX, KeyBinding
from OpenGLContext.multiview.views import View
from vrml import field, node

__all__ = [
    'PAN', 'ROTATE', 'ZOOM_IN', 'ZOOM_OUT', 'ZOOM_DRAG',
    'ViewNavigation', 'ViewNavigationMode', 'navigation_for',
    'plan_mode', 'examine_mode', 'ZOOM_STEP', 'ROTATE_RATE', 'ZOOM_PIXELS',
]

#: Carry the world with the pointer.
PAN = 'pan'
#: Swing the camera about what it is looking at.
ROTATE = 'rotate'
#: One notch towards the scene.
ZOOM_IN = 'zoomin'
#: One notch away from it.
ZOOM_OUT = 'zoomout'
#: Zoom by dragging rather than by the wheel.
ZOOM_DRAG = 'zoomdrag'

#: What one notch towards the scene multiplies a view's span or its distance by.
ZOOM_STEP = 0.8

#: Degrees a camera turns for each pixel the pointer is dragged.
ROTATE_RATE = 0.4

#: Pixels of drag that zoom by one notch, for ``zoomdrag``.
ZOOM_PIXELS = 60.0


class ViewNavigationMode(node.Node):
    """A named set of bindings: which button raises which gesture.

    A node, like the movement modes, so a settings window can enumerate,
    label and rewrite the bindings with no knowledge of any particular view.
    """

    PROTO = 'ViewNavigationMode'
    #: What the mode is called, which is how a saved binding file finds it.
    name = field.newField('name', 'SFString', 1, '')
    #: What a settings window shows the user.
    label = field.newField('label', 'SFString', 1, '')
    #: Whether the mode is on offer.
    enabled = field.newField('enabled', 'SFBool', 1, True)
    #: The bindings, in the order a settings window lists them.
    bindings = field.newField('bindings', 'MFNode', 1, list)

    UI_HINTS = {
        'name': {'skip': True},
        'label': {'label': 'Mode'},
        'enabled': {'label': 'Available'},
    }

    def keys_for(self, command: str) -> Tuple[str, ...]:
        """The keys currently bound to ``command``."""
        for binding in self.bindings:
            if binding.command == command:
                return tuple(binding.keys)
        return ()

    def command_for(self, key: str, modifiers: Sequence[int] = (0, 0, 0)
                    ) -> Optional[str]:
        """The command ``key`` raises with these modifiers held, or None.

        A binding that asks for a modifier needs it held. A binding that asks
        for none loses its key while another binding of this mode claims the
        same key with a modifier that *is* held, so ctrl-drag can zoom in a
        view whose plain drag pans.
        """
        plain = None
        for binding in self.bindings:
            if key not in binding.keys:
                continue
            index = MODIFIER_INDEX.get(binding.modifier)
            if binding.modifier:
                if index is not None and modifiers[index]:
                    return str(binding.command)
            elif plain is None:
                plain = str(binding.command)
        return plain

    def rebind(self, command: str, keys: Sequence[str],
               modifier: Optional[str] = None) -> bool:
        """Point ``command`` at other keys; False if the mode has not got it."""
        for binding in self.bindings:
            if binding.command == command:
                binding.keys = [str(key) for key in keys]
                if modifier is not None:
                    binding.modifier = str(modifier)
                return True
        return False


def _binding(command: str, label: str, keys: Sequence[str],
             modifier: str = '') -> KeyBinding:
    return KeyBinding(command=command, label=label,
                      keys=[str(key) for key in keys], modifier=modifier)


def _zoom_bindings() -> List[KeyBinding]:
    """The bindings every camera has: the wheel, and a drag nothing raises yet."""
    return [
        _binding(ZOOM_IN, _('Zoom in'), [button_name(WHEEL_UP)]),
        _binding(ZOOM_OUT, _('Zoom out'), [button_name(WHEEL_DOWN)]),
        _binding(ZOOM_DRAG, _('Zoom by dragging'), []),
    ]


def plan_mode() -> ViewNavigationMode:
    """A view with a scale: a drag moves the world, the wheel changes the scale."""
    return ViewNavigationMode(
        name='plan', label=_('Plan'),
        bindings=[_binding(PAN, _('Pan'), [button_name(button)
                                           for button in (0, 1, 2)])]
        + _zoom_bindings())


def examine_mode() -> ViewNavigationMode:
    """A camera that turns: a left drag swings it, another carries its target."""
    return ViewNavigationMode(
        name='examine', label=_('Examine'),
        bindings=[
            _binding(ROTATE, _('Rotate'), [button_name(0)]),
            _binding(PAN, _('Pan'), [button_name(1), button_name(2)]),
        ] + _zoom_bindings())


class ViewNavigation:
    """One view's camera, the gestures it offers, and the bindings that raise them.

    ``mode`` is the bindings to start with; with none given, the camera
    decides -- a camera that turns gets :func:`examine_mode` and one with a
    scale :func:`plan_mode`.
    """

    def __init__(self, view: View, mode: Optional[ViewNavigationMode] = None) -> None:
        self.view = view
        camera = getattr(view.camera, 'view', None)
        #: The camera itself -- a plan view, an elevation or one that turns.
        #: What it answers to is :meth:`commands`, and a view with no camera
        #: answers to nothing.
        self.camera: Any = camera
        self.turns = camera is not None and hasattr(camera, 'orbit')
        self.mode = mode if mode is not None else (
            examine_mode() if self.turns else plan_mode())
        self._held: Optional[Tuple[str, float, float]] = None

    # -- what it offers ----------------------------------------------------
    def commands(self) -> Tuple[str, ...]:
        """The gestures this camera can be moved by."""
        if self.camera is None:
            return ()
        if self.turns:
            return (PAN, ROTATE, ZOOM_IN, ZOOM_OUT, ZOOM_DRAG)
        return (PAN, ZOOM_IN, ZOOM_OUT, ZOOM_DRAG)

    def command_for(self, key: str, modifiers: Sequence[int] = (0, 0, 0)
                    ) -> Optional[str]:
        """The command this key raises in this view, or None."""
        found = self.mode.command_for(key, modifiers)
        return found if found in self.commands() else None

    def keys_for(self, command: str) -> Tuple[str, ...]:
        """The keys currently bound to ``command``."""
        return self.mode.keys_for(command)

    def rebind(self, command: str, keys: Sequence[str],
               modifier: Optional[str] = None) -> bool:
        """Point a command at other keys; False if this camera has not got it."""
        if command not in self.commands():
            return False
        return self.mode.rebind(command, keys, modifier)

    # -- what a settings screen reads --------------------------------------
    def modes(self) -> List[ViewNavigationMode]:
        """The modes on offer, which is the one this view is using."""
        return [self.mode]

    def binding_table(self) -> List[Tuple[str, KeyBinding]]:
        """``(mode name, binding)`` for every command, for a settings window."""
        return [(str(self.mode.name), binding)
                for binding in self.mode.bindings
                if str(binding.command) in self.commands()]

    # -- the gestures ------------------------------------------------------
    def begin(self, command: str, x: float, y: float) -> bool:
        """A drag gesture began at window pixel ``(x, y)``; True if it can run."""
        if command not in self.commands() or command in (ZOOM_IN, ZOOM_OUT):
            return False
        self._held = (command, float(x), float(y))
        return True

    def drag(self, x: float, y: float) -> bool:
        """The pointer moved to ``(x, y)``; True where the camera moved with it."""
        if self._held is None:
            return False
        command, last_x, last_y = self._held
        dx, dy = float(x) - last_x, float(y) - last_y
        self._held = (command, float(x), float(y))
        if command == PAN:
            self._pan(dx, dy)
        elif command == ROTATE:
            self.camera.orbit(-dx * ROTATE_RATE, -dy * ROTATE_RATE)
        elif command == ZOOM_DRAG:
            self._scale(ZOOM_STEP ** (dy / ZOOM_PIXELS), last_x, last_y)
        return True

    def release(self) -> bool:
        """The button came up; True where it ended a gesture."""
        held = self._held is not None
        self._held = None
        return held

    def zoom(self, notches: int, x: float, y: float) -> bool:
        """``notches`` towards the scene over window pixel ``(x, y)``."""
        if self.camera is None:
            return False
        self._scale(ZOOM_STEP ** int(notches), x, y)
        return True

    # -- moving the camera --------------------------------------------------
    def _size(self) -> Tuple[int, int]:
        width, height = self.view.size
        if width <= 0 or height <= 0:
            return (1, 1)
        return (int(width), int(height))

    def _pan(self, dx: float, dy: float) -> None:
        if not self.turns:
            self.camera.pan(dx, dy, self._size())
            return
        # A camera that turns carries what it is looking at, at that depth, so
        # the world keeps up with the pointer rather than sliding under it.
        viewport = self._size()
        model, _projection = self.camera.matrices(viewport)
        right, up = model[:3, 0], model[:3, 1]
        scale = (2.0 * self.camera.distance
                 * math.tan(math.radians(self.camera.fov) / 2.0) / viewport[1])
        target = self.camera.target() - (right * dx + up * dy) * scale
        self.camera.look_at((float(target[0]), float(target[2])), float(target[1]))

    def _scale(self, factor: float, x: float, y: float) -> None:
        if self.turns:
            self.camera.dolly(factor)
            return
        self.camera.zoom(factor, at=self.view.local(x, y), viewport=self._size())


def navigation_for(view: View, mode: Optional[ViewNavigationMode] = None
                   ) -> Optional[ViewNavigation]:
    """The view's navigation, made for its camera; None for a view with no camera.

    Kept on the view, so the bindings a caller changes are the ones the pointer
    reads.
    """
    if view.camera is None or getattr(view.camera, 'view', None) is None:
        return None
    if view.navigation is None or mode is not None:
        view.navigation = ViewNavigation(view, mode)
    found: ViewNavigation = view.navigation
    return found
