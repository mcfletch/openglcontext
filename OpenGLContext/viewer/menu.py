"""The viewer's own screens: what to do, and what to open.

``oglc-view`` with nothing named opens :func:`main_menu` rather than printing a
usage message, and from it :func:`browse_screen` -- a shelf of models and worlds
shown by **their own pictures**, because what tells one sample from another is
what it looks like and a list of names like ``MetalRoughSpheresNoTextures``
makes you open each in turn to find out which is which.

Everything here is a plain :class:`~OpenGLContext.ui.panel.Panel` built from the
shared widgets, so the screens take the skin, the interface scale and the input
routing that every other screen in the system takes, and can be checked without
a window.  Settings and key bindings are not reimplemented here at all: they are
:func:`OpenGLContext.ui.settings.open_settings` and
:func:`OpenGLContext.ui.bindings.open_bindings`, the same pages every other
program shows.

    from OpenGLContext.viewer import menu
    context.pushOverlay(menu.main_menu(on_browse=..., on_quit=...))
"""
from gettext import gettext as _
from typing import Any, Callable, List, Optional, Sequence

from OpenGLContext.ui.gallery import Carousel
from OpenGLContext.ui.layout import Column, Row
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import (
    Button, Label, Select, Separator, Spacer, TextField,
)
from OpenGLContext.viewer.library import Entry, Library

__all__ = ['main_menu', 'browse_screen', 'MENU_NAME', 'BROWSE_NAME', 'SHOWN']

#: What the launch menu calls itself.
TITLE = 'oglc-view'

#: Names the screens are pushed under, so pressing the key again raises the one
#: already up instead of stacking another over it.
MENU_NAME = 'viewer-menu'
BROWSE_NAME = 'viewer-browse'

#: Content width, in characters.  The band needs room -- pictures cramped into a
#: narrow column defeat the point of showing them -- and everything else is
#: happier not being swept across a 4K display.
MENU_COLUMNS = 44
BROWSE_COLUMNS = 96

#: Pictures visible in the band at once, and therefore how far a page moves.
SHOWN = 5

#: What an empty shelf says.  It is a real state -- no worlds in a wheel, and no
#: catalogue when offline -- so it says which, rather than looking broken.
NOTHING = _('Nothing to show here.  Pass a file or URL on the command line, or '
            'check the network for the sample catalogue.')


def _button(name: str, text: str, handler: Optional[Callable[[], None]],
            role: str = '') -> Button:
    """A button that calls a plain no-argument function."""
    widget = Button(text=text, name=name, role=role)
    if handler is not None:
        widget.on_activate = lambda _widget, call=handler: call()
    return widget


def main_menu(on_browse: Optional[Callable[[], None]] = None,
              on_settings: Optional[Callable[[], None]] = None,
              on_bindings: Optional[Callable[[], None]] = None,
              on_quit: Optional[Callable[[], None]] = None,
              on_resume: Optional[Callable[[], None]] = None,
              on_open: Optional[Callable[[str], None]] = None,
              subtitle: str = '') -> Panel:
    """The first screen, and the one Escape brings up: what someone can do.

    ``on_resume`` is what makes it dismissable, and it is offered **first**.
    A viewer opened with nothing to show has nothing behind this screen, so
    Escape does nothing and leaving is what Quit is for.  One with a scene up
    passes ``on_resume`` and gets both a Resume button and Escape again —
    because somebody who pressed Escape meaning "back out of this" must never
    find they have thrown a loaded world away instead.

    ``on_open`` is called with whatever was typed into the address box.  Not
    everything worth looking at is on the shelf, and a viewer launched from a
    desktop has no command line to pass a URL on.
    """
    children: List[Any] = [Label(text=TITLE, name='title')]
    if subtitle:
        children.append(Label(text=subtitle, wrap=True, name='subtitle'))
    children.append(Separator(top=6))
    if on_resume is not None:
        children.append(_button('resume', _('Resume'), on_resume,
                                role='primary'))
    children.append(_button('browse', _('Open a model or world...'), on_browse,
                            role='' if on_resume is not None else 'primary'))
    children.append(_button('settings', _('Settings'), on_settings))
    children.append(_button('bindings', _('Controls'), on_bindings))
    children.append(_button('quit', _('Quit'), on_quit))
    children.append(Separator(top=6))
    children.append(Label(text=_('...or open an address:'), name='url-label'))
    address = TextField(name='url',
                        placeholder=_('https://example.com/model.glb'))
    open_url = Button(text=_('Open'), name='open-url')
    children.append(address)
    children.append(open_url)

    def open_typed(_widget: Any = None) -> None:
        """Open whatever is in the box, if anything and if anyone is listening.

        Trimmed: a pasted address arrives with surrounding space more often
        than not, and a viewer answering "file not found: ' /models/duck.glb'"
        would be blaming the user for the paste.
        """
        typed = str(address.value).strip()
        if typed and on_open is not None:
            on_open(typed)
    open_url.on_activate = open_typed
    # Return in the field is what a person types after an address.
    address.on_activate = open_typed

    panel = Panel(title='', name=MENU_NAME, scrim=True, modal=True,
                  closeOnEscape=on_resume is not None,
                  preferredColumns=MENU_COLUMNS,
                  children=[Column(children=children, spacing=4)])
    if on_resume is not None:
        # Escape out of the menu means the same thing the button does.
        panel.on_close = lambda _closing: on_resume()
    return panel


