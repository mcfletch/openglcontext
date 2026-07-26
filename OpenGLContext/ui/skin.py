"""How an overlay panel looks: colours, insets, and optional artwork.

A skin is a node, so a game authors one in a file alongside the screen it
paints.  The default is drawn from flat translucent rectangles and needs no
artwork at all, which matters for a viewer that is not a game and for the
first frame of one that is.

**Translucency is the default.** These panels sit over a live world and should
read as a layer on it, not a replacement for it.

Colours are RGBA (``SFVec4f``).  Insets and sizes are **pixels at the reference
font size** and are multiplied by the interface scale before anything is
measured against them (:meth:`Skin.scaled`, and
:mod:`OpenGLContext.ui.metrics` for where the scale comes from), so a skin is
authored once and a 4K display gets a switch that is still a comfortable
target.  The one exception is the horizontal padding of a button, which is in
characters, so a label never touches its own frame at any font size.

Emphasis and focus are answered separately and deliberately:

* **Emphasis is a role rendered as text colour** -- ``primary``, ``secondary``
  or ``danger``.  One frame and three text colours rather than four states times
  three roles of near-identical artwork.
* **Focus is a ring drawn outside the widget's rectangle** -- a solid border and
  an additive glow -- and never the hover highlight.  The pointer can rest on
  one widget while the keyboard is on another, and a shared highlight makes that
  unreadable.  Outside rather than inset because a border drawn inside either
  eats the padding or moves the label a pixel when focus arrives, and text that
  shifts as you Tab reads as broken.  Two marks rather than one because either
  alone is unreliable over a world the panel does not control: a glow disappears
  against a bright scene, a thin ring against a busy one.
* **A row of a settings page is a thing in itself**: ``rowRule`` separates one
  from the next and ``rowHover``/``rowFocus`` wash the active one, so the eye
  runs from a label on the left to its control on the right without losing the
  line.
"""

from typing import Any, Sequence, Tuple

from vrml import field, node, protofunctions

