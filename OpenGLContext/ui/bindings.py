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

**The page edits the live bindings and saves when it is left with Save.**  The
edits take effect at once, because a mode resolves a command to keys when it
samples rather than when it is built -- so a rebinding can be tried without
leaving the screen.  What is deferred is the *file*: writing it on every
captured key puts a save between the player and every keystroke and leaves no
way back from a mis-hit.  Cancel and Escape put every binding back as the page
found it, a reset included.
"""

from __future__ import annotations

from gettext import gettext as _
from typing import Any, List, Optional, Sequence, Tuple

from OpenGLContext.move import bindingstore
from OpenGLContext.ui import dialogs, generate
from OpenGLContext.ui.layout import Column, Grid, Row
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.scroll import ScrollViewport
from OpenGLContext.ui.widgets import (
    Button, KeyCapture, Label, Separator, Spacer, key_label, DANGER, PRIMARY,
)

__all__ = ['bindings_panel', 'capture_panel', 'open_bindings']

#: Name the page is pushed under, so a second request finds the one already up.
BINDINGS_NAME = 'keybindings'
#: Content width in characters, and the widest the page will draw itself.
BINDINGS_COLUMNS = 66
def unbound_text() -> str:
    """What a binding with no keys reads as.

    A function rather than a module constant: ``gettext`` at import time is
    resolved before an application can bind a text domain, so the one string
    spelled that way would stay in the locale that happened to be in force when
    this module was first imported.
    """
    return _('(unbound)')


def open_bindings(context: Any, navigation: Any = None,
                  path: Optional[str] = None) -> Optional[Panel]:
    """Put the key-binding page up; None if the context declares no modes."""
    navigation = navigation or context.getNavigation()
    if navigation is None:
        return None
    existing: Optional[Panel] = context.overlays.named(BINDINGS_NAME)
    if existing is not None:
        return existing
    opened: Panel = context.pushOverlay(bindings_panel(context, navigation,
                                                       path=path))
    return opened


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

    save = Button(text=_('Save'), role=PRIMARY, name='save')
    cancel = Button(text=_('Cancel'), name='cancel')
    reset = Button(text=_('Reset all bindings'), role=DANGER, name='reset')
    panel = Panel(
        title=_('Key bindings'), name=BINDINGS_NAME, modal=True, scrim=True,
        fill=True, preferredColumns=BINDINGS_COLUMNS,
        children=[Column(spacing=10, children=[
            Label(text=_('Click a key to change it.  Escape leaves a capture '
                         'without rebinding, and leaves this page without '
                         'saving.'), wrap=True),
            ScrollViewport(name='body', flex=1, children=[
                Grid(children=rows, columns=2,
                     columnFlex=list(generate.COLUMN_FLEX),
                     spacing=generate.ROW_SPACING,
                     columnSpacing=generate.COLUMN_SPACING,
                     rowPadding=generate.ROW_PADDING)]),
            Separator(top=8),
            Row(spacing=10, top=8, children=[reset, Spacer(), cancel, save]),
        ])])

    # What the page found, so Cancel is real -- plain data rather than the
    # nodes, because a reset rebuilds a mode's bindings.
    opened_with = bindingstore.snapshot(navigation)

    def refresh() -> None:
        for mode_name, command, button in buttons:
            binding = _binding(navigation, mode_name, command)
            button.text = (_keysText(binding) if binding is not None
                           else unbound_text())

    for mode_name, command, button in buttons:
        button.on_activate = _rebinder(context, navigation, mode_name, command,
                                       refresh)

    def doSave(widget: Any) -> None:
        bindingstore.save_bindings(navigation, path)
        panel.on_close = None
        panel.close(True)

    def doCancel(widget: Any) -> None:
        panel.close(False)

    save.on_activate = doSave
    cancel.on_activate = doCancel
    # Escape closes the panel without going through Cancel, so the restore
    # hangs off the close itself and Save takes it off first.
    panel.on_close = lambda closing: bindingstore.restore(navigation,
                                                          opened_with)
    reset.on_activate = lambda widget: context.pushOverlay(dialogs.confirm(
        _('Reset every key binding to its default?'),
        detail=_('They go back to the defaults on this page; nothing is '
                 'written until you press Save.'),
        danger=True, yes=_('Reset'), no=_('Keep'),
        on_answer=lambda yes: _reset(navigation, refresh) if yes else None))
    return panel


def capture_panel(context: Any, navigation: Any, mode_name: str, binding: Any,
                  on_bound: Any) -> Panel:
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
            _bind(binding, key, on_bound)
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
            on_answer=lambda yes: _steal(binding, key, clash, on_bound, panel)
            if yes else None))

    capture.on_change = captured
    return panel


# -- the things the buttons do -------------------------------------------
def _keysText(binding: Any) -> str:
    keys = [key_label(str(key)) for key in binding.keys]
    text = ', '.join(keys) if keys else unbound_text()
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
              refresh: Any) -> Any:
    def open(widget: Any) -> None:
        binding = _binding(navigation, mode_name, command)
        if binding is None:
            return
        context.pushOverlay(capture_panel(context, navigation, mode_name,
                                          binding, refresh))
    return open


def _bind(binding: Any, key: str, on_bound: Any) -> None:
    """Point a command at a key.  The page writes the file, not this."""
    binding.keys = [key]
    if on_bound is not None:
        on_bound()


def _steal(binding: Any, key: str, clash: Sequence[Tuple[str, Any]],
           on_bound: Any, capture: Panel) -> None:
    for _name, other in clash:
        other.keys = [existing for existing in other.keys if existing != key]
    _bind(binding, key, on_bound)
    capture.close(True)


def _reset(navigation: Any, refresh: Any) -> None:
    # Into the live bindings only; the page's Cancel can still put them back
    # and its Save is what reaches the file.
    bindingstore.reset_bindings(navigation)
    refresh()