def browse_screen(library: Library,
                  on_open: Optional[Callable[[Entry], None]] = None,
                  on_cancel: Optional[Callable[[], None]] = None,
                  category: str = '') -> Panel:
    """The shelf: a category, a band of pictures, and what the selection is.

    Choosing a category rewrites the band in place rather than building another
    screen, so moving between shelves keeps the browser where it was.  The band
    shows :data:`SHOWN` entries at a time out of however many there are, which
    is what lets a shelf of several hundred lay out as fast as one of three; the
    page buttons move a bandful at a time, because reaching entry two hundred
    one arrow-press at a time is not browsing.
    """
    categories = library.categories()
    category = category if category in categories else (
        categories[0] if categories else '')

    chooser = Select(name='category', options=list(categories) or [''],
                     optionLabels=list(categories) or [_('(nothing)')],
                     value=category)
    chooser.enabled = bool(categories)
    band = Carousel(name='entry', visibleCount=SHOWN)
    note = Label(name='note', text='', wrap=True)
    entries: List[Entry] = []

    def show(shelf: Sequence[Entry]) -> None:
        """Point the band at one category's entries."""
        entries[:] = list(shelf)
        band.options = [entry.name for entry in entries]
        band.optionLabels = [entry.name for entry in entries]
        band.optionImages = [entry.preview for entry in entries]
        band.value = entries[0].name if entries else ''
        describe()

    def selected() -> Optional[Entry]:
        for entry in entries:
            if entry.name == band.value:
                return entry
        return None

    def describe() -> None:
        entry = selected()
        if entry is None:
            note.text = NOTHING if not entries else ''
        else:
            note.text = entry.note or entry.source

    def page(step: int) -> None:
        band.step(step * SHOWN)
        describe()

    def open_() -> None:
        entry = selected()
        if entry is not None and on_open is not None:
            on_open(entry)

    show(library.inCategory(category))

    back = _button('page-back', '<<', lambda: page(-1))
    forward = _button('page-forward', '>>', lambda: page(1))
    open_button = _button('open', _('Open'), open_, role='primary')
    cancel = _button('cancel', _('Cancel'), on_cancel)

    panel = Panel(title=_('Open'), name=BROWSE_NAME, scrim=True, modal=True,
                  preferredColumns=BROWSE_COLUMNS,
                  children=[Column(spacing=4, children=[
                      chooser,
                      band,
                      Row(name='paging', spacing=8,
                          children=[back, Spacer(), forward]),
                      note,
                      Separator(top=6),
                      Row(name='buttons', spacing=8, top=8,
                          children=[Spacer(), cancel, open_button]),
                  ])])

    def categoryChosen(_widget: Any) -> None:
        show(library.inCategory(str(chooser.value)))
        panel.dirty = True                  # the band is a different length now
    chooser.on_change = categoryChosen
    band.on_change = lambda _widget: describe()
    # Choosing a picture *is* choosing the model: making someone pick it and
    # then press Open is a step a gallery does not need.
    band.on_activate = lambda _widget: open_()
    if on_cancel is not None:
        # Only a close that carries nothing is a cancel.  Whoever handles a
        # choice closes the screen to get it out of the way -- ``close(True)``
        # -- and that is the opposite of Cancel, not another way of spelling it.
        panel.on_close = lambda closing: None if closing.result else on_cancel()
    return panel