from OpenGLContext.ui.metrics import FontMetrics

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
    #: Where the image is, as a filesystem path or a ``file:`` URL.  Several
    #: are alternatives, tried in order, as an MFString ``url`` is everywhere
    #: else.  Loaded once per renderer and kept; one that cannot be read leaves
    #: the widget with its flat fill rather than taking the frame down.
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
    #: The switch's track, off and on.  On is the accent colour, because the
    #: one question a player scanning a settings page asks is which of these
    #: are on, and an answer they have to squint at is no answer.
    switchOffFill = field.newField('switchOffFill', 'SFVec4f', 1, (0.16, 0.17, 0.21, 1))
    switchOnFill = field.newField('switchOnFill', 'SFVec4f', 1, (0.28, 0.62, 0.42, 1))
    #: The knob that slides between the ends.
    switchKnob = field.newField('switchKnob', 'SFVec4f', 1, (0.97, 0.98, 1.0, 1))
    #: Text marking something as set apart -- a captured key, a live value.
    accentText = field.newField('accentText', 'SFVec4f', 1, (0.55, 0.9, 0.6, 1))
    trackFill = field.newField('trackFill', 'SFVec4f', 1, (0.1, 0.11, 0.14, 0.95))
    thumbFill = field.newField('thumbFill', 'SFVec4f', 1, (0.55, 0.66, 0.8, 1))
    fieldFill = field.newField('fieldFill', 'SFVec4f', 1, (0.08, 0.09, 0.11, 0.98))
    fieldText = field.newField('fieldText', 'SFVec4f', 1, (1, 1, 1, 1))
    caret = field.newField('caret', 'SFVec4f', 1, (1, 1, 1, 0.85))
    #: Additive, and drawn outside the widget: this is focus, not hover.
    focusGlow = field.newField('focusGlow', 'SFVec4f', 1, (0.35, 0.6, 0.9, 0.5))
    #: Drawn as a solid ring just outside the widget, under the glow.  A glow
    #: alone reads as a smudge over a busy world; the ring is what says
    #: *this one*.
    focusBorder = field.newField('focusBorder', 'SFVec4f', 1, (0.55, 0.78, 1.0, 0.95))

    # -- rows -------------------------------------------------------------
    #: Hairline between one row of a settings page and the next.  Faint: it is
    #: there to let the eye run from a label to its control, not to draw a
    #: table.
    rowRule = field.newField('rowRule', 'SFVec4f', 1, (0.75, 0.82, 0.95, 0.13))
    #: Wash over the row the pointer is on or the keyboard is in, so a row is a
    #: target rather than two things that happen to be side by side.
    rowHover = field.newField('rowHover', 'SFVec4f', 1, (1, 1, 1, 0.06))
    rowFocus = field.newField('rowFocus', 'SFVec4f', 1, (0.35, 0.6, 0.9, 0.14))

    # -- console ----------------------------------------------------------
    consoleFill = field.newField('consoleFill', 'SFVec4f', 1, (0.02, 0.03, 0.04, 0.92))
    consoleText = field.newField('consoleText', 'SFVec4f', 1, (0.82, 0.86, 0.9, 1))
    consoleWarning = field.newField('consoleWarning', 'SFVec4f', 1, (1.0, 0.8, 0.4, 1))
    consoleError = field.newField('consoleError', 'SFVec4f', 1, (1.0, 0.5, 0.45, 1))

    # -- measurements -----------------------------------------------------
    # All in pixels **at the reference font size**, and multiplied by the
    # interface scale in :meth:`scaled`.  See :data:`SCALED_FIELDS`.
    #: Pixels between a panel's edge and its contents.
    panelPadding = field.newField('panelPadding', 'SFFloat', 1, 20.0)
    #: Pixels between one row of a panel and the next.
    rowSpacing = field.newField('rowSpacing', 'SFFloat', 1, 8.0)
    #: Pixels above and below the contents of one row of a settings page.
    #: Room to breathe, and a bigger target for the pointer.
    rowPadding = field.newField('rowPadding', 'SFFloat', 1, 7.0)
    #: Pixels between a label column and the control beside it.
    columnSpacing = field.newField('columnSpacing', 'SFFloat', 1, 16.0)
    #: Characters either side of a button's label.  Not scaled: the characters
    #: are already the right size for the font.
    buttonPaddingX = field.newField('buttonPaddingX', 'SFFloat', 1, 2.0)
    #: Pixels above and below a button's label.
    buttonPaddingY = field.newField('buttonPaddingY', 'SFFloat', 1, 8.0)
    #: Pixels either side of the text in a text field or a select.
    fieldPadding = field.newField('fieldPadding', 'SFFloat', 1, 6.0)
    #: Thickness of a slider's or scrollbar's track.
    trackThickness = field.newField('trackThickness', 'SFFloat', 1, 6.0)
    #: Width of a slider thumb and of a scrollbar.
    thumbWidth = field.newField('thumbWidth', 'SFFloat', 1, 14.0)
    scrollbarWidth = field.newField('scrollbarWidth', 'SFFloat', 1, 14.0)
    #: The switch a boolean is edited with: the track's length and its height.
    switchWidth = field.newField('switchWidth', 'SFFloat', 1, 44.0)
    switchHeight = field.newField('switchHeight', 'SFFloat', 1, 24.0)
    #: Pixels between the switch's knob and the edge of its track.
    switchInset = field.newField('switchInset', 'SFFloat', 1, 3.0)
    #: How far outside a focused widget its ring and glow reach.  Layout leaves
    #: this much room so the ring of a widget at the edge of a scrolling list
    #: is not clipped away by the viewport's scissor.
    focusMargin = field.newField('focusMargin', 'SFFloat', 1, 5.0)
    #: Thickness of the focus ring itself, inside that margin.
    focusWidth = field.newField('focusWidth', 'SFFloat', 1, 2.0)
    #: Border drawn around a panel; 0 for none.
    borderWidth = field.newField('borderWidth', 'SFFloat', 1, 1.0)

    #: The fields above that are pixels and are therefore multiplied by the
    #: interface scale.  Colours are not measurements, and ``buttonPaddingX``
    #: is in characters, which already grow with the font.
    SCALED_FIELDS: Sequence[str] = (
        'panelPadding', 'rowSpacing', 'rowPadding', 'columnSpacing',
        'buttonPaddingY', 'fieldPadding', 'trackThickness', 'thumbWidth',
        'scrollbarWidth', 'switchWidth', 'switchHeight', 'switchInset',
        'focusMargin', 'focusWidth', 'borderWidth',
    )

    # -- artwork ----------------------------------------------------------
    #: One nine-slice per widget state.  Any left NULL falls back to the flat
    #: fill colour above, so a game can skin the buttons and leave the rest.
    panelImage = field.newField('panelImage', 'SFNode', 1, node.NULL)
    buttonImage = field.newField('buttonImage', 'SFNode', 1, node.NULL)
    buttonHoverImage = field.newField('buttonHoverImage', 'SFNode', 1, node.NULL)
    buttonDownImage = field.newField('buttonDownImage', 'SFNode', 1, node.NULL)
    buttonDisabledImage = field.newField('buttonDisabledImage', 'SFNode', 1, node.NULL)
    switchOffImage = field.newField('switchOffImage', 'SFNode', 1, node.NULL)
    switchOnImage = field.newField('switchOnImage', 'SFNode', 1, node.NULL)
    switchKnobImage = field.newField('switchKnobImage', 'SFNode', 1, node.NULL)
    trackImage = field.newField('trackImage', 'SFNode', 1, node.NULL)
    thumbImage = field.newField('thumbImage', 'SFNode', 1, node.NULL)
    fieldImage = field.newField('fieldImage', 'SFNode', 1, node.NULL)
    focusGlowImage = field.newField('focusGlowImage', 'SFNode', 1, node.NULL)

    # -- scale ------------------------------------------------------------
    def scaled(self, factor: float) -> 'Skin':
        """This skin with every pixel measurement multiplied by ``factor``.

        A copy rather than a mutation, because the original is authored data a
        game may be sharing between several panels, and because the factor
        changes whenever the window does.  Artwork is shared, not copied: a
        nine-slice stretches to whatever rectangle it is given, so the same
        image serves every scale and the renderer's texture cache is not
        duplicated per size.
        """
        if abs(float(factor) - 1.0) < 1e-6:
            return self
        clone = type(self)()
        for definition in protofunctions.getFields(self):
            name = definition.name
            if not name.startswith(' '):
                setattr(clone, name, getattr(self, name))
        for name in self.SCALED_FIELDS:
            setattr(clone, name, float(getattr(self, name)) * float(factor))
        return clone

    # -- lookups ----------------------------------------------------------
    def roleText(self, role: str) -> Any:
        """Text colour for a button's emphasis."""
        if role == PRIMARY:
            return self.primaryText
        if role == DANGER:
            return self.dangerText
        return self.secondaryText

    def buttonState(self, hovered: bool = False, down: bool = False,
                    enabled: bool = True) -> Tuple[Any, Any]:
        """Fill colour and artwork for one button state.

        The artwork may be an unset ``SFNode``, which the renderer reads as no
        artwork; nothing here has to normalise it.
        """
        if not enabled:
            return (self.buttonDisabledFill, self.buttonDisabledImage)
        if down:
            return (self.buttonDownFill, self.buttonDownImage)
        if hovered:
            return (self.buttonHoverFill, self.buttonHoverImage)
        return (self.buttonFill, self.buttonImage)

    def buttonPadding(self, metrics: FontMetrics) -> Tuple[int, int]:
        """A button's padding in pixels, from its character-based width."""
        return (int(self.buttonPaddingX * metrics.char_width),
                int(self.buttonPaddingY))


