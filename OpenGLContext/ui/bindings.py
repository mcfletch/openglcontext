"""The key-binding page, and the capturing dialog that rebinds one command.

A rebinding dialog has to see *any* event the user can produce, including the
ones the UI would normally eat for itself: Tab, Enter, the mouse buttons and the
wheel are all bindable.  So the capture dialog is ``capturing`` -- while it is up
the overlay runs no accelerators, no focus traversal and no Enter default, and
every event goes to the capture widget verbatim.  **Escape is reserved** as the
way out, and the dialog says so on its face; the alternatives are a timeout, or
requiring a mouse click on Cancel, which fails for exactly the person rebinding
mouse buttons.

Capture a key that is already bound in the same mode and a **confirmation is
raised over the capture dialog** asking whether to steal it -- a modal over a
modal, which is why the stack exists.

Unlike the settings screen, this page edits the bindings directly and saves at
once: a binding is one small fact, the page shows what it is, and an Apply step
over a list of thirty rows only makes it possible to lose the lot.
"""

from __future__ import annotations

from gettext import gettext as _
from typing import Any, List, Optional, Sequence, Tuple

from OpenGLContext.move import bindingstore
from OpenGLContext.ui import dialogs
from OpenGLContext.ui.layout import Column, Grid, Row
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.scroll import ScrollViewport
from OpenGLContext.ui.widgets import (
    Button, KeyCapture, Label, Separator, Spacer, key_label, DANGER, PRIMARY,
)

__all__ = ['bindings_panel', 'capture_panel', 'open_bindings']

#: Name the page is pushed under, so a second request finds the one already up.
BINDINGS_NAME = 'keybindings'
#: What a binding with no keys reads as.
UNBOUND = _('(unbound)')


def open_bindings(context: Any, navigation: Any = None,
                  path: Optional[str] = None) -> Optional[Panel]:
    """Put the key-binding page up; None if the context declares no modes."""
    navigation = navigation or context.getNavigation()
    if navigation is None:
        return None
    for panel in context.overlays.panels:
        if panel.name == BINDINGS_NAME:
            return panel
    return context.pushOverlay(bindings_panel(context, navigation, path=path))


def bindings_panel(context: Any, navigation: Any,
                   path: Optional[str] = None) -> Panel:
    """A row per declared command, each rebindable by clicking it."""
    rows: List[Any] = []
    buttons: List[Tuple[str, str, Any]] = []
    current_mode = None
    for mode_name, binding in navigation.binding_table():
        if mode_name != current_mode:
            current_mode = mode_name
            rows.extend([Label(text=str(mode_name).capitalize() or _('Movement'),
                               name='%s.heading' % (mode_name,), top=8),
                         Label(text='')])
        button = Button(text=_keysText(binding),
                        name='%s.%s' % (mode_name, binding.command))
        rows.extend([Label(text=str(binding.label) or binding.command), button])
        # Held by name rather than by object: a reset rebuilds a mode's
        # bindings, and a row pointing at a discarded one would show a value
        # nothing reads any more.
        buttons.append((mode_name, str(binding.command), button))

    close = Button(text=_('Close'), role=PRIMARY, name='close')
    reset = Button(text=_('Reset all bindings'), role=DANGER, name='reset')
    panel = Panel(
        title=_('Key bindings'), name=BINDINGS_NAME, modal=True, scrim=True,
        fill=True,
        children=[Column(spacing=6, children=[
            Label(text=_('Click a key to change it.  Escape leaves a capture '
                         'without rebinding.'), wrap=True),
            ScrollViewport(name='body', flex=1, children=[
                Grid(children=rows, columns=2, spacing=4, columnSpacing=16)]),
            Separator(top=4),
            Row(spacing=8, top=4, children=[reset, Spacer(), close]),
        ])])

    def refresh() -> None:
        for mode_name, command, button in buttons:
            binding = _binding(navigation, mode_name, command)
            button.text = _keysText(binding) if binding is not None else UNBOUND

    for mode_name, command, button in buttons:
        button.on_activate = _rebinder(context, navigation, mode_name, command,
                                       refresh, path)
    close.on_activate = lambda widget: panel.close(True)
    reset.on_activate = lambda widget: context.pushOverlay(dialogs.confirm(
        _('Reset every key binding to its default?'),
        detail=_('Any keys you have changed will be forgotten.'),
        danger=True, yes=_('Reset'), no=_('Keep'),
        on_answer=lambda yes: _reset(navigation, refresh, path) if yes else None))
    return panel


