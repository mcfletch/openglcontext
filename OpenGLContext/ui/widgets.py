"""The widgets an overlay panel is built from.

Each is a scenegraph node, so a screen can be authored in a file and its parts
``DEF``/``USE``d like anything else, and each carries typed fields, which is
where validation, defaults and serialisation come from.

**The pointer is the interaction.**  Every widget has a rectangle, measured at
layout time; hover is a first-class state; and press and release are distinct,
so arming a button and dragging off it cancels.  The keyboard does two things:
it types into a field that wants text, and it runs accelerators.

A widget that edits a value **binds to a field of a node** -- ``target`` and
``fieldName`` -- and reads and writes through that field.  Nothing is copied:
the value the widget shows is the value in the node, so a screen generated from
a node needs no per-setting code and cannot drift from it.  Point the widget at
a draft (see :mod:`OpenGLContext.ui.session`) rather than at the live node and
Cancel becomes real.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

from vrml import field, node

from OpenGLContext.hud import GUINode
from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.skin import DANGER, PRIMARY, SECONDARY, skin_for

__all__ = [
    'Widget', 'BoundWidget', 'Label', 'Button', 'Toggle', 'Select', 'Slider',
    'TextField', 'KeyCapture', 'Spacer', 'Separator', 'key_label',
    'PRIMARY', 'SECONDARY', 'DANGER',
]

#: Keys a text field consumes rather than passing to the panel.
_EDIT_KEYS = ('<backspace>', '<delete>', '<left>', '<right>', '<home>', '<end>')

#: Keys whose own spelling is invisible or unreadable on a button.
_KEY_LABELS = {' ': '<space>', '\t': '<tab>', '\n': '<return>'}


def key_label(name: str) -> str:
    """A key name as it should be shown to a player.

    The event system spells the space bar ``' '``, and a button showing that
    looks unbound -- which is exactly the wrong thing to tell someone about the
    key their jump is on.
    """
    return _KEY_LABELS.get(name, name)


class Widget(GUINode, node.Node):
    """Base widget: a rectangle, a state, and the press/release protocol."""

    PROTO = 'UIWidget'
    #: Looked up with :meth:`Widget.find`, so a screen can name the parts a
    #: game wants to reach later without holding a reference to each.
    name = field.newField('name', 'SFString', 1, '')
    #: A disabled widget is drawn dimmed, is not hit-tested and takes no focus.
    enabled = field.newField('enabled', 'SFBool', 1, True)
    #: An invisible widget takes no space and receives nothing.
    visible = field.newField('visible', 'SFBool', 1, True)

    #: Whether the pointer can pick this out of the tree.
    interactive: bool = False
    #: Whether Tab stops here.
    focusable: bool = False
    #: Whether it wants typed characters, which is also what earns it a focus
    #: ring on a click rather than only on Tab.
    acceptsText: bool = False

    #: Transient state -- what the pointer and the keyboard are doing right
    #: now.  Not fields: none of it is worth saving or serialising.
    hovered: bool = False
    focused: bool = False
    armed: bool = False
    #: Called with this widget when it is activated / when its value changes.
    on_activate: Optional[Callable[['Widget'], None]] = None
    on_change: Optional[Callable[['Widget'], None]] = None

    # -- the tree ---------------------------------------------------------
    def widget_at(self, x: float, y: float) -> Optional['Widget']:
        """The topmost interactive widget under a point.

        Front to back: children are drawn after their parent and so are in
        front of it, and later children are in front of earlier ones.
        """
        if not self.visible:
            return None
        for child in reversed(list(self.layoutChildren())):
            found = child.widget_at(x, y)
            if found is not None:
                return found
        if self.interactive and self.enabled and self.rect.contains(x, y):
            return self
        return None

    def find(self, name: str) -> Optional['Widget']:
        """The first descendant (or this) with that ``name``."""
        for widget in self.walk():
            if getattr(widget, 'name', None) == name:
                return widget
        return None

    def activeSkin(self) -> Any:
        """The skin this widget paints with -- its panel's, or the default."""
        return skin_for(self)

    # -- pointer ----------------------------------------------------------
    def press(self, x: float, y: float) -> bool:
        """Take a press.  True arms the widget, so the release comes here too."""
        if not self.enabled:
            return False
        self.armed = True
        return True

    def drag(self, x: float, y: float) -> None:
        """The pointer moved while armed.

        The default disarms once the pointer leaves and re-arms when it comes
        back, which is what makes dragging off a button cancel it.
        """
        self.armed = self.rect.contains(x, y)

    def release(self, x: float, y: float) -> bool:
        """Finish a press.  True if the widget acted on it."""
        armed, self.armed = self.armed, False
        if armed and self.enabled and self.rect.contains(x, y):
            self.activate()
            return True
        return False

    def cancel(self) -> None:
        """Abandon a press without acting -- a dialog opened over it, say."""
        self.armed = False

    def wheel(self, delta: int, x: float, y: float) -> bool:
        """A wheel notch over the widget.  True if it used it."""
        return False

    # -- keyboard ---------------------------------------------------------
    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        """A key while this widget has focus.  True if it consumed it."""
        return False

    def character(self, text: str) -> bool:
        """A typed character while this widget has focus."""
        return False

    def accelerate(self, name: str) -> bool:
        """Run this widget's accelerator if ``name`` is it."""
        return False

    def focus_gained(self) -> None:
        self.focused = True

    def focus_lost(self) -> None:
        self.focused = False

    # -- drawing ----------------------------------------------------------
    def paintTree(self, renderer: Any) -> None:
        """Draw this widget and everything inside it, back to front."""
        if not self.visible:
            return
        self.paint(renderer)
        self.paintChildren(renderer)

    def paintChildren(self, renderer: Any) -> None:
        """Draw everything inside this widget.  A viewport clips here."""
        for child in self.layoutChildren():
            child.paintTree(renderer)

    def paint(self, renderer: Any) -> None:
        """Draw this widget's own body.  Containers draw nothing."""

    def paintFocus(self, renderer: Any) -> None:
        """Draw the focus glow, when this is where the keyboard is.

        Outside the widget's rectangle and additive, so it is never mistaken
        for hover and never moves the text by a pixel when focus arrives.
        """
        panel = self.root()
        if not (self.focused and getattr(panel, 'focusVisible', False)):
            return
        skin = renderer.skin
        renderer.glow(self.rect.expand(int(skin.focusMargin)), skin.focusGlow)

    def textColour(self, renderer: Any) -> Any:
        """The colour this widget's text is drawn in."""
        return (renderer.skin.labelText if self.enabled
                else renderer.skin.disabledText)

    # -- acting -----------------------------------------------------------
    def activate(self) -> None:
        """Do whatever this widget does when it is clicked or Entered."""
        if self.on_activate is not None:
            self.on_activate(self)
        dispatch = getattr(self.root(), 'dispatch', None)
        if dispatch is not None:
            dispatch(self)

    def changed(self) -> None:
        """Announce that the value this widget edits has moved."""
        if self.on_change is not None:
            self.on_change(self)
        notify = getattr(self.root(), 'valueChanged', None)
        if notify is not None:
            notify(self)


