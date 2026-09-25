"""Menus: a short list of things to do, opened at a point.

The overlay toolkit has *screens* -- settings pages, dialogs, a console -- and
controls to put on them. A menu is the control an application reaches for when
there are more things to do than there is room for buttons: a bar of titles
along the top of the window, a list under each of them, and the same list at
the pointer on a right-click.

A menu is a :class:`~OpenGLContext.ui.panel.Panel`, so it already has focus, a
skin, accelerators and the Escape that closes it; what it adds is where it
opens, rows instead of a column of buttons, and going away once something has
been chosen. An item is a :class:`~OpenGLContext.ui.widgets.Widget`, so the
pointer and the keyboard reach it the way they reach any other.

::

    bar = MenuBar(menus=[
        ('File', [MenuItem(text='Open', shortcut='<ctrl-o>', on_activate=open_),
                  Separator(),
                  MenuItem(text='Quit', on_activate=quit_)]),
        ('View', [MenuItem(text='Wireframe', checkable=True,
                           on_activate=set_wireframe)]),
    ], stack=context.overlays)
    context.addHUDLayer(bar)

An item with a ``submenu`` opens another menu beside itself instead of doing
anything; choosing something in *that* closes the whole chain, because a menu
still up after the thing was done is in the way.

A pop-up menu is the same list opened at a point -- under a control, or where
the pointer was right-clicked -- and put on the overlay stack, where its
submenus then open::

    context.pushOverlay(Menu(anchor=(x, y), items=[
        MenuItem(text='Rename', on_activate=rename),
        MenuItem(text='Delete', on_activate=delete),
        MenuItem(text='Move to', submenu=[...]),
    ]))

The row under the pointer is the row the keyboard is on, so the arrows carry
on from where the pointer left off. Every row is given a letter of its own,
underlined, which runs it while the menu is up: the first letter of one of its
words where that is free, and otherwise the first letter of it that is.
``mnemonic`` names the letter where the automatic one will not do, and
``mnemonics=False`` gives a menu none. A chosen row runs at once and the menu
stays up for ``linger`` seconds more, long enough for the row's ripple to say
which was chosen.
"""
from __future__ import annotations

from typing import Any, Iterator, List, Optional, Sequence, Set, Tuple

from vrml import field, node

from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import Separator, Widget
from OpenGLContext.hud import Rect

__all__ = ['MenuItem', 'Menu', 'MenuBar']

#: Space between an item's text and its shortcut, in characters, so the two
#: never run together on the widest row.
SHORTCUT_GAP = 3


