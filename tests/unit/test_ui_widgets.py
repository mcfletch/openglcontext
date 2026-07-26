"""Widgets: measurement, the press/release protocol, and model binding.

Every one of these runs with no GL context: layout and hit-testing are
arithmetic over measured text, and drawing is somewhere else entirely.
"""

import pytest
from vrml import field, node

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.widgets import (
    Button, KeyCapture, Label, Select, Slider, Spacer, TextField, Toggle,
    PRIMARY, DANGER,
)


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


class Settings(node.Node):
    """A stand-in for a real settings node -- ordinary typed fields."""

    PROTO = 'UITestSettings'
    shadows = field.newField('shadows', 'SFBool', 1, True)
    lights = field.newField('lights', 'SFInt32', 1, 4)
    exposure = field.newField('exposure', 'SFFloat', 1, 1.0)
    title = field.newField('title', 'SFString', 1, 'hello')
    quality = field.newField('quality', 'SFString', 1, 'high')


class TestLabel:
    def test_a_label_measures_its_text(self, metrics):
        assert Label(text='abcd').natural_size(metrics) == (32, 18)

    def test_an_empty_label_takes_no_room(self, metrics):
        assert Label().natural_size(metrics) == (0, 0)

    def test_a_label_is_not_clickable(self):
        label = Label(text='x')
        label.arrange(Rect(0, 0, 100, 20), FontMetrics(8, 16))
        assert label.widget_at(5, 5) is None

    def test_a_wrapping_label_grows_taller_when_squeezed(self, metrics):
        label = Label(text='one two three four', wrap=True)
        label.arrange(Rect(0, 0, 5 * 8, 200), metrics)
        assert len(label.display_lines(metrics)) > 1

    def test_a_wrapping_label_asks_for_the_height_its_lines_need(self, metrics):
        label = Label(text='one two three four', wrap=True, width=5 * 8)
        assert label.natural_size(metrics)[1] == 4 * metrics.line_height

    def test_margins_are_added_to_the_natural_size(self, metrics):
        label = Label(text='ab', left=4, right=6, top=1, bottom=2)
        assert label.natural_size(metrics) == (16 + 10, 18 + 3)

    def test_margins_are_taken_out_of_the_arranged_rect(self, metrics):
        label = Label(text='ab', left=4, right=6, top=1, bottom=2)
        label.arrange(Rect(0, 0, 100, 50), metrics)
        assert label.rect == Rect(4, 2, 90, 47)


class TestButtonPressAndRelease:
    @pytest.fixture
    def button(self, metrics):
        fired = []
        button = Button(text='Yes')
        button.on_activate = lambda widget: fired.append(widget)
        button.fired = fired
        button.arrange(Rect(10, 10, 60, 30), metrics)
        return button

    def test_a_button_is_wider_than_its_label(self, metrics):
        assert Button(text='Yes').natural_size(metrics)[0] > metrics.text_width('Yes')

    def test_clicking_it_fires_once(self, button):
        assert button.press(20, 20)
        assert button.release(20, 20)
        assert len(button.fired) == 1

    def test_a_press_alone_does_not_fire(self, button):
        button.press(20, 20)
        assert button.fired == []

    def test_dragging_off_before_release_cancels(self, button):
        button.press(20, 20)
        button.drag(500, 500)
        assert not button.armed
        assert not button.release(500, 500)
        assert button.fired == []

    def test_dragging_back_on_re_arms(self, button):
        button.press(20, 20)
        button.drag(500, 500)
        button.drag(20, 20)
        assert button.armed
        assert button.release(20, 20)

    def test_a_release_with_no_press_does_nothing(self, button):
        assert not button.release(20, 20)
        assert button.fired == []

    def test_a_disabled_button_does_not_arm(self, button):
        button.enabled = False
        assert not button.press(20, 20)
        assert not button.release(20, 20)
        assert button.fired == []

    def test_a_disabled_button_is_not_hit_tested(self, button):
        button.enabled = False
        assert button.widget_at(20, 20) is None

    def test_it_reports_its_role(self):
        assert Button(text='Yes', role=PRIMARY).role == PRIMARY
        assert Button(text='No').role == 'secondary'
        assert Button(text='Reset', role=DANGER).role == DANGER

    def test_an_accelerator_activates_it(self, button):
        button.accelerator = 'y'
        assert button.accelerate('y')
        assert len(button.fired) == 1

    def test_a_different_key_is_not_its_accelerator(self, button):
        button.accelerator = 'y'
        assert not button.accelerate('n')


