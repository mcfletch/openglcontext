"""The settings screen: everything the renderer can be told to stop doing.

Most of what a renderer does is decided for the player -- shadows on, image-based
lighting probed for and degraded on a weak GPU, geometry batched, detail dropped
with distance.  Those decisions are usually right and are always invisible, and
a player whose frame rate is on the floor has no way to trade any of them away.
This screen is that way: every one of them is a field on the
:class:`~OpenGLContext.contextdefinition.ContextDefinition` (see
:mod:`OpenGLContext.renderoptions`), and every field is offered here.

The page is **generated from the node's fields**, so a new setting appears with
no work here and cannot silently go missing; the ordering and the section
headings are authored, because "in declaration order" is not a design.

Everything is edited on a copy (:mod:`OpenGLContext.ui.session`), so Cancel is
real -- including for a movement page applied two dialogs deep.

To put it on a key, bind a ``keyboard`` key-down rather than a ``keypress``: a
function key produces no character, so no keypress is ever raised for one and
that binding would be accepted and then never fire.  The handler has to be a
bound method of something long-lived, because the event system holds callbacks
weakly::

    class Game(OverlayMixin, GLFWInteractiveContext):
        def OnInit(self):
            self.addEventHandler('keyboard', name='<F10>', state=1,
                                 function=self.openSettings)

        def openSettings(self, event):
            settings.open_settings(self)
"""

from __future__ import annotations

from gettext import gettext as _
from typing import Any, Callable, List, Optional, Sequence

from OpenGLContext.ui import dialogs, generate
from OpenGLContext.ui.layout import Column, Row
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.scroll import ScrollViewport
from OpenGLContext.ui.session import SettingsSession, apply_node
from OpenGLContext.ui.widgets import (
    Button, Label, Separator, Spacer, DANGER, PRIMARY,
)

__all__ = ['settings_panel', 'movement_panel', 'open_settings']

#: Name the settings screen is pushed under, so a second F10 finds it rather
#: than opening another one over it.
SETTINGS_NAME = 'settings'
#: Content width the screen aims for, **in characters**, and the widest it will
#: draw itself.  A settings page laid out to the full width of a 4K display puts
#: a label at one edge and its control at the other, which is not roominess; it
#: is a page you have to sweep your eyes across to read one line.
SETTINGS_COLUMNS = 78


def open_settings(context: Any,
                  on_apply: Optional[Callable[[SettingsSession], None]] = None
                  ) -> Panel:
    """Put the settings screen up, or bring the one already up to the front."""
    existing: Optional[Panel] = context.overlays.named(SETTINGS_NAME)
    if existing is not None:
        return existing
    opened: Panel = context.pushOverlay(settings_panel(context, on_apply=on_apply))
    return opened


def settings_panel(context: Any, session: Optional[SettingsSession] = None,
                   on_apply: Optional[Callable[[SettingsSession], None]] = None
                   ) -> Panel:
    """The whole settings screen for a context.

    ``session`` is normally left alone; pass one to edit something other than
    the context's own definition -- a saved profile, say.

    ``on_apply`` is called with the session once its values have been written
    into the definition, and is where **what to do with the player's settings**
    is decided: writing them to a file, sending them to a server, or nothing at
    all.  Ask the session which fields moved
    (:meth:`~OpenGLContext.ui.session.SettingsSession.changed_fields`) to save
    the player's choices without freezing the rest of a definition the game
    ships and may want to change in a later build.
    """
    definition = context.contextDefinition
    session = session or SettingsSession(definition)
    draft = session.draft

    body = Column(spacing=10, children=(
        _section(_('Rendering'), generate.page_for(
            draft, include=_declared(draft, 'RENDERING_FIELDS')))
        + _modeSection(context, session)
        + _section(_('Interface'), generate.page_for(
            draft, include=_declared(draft, 'INTERFACE_FIELDS')))
        + _section(_('Diagnostics'), generate.page_for(
            draft, include=_declared(draft, 'DIAGNOSTIC_FIELDS')))
    ))

    apply = Button(text=_('Apply'), role=PRIMARY, name='apply', enabled=False)
    cancel = Button(text=_('Cancel'), name='cancel')
    reset = Button(text=_('Reset to defaults'), role=DANGER, name='reset')
    keys = Button(text=_('Key bindings...'), name='keybindings')
    panel = Panel(
        title=_('Settings'), name=SETTINGS_NAME, modal=True, scrim=True,
        fill=True, preferredColumns=SETTINGS_COLUMNS,
        children=[Column(spacing=8, children=[
            ScrollViewport(name='body', flex=1, children=[body]),
            Separator(top=8),
            Row(spacing=10, top=8,
                children=[reset, keys, Spacer(), cancel, apply]),
        ])])

    def refreshApply(*args: Any) -> None:
        # Lit only when there is something to apply, which is also how a change
        # made two dialogs deep announces itself.
        apply.enabled = session.dirty

    session.on_dirty = refreshApply
    panel.session = session

    def doDiscard(closing: Any) -> None:
        session.revert()
        session.close()

    panel.on_close = doDiscard

    def doApply(widget: Any) -> None:
        session.commit()
        panel.on_close = None
        panel.close(True)
        session.close()
        if on_apply is not None:
            on_apply(session)
        # Most options are read per frame by the render pass; the few set once
        # on the window are re-applied here. A changed profile or buffer format
        # only takes effect on the next context, and nothing pretends otherwise.
        changed = getattr(context, 'settingsChanged', None)
        if changed is not None:
            changed()
        else:
            context.triggerRedraw(1)
        # The interface scale is one of the settings on this screen, so the
        # panels have to be measured again before the next frame draws them.
        context.overlays.invalidate()

    def doCancel(widget: Any) -> None:
        panel.close(False)

    def doReset(widget: Any) -> None:
        context.pushOverlay(dialogs.confirm(
            _('Reset every setting to its default?'),
            detail=_('This affects the settings on this screen only, and is '
                     'not saved until you press Apply.'),
            danger=True, yes=_('Reset'), no=_('Keep'),
            on_answer=lambda yes: _resetDraft(session, panel) if yes else None))

    def doBindings(widget: Any) -> None:
        # The bindings page edits the live bindings and saves at once, so it is
        # not part of this session's draft and Cancel here does not undo it.
        from OpenGLContext.ui import bindings
        bindings.open_bindings(context)

    apply.on_activate = doApply
    cancel.on_activate = doCancel
    reset.on_activate = doReset
    keys.on_activate = doBindings
    keys.enabled = bool(getattr(definition, 'movementModes', None))
    return panel