class MenuItem(Widget):
    """One line of a menu: what it says, what it does, and what it answers to.

    ``shortcut`` is a key name (``'<ctrl-o>'``) that runs the item from
    anywhere in the menu, and is drawn along the right so the reader learns it.
    ``checkable`` makes the item a setting rather than an action: it draws its
    state and flips it when chosen. ``submenu`` makes it a way in to another
    list rather than something that happens.
    """

    PROTO = 'MenuItem'
    text = field.newField('text', 'SFString', 1, '')
    shortcut = field.newField('shortcut', 'SFString', 1, '')
    #: Whether this item is a setting that is on or off rather than an action.
    checkable = field.newField('checkable', 'SFBool', 1, False)
    checked = field.newField('checked', 'SFBool', 1, False)
    #: The items this one leads to; empty for an item that does something.
    submenu = node.MFNode('submenu')
    #: The letter that runs this item while its menu is up; empty for the one
    #: the menu gives it.
    mnemonic = field.newField('mnemonic', 'SFString', 1, '')

    interactive = True
    focusable = True
    #: A row paints the menu's highlight instead.
    washOnHover = False
    #: The letter the menu gave this item, where it names none of its own.
    _assigned: str = ''

    def accessKey(self) -> str:
        """The lower-case letter that runs this item, or ``''`` for none."""
        return (str(self.mnemonic)[:1] or self._assigned).lower()

    def accessIndex(self) -> int:
        """Where in ``text`` the access key is underlined, or -1 where it is not in it."""
        key = self.accessKey()
        if not key:
            return -1
        text = str(self.text).lower()
        for word in _word_starts(text):
            if text[word] == key:
                return word
        return text.find(key)

    def highlighted(self) -> bool:
        """Whether this row is lit: the one a click or Enter would run.

        Where the keyboard is, in a menu; a pointer that has left the row for
        another, or been overtaken by the arrow keys, does not keep it lit.
        """
        return bool(self.enabled and (self.focused or (
            self.hovered and not isinstance(self.root(), Menu))))

    #: What is drawn in the mark column. Text rather than artwork, so an item
    #: reads the same in every font the interface is drawn in.
    CHECKED = '[x]'
    UNCHECKED = '[ ]'
    SUBMENU = '>'

    def mark(self) -> str:
        """The mark this item carries: its check, its arrow, or nothing."""
        if self.submenu:
            return self.SUBMENU
        if self.checkable:
            return self.CHECKED if self.checked else self.UNCHECKED
        return ''

    # -- measuring ---------------------------------------------------------
    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        skin = self.activeSkin()
        pad_x, pad_y = skin.buttonPadding(metrics)
        width = metrics.text_width(self.text)
        if self.checkable:
            width += metrics.text_width(self.UNCHECKED + ' ')
        if self.shortcut:
            width += metrics.char_width * SHORTCUT_GAP \
                + metrics.text_width(self.shortcut)
        elif self.submenu:
            width += metrics.char_width * SHORTCUT_GAP \
                + metrics.text_width(self.SUBMENU)
        return (width + pad_x * 2, metrics.char_height + pad_y)

    # -- acting ------------------------------------------------------------
    def accelerate(self, name: str) -> bool:
        if self.enabled and self.shortcut and name == self.shortcut:
            self.activate()
            return True
        return False

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name in ('<return>', ' ') and self.enabled:
            self.activate()
            return True
        if name == '<right>' and self.submenu:
            self.activate()
            return True
        return False

    def activate(self) -> None:
        """Do this item: open its list, flip its setting, or run its action."""
        if not self.enabled:
            return
        menu = self.root()
        if self.submenu:
            opener = getattr(menu, 'openSubmenu', None)
            if opener is not None:
                opener(self)
                return
        if self.checkable:
            self.checked = not self.checked
            self.changed()
        super(MenuItem, self).activate()
        chose = getattr(menu, 'chose', None)
        if chose is not None:
            chose(self)

    # -- drawing -----------------------------------------------------------
    def paint(self, renderer: Any) -> None:
        skin = renderer.skin
        if self.highlighted():
            renderer.rect(self.rect, skin.menuHighlight)
        colour = skin.labelText if self.enabled else skin.disabledText
        metrics = renderer.metrics
        pad_x = skin.buttonPadding(metrics)[0]
        body = self.rect.inset(pad_x, 0, pad_x, 0)
        mark = self.mark()
        if self.checkable:
            renderer.textIn(body, mark + ' ', colour, align='left')
            body = Rect(body.x + metrics.text_width(mark + ' '), body.y,
                        max(0, body.width - metrics.text_width(mark + ' ')),
                        body.height)
        renderer.textIn(body, self.text, colour, align='left')
        self.paintAccessKey(renderer, body, colour)
        trailing = self.shortcut or (self.SUBMENU if self.submenu else '')
        if trailing:
            renderer.textIn(body, trailing, skin.disabledText, align='right')


    def paintAccessKey(self, renderer: Any, body: Rect, colour: Any) -> None:
        """Underline the letter that runs this item, where the text holds it."""
        index = self.accessIndex()
        if index < 0:
            return
        metrics = renderer.metrics
        text = str(self.text)
        left = body.x + metrics.text_width(text[:index])
        width = max(metrics.text_width(text[index]), 1)
        # Under the letters of the character cell ``textIn`` centres in the row.
        cell = body.y + (body.height - metrics.char_height) // 2
        renderer.rect(Rect(left, cell + metrics.underline, width, 1), colour)


def _word_starts(text: str) -> List[int]:
    """Where each word of ``text`` begins."""
    return [index for index, letter in enumerate(text)
            if letter.isalnum() and (index == 0 or not text[index - 1].isalnum())]