class BoundWidget(Widget):
    """A widget that edits one field of one node.

    Bound, the field *is* the value: :meth:`read` and :meth:`write` go straight
    through it, so there is no second copy to fall out of step and anything
    already watching that field is notified normally.  Unbound, the widget's own
    ``value`` field holds it, which is what makes a widget useful on its own.
    """

    PROTO = 'UIBoundWidget'
    target = field.newField('target', 'SFNode', 1, node.NULL)
    fieldName = field.newField('fieldName', 'SFString', 1, '')
    #: What a click does, when a game would rather name it than pass a
    #: callable: dispatched through the panel's command table.
    action = field.newField('action', 'SFString', 1, '')

    @property
    def bound(self) -> bool:
        """Whether this widget edits a field of a node rather than its own value."""
        return bool(self.target) and bool(self.fieldName)

    def read(self) -> Any:
        """The current value: the bound field's, or this widget's own."""
        if self.bound:
            return getattr(self.target, self.fieldName)
        return self.value

    def write(self, value: Any) -> bool:
        """Store a value; True if it actually changed."""
        if value == self.read():
            return False
        if self.bound:
            setattr(self.target, self.fieldName, value)
        else:
            self.value = value
        self.changed()
        return True


class Label(Widget):
    """Text, laid out and optionally wrapped, that nothing can click."""

    PROTO = 'Label'
    text = field.newField('text', 'SFString', 1, '')
    #: Wrap to the width available rather than running off the panel.
    wrap = field.newField('wrap', 'SFBool', 1, False)
    #: ``left``, ``center`` or ``right``.
    align = field.newField('align', 'SFString', 1, 'left')
    #: Overrides the skin's label colour when set (alpha 0 means "use the skin").
    color = field.newField('color', 'SFVec4f', 1, (0, 0, 0, 0))

    def content_size(self, metrics: Any,
                     available: Optional[int] = None) -> Tuple[int, int]:
        if self.wrap:
            width = int(self.width) or available or self.rect.width
            if width:
                return metrics.lines_size(metrics.wrap(self.text, width))
        return metrics.text_size(self.text)

    def display_lines(self, metrics: Any) -> List[str]:
        """The lines to draw, wrapped to the rectangle this ended up with."""
        if not self.text:
            return []
        if self.wrap:
            return metrics.wrap(self.text, self.rect.width or int(self.width))
        return self.text.split('\n')

    def textColour(self, renderer: Any) -> Any:
        if float(self.color[3]):
            return self.color
        return super(Label, self).textColour(renderer)

    def paint(self, renderer: Any) -> None:
        renderer.lines(self.rect, self.display_lines(renderer.metrics),
                       self.textColour(renderer), align=self.align)