def capture_panel(context: Any, navigation: Any, mode_name: str, binding: Any,
                  on_bound: Any, path: Optional[str] = None) -> Panel:
    """A dialog that takes the next key and binds it to one command."""
    capture = KeyCapture(keys=list(binding.keys), name='capture')
    cancel = Button(text=_('Cancel'), name='cancel')
    panel = Panel(
        title=_('Bind %s') % (str(binding.label) or binding.command,),
        modal=True, scrim=True, capturing=True, preferredColumns=48,
        children=[Column(spacing=6, children=[
            Label(text=_('Press the key to bind to %s.  Escape cancels and is '
                         'the one key that cannot be bound.')
                  % (str(binding.label) or binding.command,), wrap=True),
            capture,
            Row(top=8, children=[Spacer(), cancel]),
        ])])
    panel.focus(capture)
    cancel.on_activate = lambda widget: panel.close(False)

    def captured(widget: Any) -> None:
        key = widget.captured
        if key is None:
            return
        clash = bindingstore.conflicts(navigation.binding_table(), key,
                                       str(binding.modifier), mode=mode_name,
                                       skip=binding)
        if not clash:
            _bind(navigation, binding, key, on_bound, path)
            panel.close(True)
            return
        # Ask over the capture dialog rather than under it: the capture is
        # still the thing the user is doing, and it stays up if they decline.
        widget.captured = None
        context.pushOverlay(dialogs.confirm(
            _('%s is already bound to %s.  Take it?')
            % (key, _conflictNames(clash)),
            detail=_('That command loses this key; any others it has stay.'),
            danger=True, yes=_('Take it'), no=_('Leave it'),
            on_answer=lambda yes: _steal(
                navigation, binding, key, clash, on_bound, path, panel)
            if yes else None))

    capture.on_change = captured
    return panel


# -- the things the buttons do -------------------------------------------
def _keysText(binding: Any) -> str:
    keys = [key_label(str(key)) for key in binding.keys]
    text = ', '.join(keys) if keys else UNBOUND
    if binding.modifier:
        return '%s + %s' % (str(binding.modifier), text)
    return text


def _conflictNames(clash: Sequence[Tuple[str, Any]]) -> str:
    return ', '.join(str(binding.label) or binding.command
                     for _name, binding in clash)


def _binding(navigation: Any, mode_name: str, command: str) -> Optional[Any]:
    """The live binding for one command of one mode, or None if it is gone."""
    for name, binding in navigation.binding_table():
        if name == mode_name and binding.command == command:
            return binding
    return None


def _rebinder(context: Any, navigation: Any, mode_name: str, command: str,
              refresh: Any, path: Optional[str]) -> Any:
    def open(widget: Any) -> None:
        binding = _binding(navigation, mode_name, command)
        if binding is None:
            return
        context.pushOverlay(capture_panel(context, navigation, mode_name,
                                          binding, refresh, path))
    return open


def _bind(navigation: Any, binding: Any, key: str, on_bound: Any,
          path: Optional[str]) -> None:
    binding.keys = [key]
    bindingstore.save_bindings(navigation, path)
    if on_bound is not None:
        on_bound()


def _steal(navigation: Any, binding: Any, key: str,
           clash: Sequence[Tuple[str, Any]], on_bound: Any,
           path: Optional[str], capture: Panel) -> None:
    for _name, other in clash:
        other.keys = [existing for existing in other.keys if existing != key]
    _bind(navigation, binding, key, on_bound, path)
    capture.close(True)


def _reset(navigation: Any, refresh: Any, path: Optional[str]) -> None:
    bindingstore.reset_bindings(navigation, path)
    refresh()