class TestToggle:
    def test_clicking_it_flips_the_value(self, metrics):
        toggle = Toggle(text='Shadows', value=False)
        toggle.arrange(Rect(0, 0, 200, 24), metrics)
        toggle.press(5, 5)
        toggle.release(5, 5)
        assert toggle.read() is True

    def test_it_writes_through_to_a_bound_field(self, metrics):
        settings = Settings()
        toggle = Toggle(text='Shadows', target=settings, fieldName='shadows')
        toggle.arrange(Rect(0, 0, 200, 24), metrics)
        assert toggle.read() is True
        toggle.press(5, 5)
        toggle.release(5, 5)
        assert not settings.shadows

    def test_it_reads_the_field_rather_than_its_own_value(self):
        settings = Settings(shadows=False)
        toggle = Toggle(target=settings, fieldName='shadows', value=True)
        assert toggle.read() is False


class TestTheSwitchAToggleDraws:
    """A sliding switch rather than a check box: the state is the shape."""

    @pytest.fixture
    def toggle(self, metrics):
        toggle = Toggle(value=False)
        toggle.arrange(Rect(0, 0, 200, 40), metrics)
        return toggle

    def test_the_track_is_wider_than_it_is_tall(self, toggle):
        track = toggle.switch_rect()
        assert track.width > track.height

    def test_the_track_sits_at_the_left_of_the_widget(self, toggle):
        assert toggle.switch_rect().x == toggle.rect.x

    def test_the_knob_rests_at_the_left_end_when_off(self, toggle):
        assert toggle.knob_rect().x < toggle.switch_rect().centre[0]

    def test_the_knob_slides_to_the_right_end_when_on(self, toggle):
        toggle.write(True)
        assert toggle.knob_rect().x > toggle.switch_rect().centre[0]

    def test_the_knob_stays_inside_the_track(self, toggle):
        for value in (False, True):
            toggle.write(value)
            knob, track = toggle.knob_rect(), toggle.switch_rect()
            assert knob.x >= track.x and knob.right <= track.right

    def test_the_knob_is_round(self, toggle):
        knob = toggle.knob_rect()
        assert knob.width == knob.height

    def test_it_asks_for_room_for_the_whole_switch(self, metrics):
        from OpenGLContext.ui.skin import DEFAULT_SKIN
        assert (Toggle().natural_size(metrics)[0]
                >= int(DEFAULT_SKIN.switchWidth))

    def test_text_beside_it_makes_it_wider(self, metrics):
        assert (Toggle(text='Shadows').natural_size(metrics)[0]
                > Toggle().natural_size(metrics)[0])

    def test_it_is_drawn_as_a_pill_with_a_round_knob(self, toggle):
        painted = _Recorder()
        toggle.paint(painted)
        assert painted.calls('pill') and painted.calls('disc')

    def test_the_track_changes_colour_with_the_value(self, toggle):
        off = _Recorder()
        toggle.paint(off)
        toggle.write(True)
        on = _Recorder()
        toggle.paint(on)
        assert tuple(off.calls('pill')[0][1]) != tuple(on.calls('pill')[0][1])

    def test_the_whole_switch_is_clickable_not_just_the_knob(self, toggle):
        """The knob is a small target and the track is the affordance."""
        track = toggle.switch_rect()
        toggle.press(track.right - 2, track.centre[1])
        toggle.release(track.right - 2, track.centre[1])
        assert toggle.read() is True