class Separator(Widget):
    """A hairline between groups of controls."""

    PROTO = 'Separator'
    height = field.newField('height', 'SFFloat', 1, 1.0)
    color = field.newField('color', 'SFVec4f', 1, (1, 1, 1, 0.18))

    def paint(self, renderer: Any) -> None:
        renderer.rect(self.rect, self.color)


class Spacer(Widget):
    """Blank, flexible space -- what pushes a row's buttons to one end."""

    PROTO = 'Spacer'
    flex = field.newField('flex', 'SFFloat', 1, 1.0)


class Button(BoundWidget):
    """A clickable action, with an emphasis and an optional accelerator."""

    PROTO = 'Button'
    text = field.newField('text', 'SFString', 1, '')
    #: ``primary``, ``secondary`` or ``danger``.  ``primary`` is also the
    #: panel's Enter default; ``danger`` marks the actions a settings screen
    #: must not let someone hit by accident.
    role = field.newField('role', 'SFString', 1, SECONDARY)
    #: A key that activates this button from anywhere in the panel.
    accelerator = field.newField('accelerator', 'SFString', 1, '')
    value = field.newField('value', 'SFString', 1, '')

    interactive = True
    focusable = True

    def content_size(self, metrics: Any,
                     available: Optional[int] = None) -> Tuple[int, int]:
        pad_x, pad_y = self.activeSkin().buttonPadding(metrics)
        return (metrics.text_width(self.text) + pad_x * 2,
                metrics.char_height + pad_y * 2)

    def accelerate(self, name: str) -> bool:
        if self.enabled and self.accelerator and name == self.accelerator:
            self.activate()
            return True
        return False

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name in ('<return>', ' ') and self.enabled:
            self.activate()
            return True
        return False

    def paint(self, renderer: Any) -> None:
        self.paintFocus(renderer)
        skin = renderer.skin
        fill, image = skin.buttonState(hovered=self.hovered, down=self.armed,
                                       enabled=bool(self.enabled))
        renderer.frame(self.rect, fill, image)
        colour = (skin.roleText(self.role) if self.enabled
                  else skin.disabledText)
        renderer.textIn(self.rect, self.text, colour, align='center')


