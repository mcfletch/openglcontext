"""How an overlay panel looks: colours, insets, and optional artwork.

A skin is a node, so a game authors one in a file alongside the screen it
paints.  The default is drawn from flat translucent rectangles and needs no
artwork at all, which matters for a viewer that is not a game and for the
first frame of one that is.

**Translucency is the default.** These panels sit over a live world and should
read as a layer on it, not a replacement for it.

Colours are RGBA (``SFVec4f``).  Insets and sizes are pixels, except the
horizontal padding of a button, which is in characters so a label never touches
its own frame at any font size.

Emphasis and focus are answered separately and deliberately:

* **Emphasis is a role rendered as text colour** -- ``primary``, ``secondary``
  or ``danger``.  One frame and three text colours rather than four states times
  three roles of near-identical artwork.
* **Focus is an additive glow drawn outside the widget's rectangle**, never the
  hover highlight.  The pointer can rest on one widget while the keyboard is on
  another, and a shared highlight makes that unreadable.  Outside rather than
  inset because a border either eats the padding or moves the label a pixel when
  focus arrives, and text that shifts as you Tab reads as broken.
"""

from typing import Any, Optional, Tuple

from vrml import field, node

#: Button emphasis.  ``primary`` is also the panel's Enter default.
PRIMARY = 'primary'
SECONDARY = 'secondary'
DANGER = 'danger'


class NineSlice(node.Node):
    """One image stretched to any size without distorting its corners.

    ``border`` is how many pixels of the source are corner: those four squares
    are drawn at their own size, the four edges stretch along one axis and the
    centre stretches along both.  Without this one button image cannot serve two
    button widths and a game ends up shipping an image per label.
    """

    PROTO = 'NineSlice'
    #: Where the image is, as a path or a file URL.  Loaded once per renderer
    #: and kept; a file that cannot be read leaves the widget with its flat
    #: fill rather than taking the frame down.
    url = field.newField('url', 'MFString', 1, list)
    #: Corner size in source pixels: left, top, right, bottom.
    border = field.newField('border', 'SFVec4f', 1, (0, 0, 0, 0))
    #: Multiplied into the sampled colour, so one greyscale frame can serve
    #: several states.
    tint = field.newField('tint', 'SFVec4f', 1, (1, 1, 1, 1))

    def borders(self) -> Tuple[int, int, int, int]:
        """Corner sizes as whole pixels, in the order left, top, right, bottom."""
        return tuple(int(value) for value in self.border)      # type: ignore[return-value]