class TestTheFocusRing:
    """Focus has to be readable over a lit world, not merely present."""

    @pytest.fixture
    def button(self, metrics):
        from OpenGLContext.ui.panel import Panel
        button = Button(text='ok')
        panel = Panel(children=[button])
        panel.layout((400, 200), metrics)
        panel.focus(button)
        return button

    def test_a_focused_widget_gets_a_solid_ring(self, button):
        painted = _Recorder()
        button.paintFocus(painted)
        assert painted.calls('border')

    def test_and_a_glow_outside_it(self, button):
        painted = _Recorder()
        button.paintFocus(painted)
        assert painted.calls('glow')

    def test_the_ring_is_outside_the_widget(self, button):
        painted = _Recorder()
        button.paintFocus(painted)
        assert painted.calls('border')[0][0].width > button.rect.width

    def test_an_unfocused_widget_draws_nothing(self, metrics):
        from OpenGLContext.ui.panel import Panel
        button = Button(text='ok')
        panel = Panel(children=[button])
        panel.layout((400, 200), metrics)
        painted = _Recorder()
        button.paintFocus(painted)
        assert not painted.recorded


class _Recorder:
    """A renderer that records what it was asked to draw.

    The widgets' painting is arithmetic over their own rectangles; that the
    primitives reach the framebuffer is tested against real GL in
    ``test_ui_draw_gl``.
    """

    def __init__(self):
        from OpenGLContext.ui.metrics import FontMetrics
        from OpenGLContext.ui.skin import DEFAULT_SKIN
        self.metrics = FontMetrics(8, 16, 2)
        self.skin = DEFAULT_SKIN
        self.recorded = []

    def calls(self, name):
        """The arguments of every call to one primitive."""
        return [arguments for called, arguments in self.recorded
                if called == name]

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)

        def record(*arguments, **named):
            self.recorded.append((name, arguments))
        return record


class TestSelect:
    @pytest.fixture
    def select(self, metrics):
        settings = Settings()
        select = Select(text='Quality', options=['low', 'medium', 'high'],
                        target=settings, fieldName='quality')
        select.arrange(Rect(0, 0, 300, 24), metrics)
        select.settings = settings
        return select

    def test_it_starts_on_the_fields_value(self, select):
        assert select.read() == 'high'

    def test_it_cycles_forward_and_wraps(self, select):
        select.step(1)
        assert select.settings.quality == 'low'

    def test_it_cycles_backward(self, select):
        select.step(-1)
        assert select.settings.quality == 'medium'

    def test_a_value_outside_the_options_starts_at_the_first(self, metrics):
        select = Select(options=['a', 'b'], value='zzz')
        assert select.index == 0

    def test_clicking_the_right_arrow_steps_forward(self, select):
        rect = select.arrow_rects()[1]
        select.press(rect.x + 1, rect.y + 1)
        select.release(rect.x + 1, rect.y + 1)
        assert select.settings.quality == 'low'

    def test_clicking_the_left_arrow_steps_back(self, select):
        rect = select.arrow_rects()[0]
        select.press(rect.x + 1, rect.y + 1)
        select.release(rect.x + 1, rect.y + 1)
        assert select.settings.quality == 'medium'

    def test_arrow_keys_step_it(self, select):
        assert select.key('<right>', (0, 0, 0))
        assert select.settings.quality == 'low'

    def test_it_shows_a_label_rather_than_the_raw_value(self, metrics):
        select = Select(options=['low', 'high'], optionLabels=['Low', 'High'],
                        value='high')
        assert select.display_value() == 'High'

    def test_it_falls_back_to_the_value_when_unlabelled(self):
        assert Select(options=['low'], value='low').display_value() == 'low'

    def test_the_wheel_cycles_it(self, select):
        assert select.wheel(1, 10, 10)
        assert select.settings.quality == 'low'
        select.wheel(-1, 10, 10)
        assert select.settings.quality == 'high'

    def test_a_wheel_notch_of_nothing_does_nothing(self, select):
        assert not select.wheel(0, 10, 10)

    def test_a_key_it_does_not_use_is_left_alone(self, select):
        assert not select.key('z', (0, 0, 0))

    def test_clicking_between_the_arrows_steps_forward(self, select):
        """The arrows are small targets and the value is the obvious one."""
        rect = select.value_rect()
        select.press(*rect.centre)
        select.release(*rect.centre)
        assert select.settings.quality == 'low'

    def test_an_empty_select_neither_steps_nor_crashes(self):
        select = Select()
        select.step(1)
        assert select.display_value() == ''


