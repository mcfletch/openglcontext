"""A strip of tools down the side of the window, one button each.

An editor's pointer does a different thing in each tool -- drawing a line,
moving the map, raising ground -- and :class:`~OpenGLContext.edit.tools.ToolManager`
is what holds which of them is in force. This is that manager on screen: one
button per declared tool, the one in force lit, and a click puts the pointer
into that tool.

It is a sibling of :class:`~OpenGLContext.ui.menu.MenuBar` and is used the same
way -- a panel at the bottom of the overlay stack rather than a HUD layer,
because a HUD takes no events and a palette is nothing but events::

    palette = ToolPalette(tools=context.tools, reserved=MENU_BAR_ROOM)
    context.overlays.push(palette)

The menus keep the operations that apply to the whole document; the palette
keeps the verbs the pointer performs. A designer reaching for "raise this hill"
should not have to go through a menu to say so, and a designer looking for
"save" should not have to hunt along a row of tools.
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from vrml import field

from OpenGLContext.hud import Rect
from OpenGLContext.ui.metrics import REFERENCE_METRICS, FontMetrics
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import Widget

__all__ = ['ToolButton', 'ToolPalette']

#: Which side of the window the strip runs down.
LEFT, RIGHT = 'left', 'right'


class ToolButton(Widget):
    """One tool, as a button that says whether it is the one in force.

    The state is read from the manager rather than kept here, so a tool chosen
    by a keyboard shortcut, by a menu or by the application itself lights the
    same button a click would have lit, and a manager that *refuses* the change
    -- which it does part-way through a gesture -- leaves the strip telling the
    truth about what the pointer is actually doing.
    """

    PROTO = 'ToolButton'
    text = field.newField('text', 'SFString', 1, '')
    #: The tool this button selects, by :attr:`ToolMode.name`.
    tool = field.newField('tool', 'SFString', 1, '')

    interactive = True
    focusable = True

    #: The :class:`~OpenGLContext.edit.tools.ToolManager` this button reads and
    #: drives. Not a field: a manager is not something to serialise, so it is
    #: taken as an ordinary argument and kept as an ordinary attribute.
    tools: Any = None

    def __init__(self, tools: Any = None, **named: Any) -> None:
        super(ToolButton, self).__init__(**named)
        self.tools = tools

    def active(self) -> bool:
        """Whether this button's tool is the one the pointer drives."""
        current = getattr(self.tools, 'active', None)
        return bool(current is not None and current.name == str(self.tool))

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        pad_x, pad_y = self.activeSkin().buttonPadding(metrics)
        return (metrics.text_width(self.text) + pad_x * 2,
                metrics.char_height + pad_y * 2)

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name in ('<return>', ' ') and self.enabled:
            self.activate()
            return True
        return False

    def activate(self) -> None:
        select = getattr(self.tools, 'select', None)
        if select is not None:
            select(str(self.tool))
        super(ToolButton, self).activate()

    def paint(self, renderer: Any) -> None:
        self.paintFocus(renderer)
        skin = renderer.skin
        on = self.active()
        fill, image = skin.buttonState(hovered=self.hovered, down=self.armed,
                                       enabled=bool(self.enabled))
        if on:
            # The tool in force reads as a *state*, not as a hover: the pointer
            # can be resting on one button while another is the tool being
            # used, and one highlight for both makes the strip unreadable.
            fill = skin.switchOnFill
        renderer.frame(self.rect, fill, image)
        if self.enabled:
            colour = skin.titleText if on else skin.labelText
        else:
            colour = skin.disabledText
        renderer.textIn(self.rect, self.text, colour, align='left')