#: The colours and measurements a panel gets when it names no skin of its own.
#: **Treat it as read-only** -- :func:`default_skin` hands out copies for
#: exactly that reason.  Changing this one would change every dialog in the
#: process, including the ones already on screen.
DEFAULT_SKIN = Skin()


def default_skin() -> Skin:
    """A fresh copy of the default skin.

    A copy rather than the shared instance: a ``Skin`` is authored data with
    every field writable, and "tweak the default's ``panelFill``" is a natural
    thing for a game to try.  Handing out the one instance makes that a change
    to every panel in the process; handing out a copy makes it a change to the
    panel that asked.
    """
    clone = Skin()
    for definition in protofunctions.getFields(DEFAULT_SKIN):
        name = definition.name
        if not name.startswith(' '):
            setattr(clone, name, getattr(DEFAULT_SKIN, name))
    return clone


def skin_for(widget: Any) -> Skin:
    """The skin a widget paints with: its panel's, or the default.

    Looked up through the tree rather than stored per widget so a game can swap
    one panel's skin without touching the widgets in it -- and so every widget
    on a screen shares the one copy the panel scaled for the current window,
    rather than each scaling its own.
    """
    root = widget.root() if hasattr(widget, 'root') else widget
    if root is not widget:
        active = getattr(root, 'activeSkin', None)
        if active is not None:
            found = active()
            if isinstance(found, Skin):
                return found
    skin = getattr(root, 'skin', None)
    return skin if isinstance(skin, Skin) else default_skin()