class TestSlider:
    @pytest.fixture
    def slider(self, metrics):
        settings = Settings()
        slider = Slider(text='Lights', minimum=0, maximum=8, step=1,
                        integer=True, target=settings, fieldName='lights')
        slider.arrange(Rect(0, 0, 200, 24), metrics)
        slider.settings = settings
        return slider

    def test_it_shows_the_fields_value(self, slider):
        assert slider.read() == 4

    def test_dragging_the_thumb_sets_the_value(self, slider):
        track = slider.track_rect()
        slider.press(*slider.thumb_rect().centre)
        slider.drag(track.right, track.y + 1)
        assert slider.settings.lights == 8

    def test_dragging_past_the_start_clamps_at_the_minimum(self, slider):
        slider.press(*slider.thumb_rect().centre)
        slider.drag(-500, 5)
        assert slider.settings.lights == 0

    def test_clicking_the_track_jumps_to_that_value(self, slider):
        track = slider.track_rect()
        slider.press(track.x + track.width // 2, track.y + 1)
        assert slider.settings.lights == 4

    def test_an_integer_slider_never_stores_a_fraction(self, slider):
        track = slider.track_rect()
        slider.press(*slider.thumb_rect().centre)
        slider.drag(track.x + track.width // 3, track.y + 1)
        assert isinstance(slider.settings.lights, int)

    def test_arrow_keys_step_by_the_step(self, slider):
        assert slider.key('<right>', (0, 0, 0))
        assert slider.settings.lights == 5
        assert slider.key('<left>', (0, 0, 0))
        assert slider.settings.lights == 4

    def test_a_float_slider_keeps_fractions(self, metrics):
        settings = Settings()
        slider = Slider(minimum=0.0, maximum=2.0, step=0.25,
                        target=settings, fieldName='exposure')
        slider.arrange(Rect(0, 0, 200, 24), metrics)
        slider.key('<right>', (0, 0, 0))
        assert settings.exposure == pytest.approx(1.25)

    def test_home_and_end_go_to_the_ends(self, slider):
        slider.key('<end>', (0, 0, 0))
        assert slider.settings.lights == 8
        slider.key('<home>', (0, 0, 0))
        assert slider.settings.lights == 0

    def test_the_wheel_steps_it(self, slider):
        assert slider.wheel(1, 10, 10)
        assert slider.settings.lights == 5
        slider.wheel(-1, 10, 10)
        assert slider.settings.lights == 4

    def test_a_wheel_notch_of_nothing_does_nothing(self, slider):
        assert not slider.wheel(0, 10, 10)

    def test_a_key_it_does_not_use_is_left_alone(self, slider):
        assert not slider.key('z', (0, 0, 0))

    def test_it_prints_its_value_with_the_suffix(self, metrics):
        slider = Slider(minimum=0, maximum=10, value=3, suffix=' m/s')
        assert slider.display_value(metrics) == '3 m/s'

    def test_a_zero_range_slider_does_not_divide_by_zero(self, metrics):
        slider = Slider(minimum=1.0, maximum=1.0)
        slider.arrange(Rect(0, 0, 200, 24), metrics)
        assert slider.fraction() == 0.0
        slider.press(*slider.track_rect().centre)
        assert slider.read() == 1.0


class TestTextField:
    @pytest.fixture
    def entry(self, metrics):
        settings = Settings()
        entry = TextField(target=settings, fieldName='title')
        entry.arrange(Rect(0, 0, 200, 24), metrics)
        entry.settings = settings
        return entry

    def test_it_starts_from_the_field(self, entry):
        assert entry.read() == 'hello'

    def test_typing_inserts_at_the_cursor(self, entry):
        entry.focus_gained()
        entry.character('!')
        assert entry.settings.title == 'hello!'

    def test_backspace_deletes_before_the_cursor(self, entry):
        entry.focus_gained()
        entry.key('<backspace>', (0, 0, 0))
        assert entry.settings.title == 'hell'

    def test_the_cursor_can_be_moved_and_typed_into(self, entry):
        entry.focus_gained()
        entry.key('<home>', (0, 0, 0))
        entry.character('X')
        assert entry.settings.title == 'Xhello'

    def test_delete_removes_after_the_cursor(self, entry):
        entry.focus_gained()
        entry.key('<home>', (0, 0, 0))
        entry.key('<delete>', (0, 0, 0))
        assert entry.settings.title == 'ello'

    def test_it_wants_the_keyboard(self, entry):
        assert entry.focusable
        assert entry.acceptsText

    def test_it_refuses_more_than_its_maximum(self, entry):
        entry.maximumLength = 5
        entry.focus_gained()
        entry.character('!')
        assert entry.settings.title == 'hello'

    def test_clicking_puts_the_caret_where_it_was_clicked(self, entry, metrics):
        entry.focus_gained()
        pad = int(entry.activeSkin().fieldPadding)
        assert entry.caret_from(entry.rect.x + pad + metrics.char_width * 2,
                                metrics) == 2

    def test_a_click_past_the_end_puts_the_caret_at_the_end(self, entry, metrics):
        assert entry.caret_from(entry.rect.right, metrics) == len('hello')

    def test_backspace_at_the_start_deletes_nothing(self, entry):
        entry.focus_gained()
        entry.key('<home>', (0, 0, 0))
        entry.key('<backspace>', (0, 0, 0))
        assert entry.settings.title == 'hello'

    def test_delete_at_the_end_deletes_nothing(self, entry):
        entry.focus_gained()
        entry.key('<delete>', (0, 0, 0))
        assert entry.settings.title == 'hello'

    def test_the_cursor_stops_at_the_ends(self, entry):
        entry.focus_gained()
        entry.key('<end>', (0, 0, 0))
        entry.key('<right>', (0, 0, 0))
        assert entry.caret == len('hello')
        entry.key('<home>', (0, 0, 0))
        entry.key('<left>', (0, 0, 0))
        assert entry.caret == 0

    def test_enter_is_not_swallowed_so_the_panel_can_default(self, entry):
        entry.focus_gained()
        assert not entry.key('<return>', (0, 0, 0))


class TestKeyCapture:
    def test_it_takes_the_next_key_whatever_it_is(self, metrics):
        capture = KeyCapture(keys=['w'])
        assert capture.key('<tab>', (0, 0, 0))
        assert capture.captured == '<tab>'

    def test_escape_is_reserved_as_the_way_out(self):
        capture = KeyCapture(keys=['w'])
        assert not capture.key('<escape>', (0, 0, 0))
        assert capture.captured is None

    def test_the_captured_key_replaces_the_binding_on_commit(self):
        binding = node.Node()
        capture = KeyCapture(keys=['w'])
        capture.key('j', (0, 0, 0))
        assert capture.result() == ['j']
        assert binding is not None

    def test_a_mouse_button_can_be_bound(self):
        capture = KeyCapture()
        assert capture.button(2)
        assert capture.result() == ['<mouse2>']

    def test_an_unbound_capture_says_so(self):
        assert 'unbound' in KeyCapture().display_value()

    def test_a_captured_key_is_what_it_shows(self):
        capture = KeyCapture(keys=['w'])
        capture.key('j', (0, 0, 0))
        assert capture.display_value() == 'j'

    def test_nothing_captured_leaves_the_keys_alone(self):
        capture = KeyCapture(keys=['w', '<up>'])
        assert capture.result() == ['w', '<up>']


class TestKeyNames:
    def test_a_space_is_named_rather_than_shown_blank(self):
        """Jump is bound to space, and a blank button reads as unbound."""
        from OpenGLContext.ui.widgets import key_label
        assert key_label(' ') == '<space>'

    def test_an_ordinary_key_is_shown_as_it_is(self):
        from OpenGLContext.ui.widgets import key_label
        assert key_label('w') == 'w'
        assert key_label('<up>') == '<up>'

    def test_a_key_capture_shows_a_captured_space_by_name(self):
        capture = KeyCapture()
        capture.key(' ', (0, 0, 0))
        assert capture.display_value() == '<space>'

    def test_a_binding_on_space_is_not_shown_blank(self):
        assert KeyCapture(keys=[' ']).display_value() == '<space>'


class TestSpacer:
    def test_a_spacer_takes_no_natural_room_but_flexes(self, metrics):
        spacer = Spacer()
        assert spacer.natural_size(metrics) == (0, 0)
        assert spacer.flex == 1.0