class ToolPalette(Panel):
    """The tools, down one side of the window, with the one in force lit.

    ``reserved`` is how much of the top of the window something else has
    already taken -- a menu bar, usually -- in reference pixels, so the strip
    starts under it rather than through it. ``edge`` puts it down the left or
    the right.
    """

    PROTO = 'ToolPalette'
    #: ``left`` or ``right``.
    edge = field.newField('edge', 'SFString', 1, LEFT)
    #: Pixels of the window top already spoken for, at the reference font size.
    reserved = field.newField('reserved', 'SFFloat', 1, 0.0)

    def __init__(self, tools: Any = None, **named: Any) -> None:
        named.setdefault('modal', False)
        named.setdefault('closeOnEscape', False)
        super(ToolPalette, self).__init__(**named)
        #: The manager whose tools are drawn and driven.
        self.tools = tools
        self.rebuild()

    # -- what is in it -----------------------------------------------------
    def rebuild(self) -> None:
        """Make a button for each of the manager's tools.

        Called when the set of tools changes -- a project opened, a mode added
        -- rather than every frame: the labels are text, and measuring them is
        what layout is for.
        """
        self.children = [
            ToolButton(text=tool.label or tool.name, tool=tool.name,
                       tools=self.tools)
            for tool in getattr(self.tools, 'tools', ())
        ]

    def buttons(self) -> List[ToolButton]:
        """The buttons, in the order they are drawn."""
        return [child for child in self.layoutChildren()
                if isinstance(child, ToolButton)]

    def room(self, metrics: Optional[FontMetrics] = None) -> float:
        """How much of the window's width this strip wants, in reference pixels.

        What a HUD is told to keep clear (``HUDLayer.reserved``). That is in
        *reference* pixels, because a HUD is authored once and scaled to the
        window it is drawn in, so the strip's real width is divided back out by
        the same scale. Pass the metrics the interface is being drawn at; with
        none, the answer is the reference-size strip, which is what to reserve
        before there is a font to measure against.
        """
        metrics = metrics or REFERENCE_METRICS
        self.link()
        self.scaleSkin(metrics)
        width = float(self.natural_size(metrics, None)[0])
        return width / max(float(getattr(metrics, 'scale', 1.0)), 1e-6)

    # -- where it goes -----------------------------------------------------
    def layout(self, viewport: Tuple[int, int], metrics: FontMetrics) -> None:
        self.link()
        view_width, view_height = int(viewport[0]), int(viewport[1])
        self.scaleSkin(metrics)
        self._title_height = 0
        width, height = self.natural_size(metrics, None)
        width, height = int(width), int(height)
        top = view_height - metrics.pixels(self.reserved)
        x = 0 if str(self.edge) != RIGHT else max(0, view_width - width)
        self.rect = Rect(x, max(0, top - height), width, min(height, top))
        self.arrange_content(metrics)

    def arrange_content(self, metrics: FontMetrics) -> None:
        """Buttons full width, one under the next, from the top down."""
        content = self.contentRect()
        spacing = int(self.activeSkin().rowSpacing)
        cursor = content.top
        for child in self.layoutChildren():
            height = int(child.natural_size(metrics, content.width)[1])
            child.parent = self
            child.arrange(Rect(content.x, cursor - height,
                               content.width, height), metrics)
            cursor -= height + spacing

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        children = list(self.layoutChildren())
        widest = 0
        total = 0
        for child in children:
            width, height = child.natural_size(metrics, available)
            widest = max(widest, int(width))
            total += int(height)
        spacing = int(self.activeSkin().rowSpacing) * max(0, len(children) - 1)
        pad = int(self.activeSkin().panelPadding)
        return (widest + pad, total + spacing + pad)

    def contentRect(self) -> Rect:
        return self.rect.inset(int(self.activeSkin().panelPadding) // 2)

    # -- what the world behind it hears ------------------------------------
    def pointer_pressed(self, x: float, y: float, button: int = 0) -> bool:
        """A press anywhere on the strip is the strip's.

        Including the gaps between buttons: the palette stands over a document
        the pointer also draws on, and a click that missed a button by two
        pixels must not put a point down on the map underneath it.
        """
        taken = super(ToolPalette, self).pointer_pressed(x, y, button)
        return taken or self.rect.contains(x, y)