def movement_panel(context: Any, session: SettingsSession, index: int,
                   title: str = '') -> Panel:
    """A page for one declared movement mode, editing a copy of a copy.

    Its Apply writes into the settings screen's draft, so cancelling the screen
    after applying this page still changes nothing.
    """
    child = session.child('movementModes', index=index)
    return record_panel(context, child, title or _('Movement'))


def record_panel(context: Any, session: SettingsSession, title: str,
                 include: Optional[Sequence[str]] = None) -> Panel:
    """A generated page over one sub-record, with its own Apply and Cancel."""
    apply = Button(text=_('Apply'), role=PRIMARY, name='apply')
    cancel = Button(text=_('Cancel'), name='cancel')
    panel = Panel(
        title=title, modal=True, scrim=True, preferredColumns=60,
        children=[Column(spacing=6, children=[
            ScrollViewport(name='body', flex=1, children=[
                generate.page_for(session.draft, include=include)]),
            Row(spacing=8, top=8, children=[Spacer(), cancel, apply]),
        ])])
    panel.session = session

    def doApply(widget: Any) -> None:
        session.commit()
        panel.close(True)

    def doCancel(widget: Any) -> None:
        panel.close(False)

    apply.on_activate = doApply
    cancel.on_activate = doCancel
    panel.closeListeners.append(lambda closing: session.close())
    return panel


# -- the pieces the screen is assembled from ------------------------------
def _declared(node: Any, attribute: str) -> Optional[Sequence[str]]:
    """A node class's named field order, or None to show every field."""
    return getattr(type(node), attribute, None)


def _section(heading: str, page: Any) -> List[Any]:
    return [Label(text=heading, name='%s.heading' % (heading.lower(),),
                  top=8), page]


def _modeSection(context: Any, session: SettingsSession) -> List[Any]:
    """One button per declared movement mode, each opening its own page.

    A button rather than the mode's fields inline: a game may declare four
    modes with a dozen tunables each, and a settings screen that dumps all of
    them is not a settings screen.
    """
    modes = list(getattr(session.draft, 'movementModes', ()) or ())
    if not modes:
        return []
    buttons: List[Any] = []
    for index, mode in enumerate(modes):
        name = str(mode.name) or 'mode %d' % (index,)
        button = Button(text='%s...' % (name.capitalize(),),
                        name='mode.%s' % (name,))
        button.on_activate = _modeOpener(context, session, index, name)
        buttons.append(button)
    return [Label(text=_('Movement'), name='movement.heading', top=8),
            Row(spacing=8, children=buttons)]


def _modeOpener(context: Any, session: SettingsSession, index: int,
                name: str) -> Any:
    def open(widget: Any) -> None:
        context.pushOverlay(movement_panel(
            context, session, index, title=_('%s movement') % (name.capitalize(),)))
    return open


def _resetDraft(session: SettingsSession, panel: Panel) -> None:
    """Put every setting in the draft back to its declared default.

    Into the draft, not the live node: a reset the player then cancels has to
    be as undoable as any other change on the screen.
    """
    apply_node(type(session.draft)(), session.draft)
    if session.on_dirty is not None:
        session.on_dirty(session)