class Toggle(BoundWidget):
    """A checkbox: a label, a box, and a boolean."""

    PROTO = 'Toggle'
    text = field.newField('text', 'SFString', 1, '')
    value = field.newField('value', 'SFBool', 1, False)

    interactive = True
    focusable = True

    def content_size(self, metrics: Any,
                     available: Optional[int] = None) -> Tuple[int, int]:
        box = metrics.char_height
        text = metrics.text_width(self.text)
        gap = metrics.char_width if self.text else 0
        return (box + gap + text, box + int(self.activeSkin().buttonPaddingY))

    def read(self) -> bool:
        """The value as a real boolean.

        ``SFBool`` stores 1/0, and a widget handing that back would leak the
        storage into every caller's ``is True``.
        """
        return bool(super(Toggle, self).read())

    def box_rect(self) -> Rect:
        """The check box itself, at the left of the widget."""
        size = min(self.rect.height, self.rect.width)
        return Rect(self.rect.x, self.rect.y + (self.rect.height - size) // 2,
                    size, size)

    def activate(self) -> None:
        self.write(not self.read())
        super(Toggle, self).activate()

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name in ('<return>', ' '):
            self.activate()
            return True
        return False

    def paint(self, renderer: Any) -> None:
        self.paintFocus(renderer)
        skin = renderer.skin
        box = self.box_rect()
        on = self.read()
        image = skin._image(skin.checkFullImage if on else skin.checkEmptyImage)
        renderer.frame(box, skin.checkFill, image)
        renderer.border(box, skin.panelBorder)
        if on and image is None:
            renderer.rect(box.inset(max(2, box.width // 4)), skin.checkMark)
        if self.hovered:
            renderer.border(box, skin.buttonHoverFill, 2)
        label = Rect(box.right + renderer.metrics.char_width, self.rect.y,
                     max(0, self.rect.right - box.right), self.rect.height)
        renderer.textIn(label, self.text, self.textColour(renderer))


class Select(BoundWidget):
    """One of a fixed set of values, cycled with two arrows or the keyboard.

    A cycle rather than a drop-down list: a list is a second, floating,
    scrollable surface with its own focus and hit-testing, and the settings this
    is for -- a profile, a quality level, a shadow filter -- have three or four
    values each.
    """

    PROTO = 'Select'
    text = field.newField('text', 'SFString', 1, '')
    #: The values, as they are stored in the bound field.
    options = field.newField('options', 'MFString', 1, list)
    #: What to show for each option; falls back to the option itself.
    optionLabels = field.newField('optionLabels', 'MFString', 1, list)
    value = field.newField('value', 'SFString', 1, '')

    interactive = True
    focusable = True

    #: Which arrow the pointer went down on, so the release acts on the same one.
    _pressed_arrow: int = 0

    @property
    def index(self) -> int:
        """Where the current value sits in ``options``.

        A value that is not one of them reads as the first: a settings file
        naming a mode this build does not have should show something, and the
        first option is the one the screen was authored to default to.
        """
        try:
            return list(self.options).index(self.read())
        except ValueError:
            return 0

    def display_value(self) -> str:
        """What to show for the current value: its label, or the value itself."""
        options = list(self.options)
        if not options:
            return ''
        index = self.index
        labels = list(self.optionLabels)
        if index < len(labels):
            return labels[index]
        return options[index]

    def content_size(self, metrics: Any,
                     available: Optional[int] = None) -> Tuple[int, int]:
        widest = max([len(self.display_label(index))
                      for index in range(len(self.options))], default=0)
        arrows = metrics.char_width * 3 * 2
        pad = int(self.activeSkin().fieldPadding) * 2
        return (arrows + widest * metrics.char_width + pad,
                metrics.char_height + int(self.activeSkin().buttonPaddingY))

    def display_label(self, index: int) -> str:
        """What to show for one option."""
        labels = list(self.optionLabels)
        if index < len(labels):
            return labels[index]
        options = list(self.options)
        return options[index] if index < len(options) else ''

    def arrow_rects(self) -> Tuple[Rect, Rect]:
        """The left and right arrows, at the two ends of the widget."""
        width = min(self.rect.width // 2, max(1, self.rect.height))
        left = Rect(self.rect.x, self.rect.y, width, self.rect.height)
        right = Rect(self.rect.right - width, self.rect.y, width,
                     self.rect.height)
        return (left, right)

    def value_rect(self) -> Rect:
        """Where the current value is drawn, between the arrows."""
        left, right = self.arrow_rects()
        return Rect(left.right, self.rect.y,
                    max(0, right.x - left.right), self.rect.height)

    def step(self, direction: int) -> bool:
        """Move to the next or previous option, wrapping at the ends."""
        options = list(self.options)
        if not options:
            return False
        return self.write(options[(self.index + direction) % len(options)])

    def press(self, x: float, y: float) -> bool:
        if not super(Select, self).press(x, y):
            return False
        left, right = self.arrow_rects()
        self._pressed_arrow = -1 if left.contains(x, y) else (
            1 if right.contains(x, y) else 0)
        return True

    def release(self, x: float, y: float) -> bool:
        armed, self.armed = self.armed, False
        if not (armed and self.enabled and self.rect.contains(x, y)):
            return False
        # Clicking the value itself, between the arrows, steps forward: it is
        # what the pointer expects of a cycling control, and the arrows are
        # small targets.
        self.step(self._pressed_arrow or 1)
        super(Select, self).activate()
        return True

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name in ('<right>', '<up>'):
            self.step(1)
            return True
        if name in ('<left>', '<down>'):
            self.step(-1)
            return True
        return False

    def wheel(self, delta: int, x: float, y: float) -> bool:
        if delta:
            self.step(1 if delta > 0 else -1)
            return True
        return False

    def paint(self, renderer: Any) -> None:
        self.paintFocus(renderer)
        skin = renderer.skin
        renderer.frame(self.rect, skin.fieldFill, skin._image(skin.fieldImage))
        left, right = self.arrow_rects()
        arrow = skin.secondaryText if self.enabled else skin.disabledText
        lit = skin.buttonHoverFill if self.hovered else None
        for rect, glyph in ((left, '<'), (right, '>')):
            if lit is not None:
                renderer.rect(rect, lit)
            renderer.textIn(rect, glyph, arrow, align='center')
        renderer.textIn(self.value_rect(), self.display_value(),
                        self.textColour(renderer), align='center')


class Slider(BoundWidget):
    """A number, dragged along a track."""

    PROTO = 'Slider'
    text = field.newField('text', 'SFString', 1, '')
    value = field.newField('value', 'SFFloat', 1, 0.0)
    minimum = field.newField('minimum', 'SFFloat', 1, 0.0)
    maximum = field.newField('maximum', 'SFFloat', 1, 1.0)
    #: How far one arrow key moves it, and what a drag rounds to.  0 is
    #: continuous.
    step = field.newField('step', 'SFFloat', 1, 0.0)
    #: Store whole numbers, for a count of lights or of cascades.
    integer = field.newField('integer', 'SFBool', 1, False)
    #: Printed after the value, e.g. ``"x"`` or ``" m/s"``.
    suffix = field.newField('suffix', 'SFString', 1, '')

    interactive = True
    focusable = True

    def content_size(self, metrics: Any,
                     available: Optional[int] = None) -> Tuple[int, int]:
        return (metrics.char_width * 14,
                max(int(self.activeSkin().thumbWidth),
                    metrics.char_height + int(self.activeSkin().buttonPaddingY)))

    # -- geometry ---------------------------------------------------------
    def value_width(self, metrics: Any) -> int:
        """Room kept at the right for the printed value."""
        return metrics.text_width(self.display_value(metrics)) + metrics.char_width

    def track_rect(self, metrics: Any = None) -> Rect:
        """The groove the thumb runs along."""
        reserved = self.value_width(metrics) if metrics is not None else 0
        thickness = int(self.activeSkin().trackThickness)
        half = int(self.activeSkin().thumbWidth) // 2
        return Rect(self.rect.x + half,
                    self.rect.y + (self.rect.height - thickness) // 2,
                    max(1, self.rect.width - reserved - half * 2), thickness)

    def thumb_rect(self, metrics: Any = None) -> Rect:
        """The grip, centred on the value's position along the track."""
        track = self.track_rect(metrics)
        width = int(self.activeSkin().thumbWidth)
        centre = track.x + int(track.width * self.fraction())
        return Rect(centre - width // 2, self.rect.y, width, self.rect.height)

    def fraction(self) -> float:
        """Where the value sits between the ends, 0..1.

        A slider whose ends are equal has nowhere to sit, so it reports the
        start rather than dividing by zero.
        """
        span = float(self.maximum) - float(self.minimum)
        if span <= 0:
            return 0.0
        return min(1.0, max(0.0, (float(self.read()) - float(self.minimum)) / span))

    def display_value(self, metrics: Any = None) -> str:
        """The value as it is printed beside the track."""
        value = self.read()
        if self.integer or float(value) == int(value):
            text = '%d' % (int(value),)
        else:
            text = '%.2f' % (float(value),)
        return text + self.suffix

    # -- changing ---------------------------------------------------------
    def coerce(self, value: float) -> Any:
        """Clamp to the ends, round to the step, and to a whole number if asked."""
        value = min(float(self.maximum), max(float(self.minimum), float(value)))
        if self.step:
            steps = round((value - float(self.minimum)) / float(self.step))
            value = float(self.minimum) + steps * float(self.step)
            value = min(float(self.maximum), max(float(self.minimum), value))
        if self.integer:
            return int(round(value))
        return value

    def set_fraction(self, fraction: float) -> bool:
        """Set the value from a 0..1 position along the track."""
        span = float(self.maximum) - float(self.minimum)
        return self.write(self.coerce(float(self.minimum) + span * fraction))

    def _fraction_at(self, x: float, metrics: Any = None) -> float:
        track = self.track_rect(metrics)
        if track.width <= 0:
            return 0.0
        return min(1.0, max(0.0, (x - track.x) / float(track.width)))

    def press(self, x: float, y: float) -> bool:
        if not super(Slider, self).press(x, y):
            return False
        # A click anywhere on the track jumps there; the drag then continues
        # from that point, which is what a pointer UI does.
        self.set_fraction(self._fraction_at(x))
        return True

    def drag(self, x: float, y: float) -> None:
        if self.armed:
            self.set_fraction(self._fraction_at(x))

    def release(self, x: float, y: float) -> bool:
        was, self.armed = self.armed, False
        return was

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        amount = float(self.step) or (float(self.maximum) - float(self.minimum)) / 20.0
        if name in ('<right>', '<up>'):
            return self.write(self.coerce(float(self.read()) + amount)) or True
        if name in ('<left>', '<down>'):
            return self.write(self.coerce(float(self.read()) - amount)) or True
        if name == '<home>':
            return self.write(self.coerce(float(self.minimum))) or True
        if name == '<end>':
            return self.write(self.coerce(float(self.maximum))) or True
        return False

    def wheel(self, delta: int, x: float, y: float) -> bool:
        if not delta:
            return False
        amount = float(self.step) or (float(self.maximum) - float(self.minimum)) / 20.0
        self.write(self.coerce(float(self.read()) + amount * (1 if delta > 0 else -1)))
        return True

    def paint(self, renderer: Any) -> None:
        self.paintFocus(renderer)
        skin = renderer.skin
        metrics = renderer.metrics
        track = self.track_rect(metrics)
        renderer.frame(track, skin.trackFill, skin._image(skin.trackImage))
        filled = Rect(track.x, track.y, int(track.width * self.fraction()),
                      track.height)
        renderer.rect(filled, skin.thumbFill)
        thumb = self.thumb_rect(metrics)
        fill = skin.buttonHoverFill if (self.hovered or self.armed) else skin.thumbFill
        renderer.frame(thumb, fill, skin._image(skin.thumbImage))
        value = Rect(track.right, self.rect.y,
                     max(0, self.rect.right - track.right), self.rect.height)
        renderer.textIn(value, self.display_value(metrics),
                        self.textColour(renderer), align='right')


class TextField(BoundWidget):
    """One line of editable text."""

    PROTO = 'TextField'
    value = field.newField('value', 'SFString', 1, '')
    #: 0 for no limit.
    maximumLength = field.newField('maximumLength', 'SFInt32', 1, 0)
    #: Shown greyed when the value is empty.
    placeholder = field.newField('placeholder', 'SFString', 1, '')

    interactive = True
    focusable = True
    acceptsText = True

    #: Where the next character goes, in characters from the start.
    caret: int = 0

    def content_size(self, metrics: Any,
                     available: Optional[int] = None) -> Tuple[int, int]:
        columns = int(self.maximumLength) or 20
        return (columns * metrics.char_width + int(self.activeSkin().fieldPadding) * 2,
                metrics.char_height + int(self.activeSkin().buttonPaddingY))

    def focus_gained(self) -> None:
        """Take the keyboard, with the caret at the end of what is there."""
        super(TextField, self).focus_gained()
        self.caret = len(self.read())

    def press(self, x: float, y: float) -> bool:
        if not super(TextField, self).press(x, y):
            return False
        self._pending_caret = x
        return True

    def caret_from(self, x: float, metrics: Any) -> int:
        """Which character position a click at ``x`` lands on."""
        pad = int(self.activeSkin().fieldPadding)
        offset = max(0, x - (self.rect.x + pad))
        return min(len(self.read()), int(round(offset / max(1, metrics.char_width))))

    def character(self, text: str) -> bool:
        current = self.read()
        limit = int(self.maximumLength)
        if limit and len(current) >= limit:
            return True
        self.caret = min(self.caret, len(current))
        self.write(current[:self.caret] + text + current[self.caret:])
        self.caret += len(text)
        return True

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name not in _EDIT_KEYS:
            return False
        current = self.read()
        self.caret = min(self.caret, len(current))
        if name == '<backspace>':
            if self.caret:
                self.write(current[:self.caret - 1] + current[self.caret:])
                self.caret -= 1
        elif name == '<delete>':
            if self.caret < len(current):
                self.write(current[:self.caret] + current[self.caret + 1:])
        elif name == '<left>':
            self.caret = max(0, self.caret - 1)
        elif name == '<right>':
            self.caret = min(len(current), self.caret + 1)
        elif name == '<home>':
            self.caret = 0
        elif name == '<end>':
            self.caret = len(current)
        return True

    def paint(self, renderer: Any) -> None:
        self.paintFocus(renderer)
        skin = renderer.skin
        metrics = renderer.metrics
        renderer.frame(self.rect, skin.fieldFill, skin._image(skin.fieldImage))
        pad = int(skin.fieldPadding)
        inner = self.rect.inset(pad, 0)
        text = self.read()
        if text:
            renderer.textIn(inner, metrics.truncate(text, inner.width),
                            skin.fieldText if self.enabled else skin.disabledText)
        else:
            renderer.textIn(inner, self.placeholder, skin.disabledText)
        if self.focused:
            caret = min(self.caret, len(text))
            x = inner.x + caret * metrics.char_width
            renderer.rect(Rect(x, inner.y + (inner.height - metrics.char_height) // 2,
                               max(1, metrics.char_width // 8), metrics.char_height),
                          skin.caret)


class KeyCapture(Widget):
    """Takes the next key the user presses, whatever it is.

    While one of these has focus its panel is ``capturing``: no accelerator, no
    Tab traversal and no Enter default run, so Tab, Enter and the mouse buttons
    are all bindable.  **Escape is reserved** as the way out and is therefore
    the one key that cannot be bound -- the alternatives are a timeout, or
    requiring a mouse click on Cancel, which fails for exactly the person
    rebinding mouse buttons.
    """

    PROTO = 'KeyCapture'
    #: The keys currently bound, shown until something is captured.
    keys = field.newField('keys', 'MFString', 1, list)
    #: Shown when nothing is bound.
    text = field.newField('text', 'SFString', 1, '')

    interactive = True
    focusable = True
    acceptsText = True

    #: What was captured, or None while still waiting.
    captured: Optional[str] = None

    def content_size(self, metrics: Any,
                     available: Optional[int] = None) -> Tuple[int, int]:
        return (metrics.text_width(self.display_value()) +
                int(self.activeSkin().fieldPadding) * 2 + metrics.char_width * 4,
                metrics.char_height + int(self.activeSkin().buttonPaddingY))

    def display_value(self) -> str:
        """What the field shows: the captured key, or the current binding."""
        if self.captured is not None:
            return key_label(self.captured)
        return (', '.join(key_label(key) for key in self.keys)
                or self.text or '(unbound)')

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name == '<escape>':
            return False
        self.captured = name
        self.changed()
        return True

    def button(self, index: int) -> bool:
        """Bind a mouse button, spelled as the event system spells one."""
        self.captured = '<mouse%d>' % (index,)
        self.changed()
        return True

    def result(self) -> List[str]:
        """The keys this dialog would store: what was captured, or the old set."""
        if self.captured is None:
            return list(self.keys)
        return [self.captured]

    def paint(self, renderer: Any) -> None:
        self.paintFocus(renderer)
        skin = renderer.skin
        renderer.frame(self.rect, skin.fieldFill, skin._image(skin.fieldImage))
        colour = (skin.checkMark if self.captured is not None
                  else self.textColour(renderer))
        renderer.textIn(self.rect, self.display_value(), colour, align='center')
