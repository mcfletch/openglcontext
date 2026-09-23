"""What a control shows the pointer: a wash while it rests there, a ripple when it is used.

Headless. A recording renderer stands in for the GL one, and time is passed in
rather than read, so each moment of a ripple can be looked at.
"""
import pytest

from OpenGLContext.events import systemtime
from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.layout import Column
from OpenGLContext.ui.metrics import REFERENCE_METRICS
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import (
    RIPPLE_SECONDS, Button, Label, Slider, TextField, Toggle,
)

VIEWPORT = (800, 600)


class _Recorder:
    """Records each drawing call a widget makes, by name, with its arguments."""

    def __init__(self, skin, now=None):
        self.skin = skin
        self.metrics = REFERENCE_METRICS
        self.now = now
        self.calls = []

    def __getattr__(self, name):
        def record(*arguments, **named):
            self.calls.append((name, arguments))
            return None
        return record

    def named(self, name):
        return [arguments for called, arguments in self.calls if called == name]


def _panel(*children):
    panel = Panel(children=[Column(children=list(children))])
    panel.layout(VIEWPORT, REFERENCE_METRICS)
    return panel


def _painted(widget, now=None):
    renderer = _Recorder(widget.activeSkin(), now=now)
    widget.paintTree(renderer)
    return renderer


class TestTheHoverWash:
    def test_a_control_under_the_pointer_is_washed(self):
        toggle = Toggle(text='Shadows')
        panel = _panel(toggle)
        panel.pointer_moved(*toggle.rect.centre)
        washes = [args for args in _painted(toggle).named('rect')
                  if args[1] == tuple(toggle.activeSkin().hoverWash)]
        assert washes and washes[0][0] == toggle.rect

    def test_a_control_the_pointer_is_not_on_is_not(self):
        toggle = Toggle(text='Shadows')
        _panel(toggle)
        skin = toggle.activeSkin()
        assert not [args for args in _painted(toggle).named('rect')
                    if args[1] == tuple(skin.hoverWash)]

    def test_a_disabled_control_is_not(self):
        toggle = Toggle(text='Shadows', enabled=False)
        _panel(toggle)
        toggle.hovered = True
        skin = toggle.activeSkin()
        assert not [args for args in _painted(toggle).named('rect')
                    if args[1] == tuple(skin.hoverWash)]

    def test_text_that_nothing_can_click_is_not(self):
        label = Label(text='Volume')
        _panel(label)
        label.hovered = True
        assert not label.showsHover()

    def test_a_button_lights_itself_instead(self):
        button = Button(text='Apply')
        _panel(button)
        button.hovered = True
        assert not button.showsHover()

    def test_the_panel_under_it_all_is_not(self):
        panel = _panel(Button(text='Apply'))
        panel.hovered = True
        assert not panel.showsHover()


class TestTheRipple:
    def _pressed(self, widget, at=None):
        panel = _panel(widget)
        start = systemtime.systemTime()
        x, y = at if at is not None else widget.rect.centre
        panel.pointer_pressed(x, y)
        return panel, start

    def test_a_press_starts_one_where_the_pointer_went_down(self):
        button = Button(text='Apply')
        _panel_, start = self._pressed(button, at=None)
        corner = (button.rect.x + 3, button.rect.y + 2)
        button.ripple(*corner, now=start)
        x, y, _radius, _strength = button.rippleAt(start + 0.05)
        assert (x, y) == corner

    def test_it_grows_and_fades(self):
        button = Button(text='Apply')
        _panel(button)
        button.ripple(now=10.0)
        early = button.rippleAt(10.0 + RIPPLE_SECONDS * 0.2)
        late = button.rippleAt(10.0 + RIPPLE_SECONDS * 0.8)
        assert late[2] > early[2]
        assert late[3] < early[3]

    def test_by_the_end_it_reaches_every_corner(self):
        button = Button(text='Apply')
        _panel(button)
        corner = (button.rect.x, button.rect.y)
        button.ripple(*corner, now=0.0)
        radius = button.rippleAt(RIPPLE_SECONDS * 0.999)[2]
        assert radius >= ((button.rect.width ** 2 + button.rect.height ** 2) ** 0.5) * 0.99

    def test_it_is_over_once_its_time_is_up(self):
        button = Button(text='Apply')
        _panel(button)
        button.ripple(now=0.0)
        assert button.rippleAt(RIPPLE_SECONDS + 0.01) is None

    def test_a_click_in_a_panel_starts_one(self):
        button = Button(text='Apply')
        _panel_, start = self._pressed(button)
        assert button.rippleAt(start + 0.05) is not None

    def test_it_is_drawn_inside_the_control(self):
        button = Button(text='Apply')
        _panel(button)
        button.ripple(now=0.0)
        renderer = _painted(button, now=RIPPLE_SECONDS / 2.0)
        names = [name for name, _args in renderer.calls]
        start = names.index('pushScissor')
        assert names[start + 1] == 'disc' and names[start + 2] == 'popScissor'
        assert renderer.named('pushScissor')[0][0] == button.rect

    def test_the_keyboard_starts_one_from_the_middle(self):
        button = Button(text='Apply')
        panel = _panel(button)
        panel.focus(button)
        start = systemtime.systemTime()
        panel.key('<return>', (0, 0, 0))
        x, y, _radius, _strength = button.rippleAt(start + 0.05)
        assert (x, y) == pytest.approx(button.rect.centre)

    def test_one_already_running_is_not_restarted_by_the_click_it_came_from(self):
        button = Button(text='Apply')
        panel = _panel(button)
        corner = (button.rect.x + 2, button.rect.y + 2)
        panel.pointer_pressed(*corner)
        panel.pointer_released(*corner)
        x, y, _radius, _strength = button.rippleAt(systemtime.systemTime())
        assert (x, y) == corner

    @pytest.mark.parametrize('make', [
        lambda: Slider(minimum=0.0, maximum=1.0),
        lambda: TextField(),
    ])
    def test_what_is_dragged_or_typed_in_does_not(self, make):
        widget = make()
        _panel_, start = self._pressed(widget)
        assert widget.rippleAt(start + 0.05) is None

    def test_a_disabled_control_does_not(self):
        button = Button(text='Apply', enabled=False)
        _panel(button)
        assert not button.ripple(now=0.0)


class TestKeepingTheFramesComing:
    def test_the_panel_is_animating_while_a_ripple_runs(self):
        button = Button(text='Apply')
        panel = _panel(button)
        button.ripple(now=5.0)
        assert panel.animating(5.0 + RIPPLE_SECONDS / 2.0)
        assert not panel.animating(5.0 + RIPPLE_SECONDS * 2.0)

    def test_a_still_panel_is_not(self):
        assert not _panel(Button(text='Apply')).animating(0.0)


def test_the_ripple_is_placed_by_rect_arithmetic():
    """A disc's rectangle is the ripple's circle: centre and radius."""
    button = Button(text='Apply')
    _panel(button)
    button.ripple(button.rect.x + 10, button.rect.y + 5, now=0.0)
    renderer = _painted(button, now=RIPPLE_SECONDS / 2.0)
    disc = renderer.named('disc')[0][0]
    x, y, radius, _strength = button.rippleAt(RIPPLE_SECONDS / 2.0)
    assert isinstance(disc, Rect)
    assert disc.centre == pytest.approx((x, y), abs=1.0)
    assert disc.width == pytest.approx(radius * 2, abs=2.0)