def assign_access_keys(items: Sequence['MenuItem']) -> None:
    """Give each item without a mnemonic a letter no other item in the list has.

    The first letter of one of its words where one is free, then any letter
    or digit of its text; an item whose every letter is taken gets none.
    """
    taken: Set[str] = {str(item.mnemonic)[:1].lower() for item in items
                       if item.mnemonic}
    for item in items:
        item._assigned = ''
        if item.mnemonic:
            continue
        text = str(item.text).lower()
        starts = _word_starts(text)
        rest = [index for index, letter in enumerate(text)
                if letter.isalnum() and index not in starts]
        for index in starts + rest:
            if text[index] not in taken:
                item._assigned = text[index]
                taken.add(text[index])
                break


def _walkItems(items: Sequence[Widget]) -> Iterator[MenuItem]:
    """Each item, then whatever hangs off it, depth first."""
    for item in items:
        if not isinstance(item, MenuItem):
            continue
        yield item
        if item.submenu:
            yield from _walkItems(list(item.submenu))


class _MenuPanel(Panel):
    """What a menu and a menu bar have in common: items, and opening lists.

    Neither is a settings screen: the rows are the whole of the panel, there is
    no title, and what a click does is run something and get out of the way.
    """

    def __init__(self, items: Optional[Sequence[Widget]] = None,
                 stack: Any = None, parentMenu: Any = None,
                 **named: Any) -> None:
        super(_MenuPanel, self).__init__(**named)
        #: The overlay stack this belongs to, which is what a submenu is
        #: opened on and what the chain is closed through.
        self.stack = stack
        #: The menu this one was opened from, if any.
        self.parentMenu = parentMenu
        #: What this was last laid out against, so a submenu opened from it can
        #: be put in the right place at once rather than on the next frame.
        self._laidOut: Optional[Tuple[Tuple[int, int], FontMetrics]] = None
        if items:
            self.children = list(items)

    def menuPadding(self, skin: Any) -> int:
        """The margin round the rows. A menu is a list, not a dialog: the
        cushion a settings page wants round its controls would leave a menu
        floating in the middle of a much bigger box."""
        return max(1, int(skin.rowSpacing) // 2)

    def contentRect(self) -> Rect:
        return self.rect.inset(self.menuPadding(self.activeSkin()))

    def items(self) -> List[MenuItem]:
        """This panel's own items, in the order they are drawn."""
        return [child for child in self.layoutChildren()
                if isinstance(child, MenuItem)]

    def allItems(self) -> Iterator[MenuItem]:
        """Every item of this menu and of the lists hanging off it.

        A key and a menu item often do the same thing, and the item's tick has
        to follow either of them. A title's list is its ``submenu``, which is
        not among its children until the list is opened -- by which time the
        tick is already wrong -- so an application looking for an item to tick
        walks this rather than the widget tree.
        """
        return _walkItems(self.items())

    def submenuAnchor(self, item: MenuItem) -> Tuple[float, float]:
        """Where the list this item leads to should open."""
        raise NotImplementedError

    def openSubmenu(self, item: MenuItem) -> Optional['Menu']:
        """Open the list an item leads to, beside the item rather than over it."""
        if self.stack is None:
            return None
        opened = Menu(items=list(item.submenu), anchor=self.submenuAnchor(item),
                      stack=self.stack, parentMenu=self)
        if self._laidOut is not None:
            self.stack.push(opened, *self._laidOut)
        else:
            self.stack.push(opened)
        return opened

    def chose(self, item: MenuItem) -> None:
        """Something was chosen: put away whatever is in the way of seeing it."""

    def dismiss(self) -> None:
        """Put this away without choosing anything."""
        self.close(None)


class Menu(_MenuPanel):
    """A list of items, opened at a point on the screen.

    ``anchor`` is where the top-left corner goes, in window pixels. The menu
    hangs down from it and moves left to stay on screen. Where there is no
    room below it opens *upwards*, sitting on ``above`` -- the top edge of the
    control that opened it, so the list does not cover what was clicked -- or
    on the anchor where that is not given. A list with room neither way is
    moved as little as keeps it inside the window.
    """

    PROTO = 'Menu'
    #: The top-left corner the list opens from, in window pixels.
    anchor = field.newField('anchor', 'SFVec2f', 1, (0.0, 0.0))
    #: The height the list sits on when it opens upwards, in window pixels;
    #: below 0 for the anchor's own.
    above = field.newField('above', 'SFFloat', 1, -1.0)
    #: Whether each row is given a letter that runs it.
    mnemonics = field.newField('mnemonics', 'SFBool', 1, True)
    #: How long the menu stays up once something is chosen, in seconds, so
    #: the chosen row's ripple is seen. 0 puts it away at once.
    linger = field.newField('linger', 'SFFloat', 1, 0.2)

    #: When the menu goes away, once something has been chosen; None before.
    _closingAt: Optional[float] = None

    def __init__(self, **named: Any) -> None:
        named.setdefault('modal', True)
        super(Menu, self).__init__(**named)
        self.assignAccessKeys()

    def assignAccessKeys(self) -> None:
        """Settle each row's access key: see :func:`assign_access_keys`."""
        rows = self.items()
        if self.mnemonics:
            assign_access_keys(rows)
        else:
            for row in rows:
                row._assigned = ''

    # -- where it goes -----------------------------------------------------
    def layout(self, viewport: Tuple[int, int], metrics: FontMetrics) -> None:
        self.link()
        self.assignAccessKeys()
        view_width, view_height = int(viewport[0]), int(viewport[1])
        self.scaleSkin(metrics)
        self._title_height = 0
        width, height = self.natural_size(metrics, None)
        width, height = int(width), int(height)
        x = max(0, min(int(self.anchor[0]), view_width - width))
        self.rect = Rect(x, self._top(height, view_height) - height,
                         width, height)
        self._laidOut = ((view_width, view_height), metrics)
        self.arrange_content(metrics)

    def _top(self, height: int, view_height: int) -> int:
        """Where the list's top edge goes in a window ``view_height`` tall."""
        below = int(self.anchor[1])
        if below - height >= 0:
            return below
        base = int(self.above) if float(self.above) >= 0.0 else below
        if base + height <= view_height:
            return base + height
        # Room neither way: as near the anchor as keeps it on screen, and
        # from the top of the window for a list taller than the window.
        return min(view_height, max(below, height))

    def rowHeight(self, child: Widget, metrics: FontMetrics,
                  available: Optional[int] = None) -> int:
        """How tall a row of this menu is: its own height, and room round a separator."""
        height = int(child.natural_size(metrics, available)[1])
        if isinstance(child, Separator):
            height += max(child.activeSkin().buttonPadding(metrics)[1] // 2, 2) * 2
        return height

    def arrange_content(self, metrics: FontMetrics) -> None:
        """Rows, full width, one under the next with nothing between them."""
        content = self.contentRect()
        cursor = content.top
        for child in self.layoutChildren():
            height = self.rowHeight(child, metrics, content.width)
            child.parent = self
            child.arrange(Rect(content.x, cursor - height,
                               content.width, height), metrics)
            cursor -= height

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        widest = 0
        total = 0
        for child in self.layoutChildren():
            widest = max(widest, int(child.natural_size(metrics, available)[0]))
            total += self.rowHeight(child, metrics, available)
        pad = self.menuPadding(self.activeSkin()) * 2
        return (widest + pad, total + pad)

    def submenuAnchor(self, item: MenuItem) -> Tuple[float, float]:
        return (float(self.rect.x + self.rect.width), float(item.rect.top))

    # -- the pointer and the keys -------------------------------------------
    @property
    def choosing(self) -> bool:
        """Whether something has been chosen and the menu is about to go."""
        return self._closingAt is not None

    def pointer_moved(self, x: float, y: float) -> bool:
        """Light the row under the pointer, and put the keyboard on it."""
        moved = super(Menu, self).pointer_moved(x, y)
        found = self.hovered_widget
        if isinstance(found, MenuItem) and found is not self.focused_widget:
            self.focus(found, visible=False)
            return True
        return moved

    def pointer_pressed(self, x: float, y: float, button: int = 0) -> bool:
        """A press inside picks a row; one outside puts the menu away.

        Taken either way: a click that dismisses a menu is spent on dismissing
        it, and should not also press whatever was behind it.
        """
        if self.choosing:
            return True
        if not self.rect.contains(x, y):
            self.dismissChain()
            return True
        return super(Menu, self).pointer_pressed(x, y, button)

    def pointer_released(self, x: float, y: float, button: int = 0) -> bool:
        if self.choosing:
            return True
        return super(Menu, self).pointer_released(x, y, button)

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if self.choosing:
            return name != '<escape>' or super(Menu, self).key(name, modifiers)
        if name == '<left>' and isinstance(self.parentMenu, Menu):
            self.dismiss()
            return True
        return super(Menu, self).key(name, modifiers)

    def character(self, text: str) -> bool:
        """A typed letter runs the row it is the access key of."""
        if self.choosing:
            return True
        if super(Menu, self).character(text):
            return True
        wanted = str(text)[:1].lower()
        if not wanted:
            return False
        for row in self.items():
            if row.enabled and row.accessKey() == wanted:
                self.focus(row, visible=True)
                row.activate()
                return True
        return False

    # -- going away --------------------------------------------------------
    def chose(self, item: MenuItem) -> None:
        """Something was chosen: put this menu and the ones it hangs off away.

        After ``linger`` seconds, in which nothing more can be chosen; at once
        where that is 0.
        """
        from OpenGLContext.events import systemtime
        chain: Optional[Any] = self
        while isinstance(chain, Menu):
            chain._closingAt = systemtime.systemTime() + max(float(chain.linger), 0.0)
            chain = chain.parentMenu
        if float(self.linger) <= 0.0:
            self.dismissChain()

    def tick(self, now: float) -> None:
        """Put the menu away once a choice has lingered for long enough."""
        if self._closingAt is not None and float(now) >= self._closingAt:
            self.dismissChain()

    def animating(self, now: float) -> bool:
        """Moving while a choice lingers, as well as while a row ripples."""
        moving = super(Menu, self).animating(now)
        return moving or (self._closingAt is not None and not self.closed)

    def dismissChain(self) -> None:
        """Put this menu away, and the ones it hangs off."""
        parent = self.parentMenu
        self.dismiss()
        if isinstance(parent, Menu):
            parent.dismissChain()


class MenuBar(_MenuPanel):
    """Titles along the top of the window, each opening its own list.

    Not modal and not a wall: a click that misses the bar is offered to
    whatever is under it, so the world carries on being usable while the bar is
    on screen.
    """

    PROTO = 'MenuBar'

    def __init__(self, menus: Optional[Sequence[Tuple[str, Sequence[Widget]]]] = None,
                 **named: Any) -> None:
        named.setdefault('modal', False)
        named.setdefault('closeOnEscape', False)
        titles = [MenuItem(text=title, submenu=list(items))
                  for title, items in (menus or ())]
        super(MenuBar, self).__init__(items=titles, **named)

    def layout(self, viewport: Tuple[int, int], metrics: FontMetrics) -> None:
        self.link()
        view_width, view_height = int(viewport[0]), int(viewport[1])
        self.scaleSkin(metrics)
        self._title_height = 0
        height = int(self.natural_size(metrics, view_width)[1])
        self.rect = Rect(0, view_height - height, view_width, height)
        self._laidOut = ((view_width, view_height), metrics)
        self.arrange_content(metrics)

    def arrange_content(self, metrics: FontMetrics) -> None:
        """Titles left to right, each as wide as its own text."""
        content = self.contentRect()
        cursor = content.x
        for child in self.layoutChildren():
            width = int(child.natural_size(metrics, content.width)[0])
            child.parent = self
            child.arrange(Rect(cursor, content.y, width, content.height),
                          metrics)
            cursor += width

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        width = 0
        tallest = 0
        for child in self.layoutChildren():
            size = child.natural_size(metrics, available)
            width += int(size[0])
            tallest = max(tallest, int(size[1]))
        pad = self.menuPadding(self.activeSkin()) * 2
        return (width + pad, tallest + pad)

    def submenuAnchor(self, item: MenuItem) -> Tuple[float, float]:
        return (float(item.rect.x), float(self.rect.y))
