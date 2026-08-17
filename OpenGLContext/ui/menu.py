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
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from vrml import field, node

from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import Widget
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

    interactive = True
    focusable = True

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
        if self.hovered or self.focused:
            renderer.rect(self.rect, skin.rowFocus if self.focused
                          else skin.rowHover)
        colour = skin.labelText if self.enabled else skin.disabledText
        metrics = renderer.metrics
        pad_x = skin.buttonPadding(metrics)[0]
        body = self.rect.inset(pad_x)
        mark = self.mark()
        if self.checkable:
            renderer.textIn(body, mark + ' ', colour, align='left')
            body = Rect(body.x + metrics.text_width(mark + ' '), body.y,
                        max(0, body.width - metrics.text_width(mark + ' ')),
                        body.height)
        renderer.textIn(body, self.text, colour, align='left')
        trailing = self.shortcut or (self.SUBMENU if self.submenu else '')
        if trailing:
            renderer.textIn(body, trailing, skin.disabledText, align='right')


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
    hangs down from it, moves left to stay on screen, and opens *upwards*
    rather than being pushed up over what was clicked.
    """

    PROTO = 'Menu'
    #: The top-left corner the list opens from, in window pixels.
    anchor = field.newField('anchor', 'SFVec2f', 1, (0.0, 0.0))

    def __init__(self, **named: Any) -> None:
        named.setdefault('modal', True)
        super(Menu, self).__init__(**named)

    # -- where it goes -----------------------------------------------------
    def layout(self, viewport: Tuple[int, int], metrics: FontMetrics) -> None:
        self.link()
        view_width, view_height = int(viewport[0]), int(viewport[1])
        self.scaleSkin(metrics)
        self._title_height = 0
        width, height = self.natural_size(metrics, None)
        width, height = int(width), int(height)
        x = max(0, min(int(self.anchor[0]), view_width - width))
        top = int(self.anchor[1])
        if top - height < 0:
            # Down would run off the bottom, so open upwards from the anchor
            # rather than sliding up over whatever was clicked.
            top = min(view_height, top + height)
        self.rect = Rect(x, top - height, width, height)
        self._laidOut = ((view_width, view_height), metrics)
        self.arrange_content(metrics)

    def arrange_content(self, metrics: FontMetrics) -> None:
        """Rows, full width, one under the next with nothing between them."""
        content = self.contentRect()
        cursor = content.top
        for child in self.layoutChildren():
            height = int(child.natural_size(metrics, content.width)[1])
            child.parent = self
            child.arrange(Rect(content.x, cursor - height,
                               content.width, height), metrics)
            cursor -= height

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        widest = 0
        total = 0
        for child in self.layoutChildren():
            width, height = child.natural_size(metrics, available)
            widest = max(widest, int(width))
            total += int(height)
        pad = self.menuPadding(self.activeSkin()) * 2
        return (widest + pad, total + pad)

    def submenuAnchor(self, item: MenuItem) -> Tuple[float, float]:
        return (float(self.rect.x + self.rect.width), float(item.rect.top))

    # -- going away --------------------------------------------------------
    def pointer_pressed(self, x: float, y: float, button: int = 0) -> bool:
        """A press inside picks a row; one outside puts the menu away.

        Taken either way: a click that dismisses a menu is spent on dismissing
        it, and should not also press whatever was behind it.
        """
        if not self.rect.contains(x, y):
            self.dismissChain()
            return True
        return super(Menu, self).pointer_pressed(x, y, button)

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name == '<left>' and isinstance(self.parentMenu, Menu):
            self.dismiss()
            return True
        return super(Menu, self).key(name, modifiers)

    def chose(self, item: MenuItem) -> None:
        """Close this menu and every one it was opened from."""
        self.dismissChain()

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