class Skin(node.Node):
    """Colours, insets and artwork for one overlay's widgets."""

    PROTO = 'Skin'

    # -- panel ------------------------------------------------------------
    panelFill = field.newField('panelFill', 'SFVec4f', 1, (0.04, 0.05, 0.07, 0.88))
    panelBorder = field.newField('panelBorder', 'SFVec4f', 1, (0.5, 0.6, 0.75, 0.35))
    #: Dimming drawn over everything below a modal panel, so the eye goes to
    #: the question rather than the world behind it.
    scrimFill = field.newField('scrimFill', 'SFVec4f', 1, (0, 0, 0, 0.35))
    titleText = field.newField('titleText', 'SFVec4f', 1, (1, 1, 1, 1))
    labelText = field.newField('labelText', 'SFVec4f', 1, (0.88, 0.9, 0.94, 1))
    disabledText = field.newField('disabledText', 'SFVec4f', 1, (0.5, 0.52, 0.56, 1))

    # -- button -----------------------------------------------------------
    buttonFill = field.newField('buttonFill', 'SFVec4f', 1, (0.18, 0.21, 0.27, 0.95))
    buttonHoverFill = field.newField('buttonHoverFill', 'SFVec4f', 1, (0.28, 0.34, 0.44, 0.98))
    buttonDownFill = field.newField('buttonDownFill', 'SFVec4f', 1, (0.12, 0.14, 0.18, 1))
    buttonDisabledFill = field.newField('buttonDisabledFill', 'SFVec4f', 1, (0.14, 0.15, 0.17, 0.7))
    primaryText = field.newField('primaryText', 'SFVec4f', 1, (0.55, 0.82, 1.0, 1))
    secondaryText = field.newField('secondaryText', 'SFVec4f', 1, (0.9, 0.92, 0.95, 1))
    dangerText = field.newField('dangerText', 'SFVec4f', 1, (1.0, 0.55, 0.5, 1))

    # -- controls ---------------------------------------------------------
    checkFill = field.newField('checkFill', 'SFVec4f', 1, (0.1, 0.11, 0.14, 0.95))
    checkMark = field.newField('checkMark', 'SFVec4f', 1, (0.55, 0.9, 0.6, 1))
    trackFill = field.newField('trackFill', 'SFVec4f', 1, (0.1, 0.11, 0.14, 0.95))
    thumbFill = field.newField('thumbFill', 'SFVec4f', 1, (0.55, 0.66, 0.8, 1))
    fieldFill = field.newField('fieldFill', 'SFVec4f', 1, (0.08, 0.09, 0.11, 0.98))
    fieldText = field.newField('fieldText', 'SFVec4f', 1, (1, 1, 1, 1))
    caret = field.newField('caret', 'SFVec4f', 1, (1, 1, 1, 0.85))
    #: Additive, and drawn outside the widget: this is focus, not hover.
    focusGlow = field.newField('focusGlow', 'SFVec4f', 1, (0.35, 0.6, 0.9, 0.55))

    # -- console ----------------------------------------------------------
    consoleFill = field.newField('consoleFill', 'SFVec4f', 1, (0.02, 0.03, 0.04, 0.92))
    consoleText = field.newField('consoleText', 'SFVec4f', 1, (0.82, 0.86, 0.9, 1))
    consoleWarning = field.newField('consoleWarning', 'SFVec4f', 1, (1.0, 0.8, 0.4, 1))
    consoleError = field.newField('consoleError', 'SFVec4f', 1, (1.0, 0.5, 0.45, 1))

    # -- measurements -----------------------------------------------------
    #: Pixels between a panel's edge and its contents.
    panelPadding = field.newField('panelPadding', 'SFFloat', 1, 16.0)
    #: Pixels between one row of a panel and the next.
    rowSpacing = field.newField('rowSpacing', 'SFFloat', 1, 6.0)
    #: Characters either side of a button's label.
    buttonPaddingX = field.newField('buttonPaddingX', 'SFFloat', 1, 2.0)
    #: Pixels above and below a button's label.
    buttonPaddingY = field.newField('buttonPaddingY', 'SFFloat', 1, 6.0)
    #: Pixels either side of the text in a text field or a select.
    fieldPadding = field.newField('fieldPadding', 'SFFloat', 1, 4.0)
    #: Thickness of a slider's or scrollbar's track.
    trackThickness = field.newField('trackThickness', 'SFFloat', 1, 6.0)
    #: Width of a slider thumb and of a scrollbar.
    thumbWidth = field.newField('thumbWidth', 'SFFloat', 1, 12.0)
    scrollbarWidth = field.newField('scrollbarWidth', 'SFFloat', 1, 12.0)
    #: How far outside a focused widget its glow reaches.  Layout leaves this
    #: much room so the glow of a widget at the edge of a scrolling list is not
    #: clipped away by the viewport's scissor.
    focusMargin = field.newField('focusMargin', 'SFFloat', 1, 3.0)
    #: Border drawn around a panel; 0 for none.
    borderWidth = field.newField('borderWidth', 'SFFloat', 1, 1.0)

    # -- artwork ----------------------------------------------------------
    #: One nine-slice per widget state.  Any left NULL falls back to the flat
    #: fill colour above, so a game can skin the buttons and leave the rest.
    panelImage = field.newField('panelImage', 'SFNode', 1, node.NULL)
    buttonImage = field.newField('buttonImage', 'SFNode', 1, node.NULL)
    buttonHoverImage = field.newField('buttonHoverImage', 'SFNode', 1, node.NULL)
    buttonDownImage = field.newField('buttonDownImage', 'SFNode', 1, node.NULL)
    buttonDisabledImage = field.newField('buttonDisabledImage', 'SFNode', 1, node.NULL)
    checkEmptyImage = field.newField('checkEmptyImage', 'SFNode', 1, node.NULL)
    checkFullImage = field.newField('checkFullImage', 'SFNode', 1, node.NULL)
    trackImage = field.newField('trackImage', 'SFNode', 1, node.NULL)
    thumbImage = field.newField('thumbImage', 'SFNode', 1, node.NULL)
    fieldImage = field.newField('fieldImage', 'SFNode', 1, node.NULL)
    focusGlowImage = field.newField('focusGlowImage', 'SFNode', 1, node.NULL)

    # -- lookups ----------------------------------------------------------
    def roleText(self, role: str) -> Any:
        """Text colour for a button's emphasis."""
        if role == PRIMARY:
            return self.primaryText
        if role == DANGER:
            return self.dangerText
        return self.secondaryText

    def buttonState(self, hovered: bool = False, down: bool = False,
                    enabled: bool = True) -> Tuple[Any, Optional[NineSlice]]:
        """Fill colour and artwork for one button state."""
        if not enabled:
            return (self.buttonDisabledFill, self._image(self.buttonDisabledImage))
        if down:
            return (self.buttonDownFill, self._image(self.buttonDownImage))
        if hovered:
            return (self.buttonHoverFill, self._image(self.buttonHoverImage))
        return (self.buttonFill, self._image(self.buttonImage))

    @staticmethod
    def _image(value: Any) -> Optional[NineSlice]:
        return value if value else None

    def buttonPadding(self, metrics: Any) -> Tuple[int, int]:
        """A button's padding in pixels, from its character-based width."""
        return (int(self.buttonPaddingX * metrics.char_width),
                int(self.buttonPaddingY))


#: Used by any panel that names no skin of its own.
DEFAULT_SKIN = Skin()


def skin_for(widget: Any) -> Skin:
    """The skin a widget paints with: its panel's, or the default.

    Looked up through the tree rather than stored per widget so a game can swap
    one panel's skin without touching the widgets in it.
    """
    root = widget.root() if hasattr(widget, 'root') else widget
    skin = getattr(root, 'skin', None)
    return skin if isinstance(skin, Skin) else DEFAULT_SKIN
