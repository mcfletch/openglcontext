"""One screen: where it sits, what has focus, and what the keyboard does."""

import pytest

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.layout import Column, Row
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import (
    Button, KeyCapture, Label, Slider, TextField, Toggle, PRIMARY,
)


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


@pytest.fixture
def panel(metrics):
    """A dialog with a wrapped message and two buttons, laid out in a window."""
    yes = Button(text='Yes', role=PRIMARY, accelerator='y', name='yes')
    no = Button(text='No', accelerator='n', name='no')
    dialog = Panel(
        title='Download?',
        children=[Column(children=[
            Label(text='A long message that has to wrap inside the panel '
                       'rather than running off the end of it.', wrap=True),
            Row(children=[yes, no], spacing=8, flexJustify='end'),
        ], spacing=8)],
    )
    dialog.fired = []
    yes.on_activate = lambda widget: dialog.fired.append('yes')
    no.on_activate = lambda widget: dialog.fired.append('no')
    dialog.layout((800, 600), metrics)
    return dialog


class TestPlacement:
    def test_the_panel_is_centred_in_the_window(self, panel):
        assert abs((panel.rect.x + panel.rect.right) - 800) <= 1
        assert abs((panel.rect.y + panel.rect.top) - 600) <= 1

    def test_it_stays_inside_a_window_smaller_than_it_wants(self, metrics):
        dialog = Panel(children=[Label(text='x' * 400)])
        dialog.layout((200, 100), metrics)
        assert dialog.rect.width <= 200
        assert dialog.rect.height <= 100

    def test_the_text_stays_inside_the_panel(self, panel, metrics):
        label = next(widget for widget in panel.walk()
                     if isinstance(widget, Label))
        for line in label.display_lines(metrics):
            assert metrics.text_width(line) <= label.rect.width

    def test_a_filling_panel_takes_the_whole_window(self, metrics):
        screen = Panel(fill=True, margin=10, children=[Label(text='x')])
        screen.layout((800, 600), metrics)
        assert screen.rect == Rect(10, 10, 780, 580)

    def test_a_panel_with_nothing_in_it_still_lays_out(self, metrics):
        empty = Panel()
        empty.layout((800, 600), metrics)
        assert empty.rect.width >= 0


class TestPointer:
    def test_hovering_a_button_lights_it(self, panel):
        button = panel.find('yes')
        assert panel.pointer_moved(*button.rect.centre)
        assert button.hovered

    def test_moving_away_unlights_it(self, panel):
        button = panel.find('yes')
        panel.pointer_moved(*button.rect.centre)
        panel.pointer_moved(panel.rect.x + 1, panel.rect.top - 1)
        assert not button.hovered

    def test_a_click_fires_the_button_under_it(self, panel):
        x, y = panel.find('yes').rect.centre
        panel.pointer_pressed(x, y)
        panel.pointer_released(x, y)
        assert panel.fired == ['yes']

    def test_pressing_and_releasing_elsewhere_does_not_fire(self, panel):
        x, y = panel.find('yes').rect.centre
        panel.pointer_pressed(x, y)
        panel.pointer_moved(panel.rect.x + 1, panel.rect.y + 1)
        panel.pointer_released(panel.rect.x + 1, panel.rect.y + 1)
        assert panel.fired == []

    def test_a_click_on_bare_panel_does_nothing(self, panel):
        panel.pointer_pressed(panel.rect.x + 2, panel.rect.top - 2)
        panel.pointer_released(panel.rect.x + 2, panel.rect.top - 2)
        assert panel.fired == []

    def test_a_click_outside_the_panel_is_still_sunk_by_a_modal(self, panel):
        assert panel.modal
        assert not panel.rect.contains(2, 2)
        assert panel.pointer_pressed(2, 2) is False

    def test_a_wheel_notch_over_the_bare_panel_does_nothing(self, panel):
        """The panel is where the walk up the parents ends, not another rung.

        It is its own ancestor at the top of that walk and is what
        ``widget_at`` answers for a point on no widget at all, so offering it
        the notch would start the identical walk over and never come back.
        """
        assert panel.wheel(-1, panel.rect.x + 2, panel.rect.top - 2) is False

    def test_a_wheel_notch_over_a_widget_that_ignores_it_does_nothing(self,
                                                                     panel):
        assert panel.wheel(-1, *panel.find('yes').rect.centre) is False

    def test_dragging_a_slider_keeps_the_slider(self, metrics):
        slider = Slider(minimum=0, maximum=10, name='s')
        screen = Panel(children=[Column(children=[slider])], fill=True)
        screen.layout((400, 200), metrics)
        screen.pointer_pressed(*slider.thumb_rect().centre)
        screen.pointer_moved(slider.track_rect().right, slider.rect.y + 1)
        assert slider.read() == 10


class TestFocus:
    def test_tab_moves_to_the_first_focusable(self, panel):
        panel.key('<tab>', (0, 0, 0))
        assert panel.focused_widget is panel.find('yes')

    def test_tab_moves_on_and_wraps(self, panel):
        panel.key('<tab>', (0, 0, 0))
        panel.key('<tab>', (0, 0, 0))
        assert panel.focused_widget is panel.find('no')
        panel.key('<tab>', (0, 0, 0))
        assert panel.focused_widget is panel.find('yes')

    def test_shift_tab_goes_back(self, panel):
        panel.key('<tab>', (0, 0, 0))
        panel.key('<tab>', (1, 0, 0))
        assert panel.focused_widget is panel.find('no')

    def test_the_focused_widget_knows_it(self, panel):
        panel.key('<tab>', (0, 0, 0))
        assert panel.find('yes').focused
        panel.key('<tab>', (0, 0, 0))
        assert not panel.find('yes').focused

    def test_keyboard_focus_shows_the_ring(self, panel):
        panel.key('<tab>', (0, 0, 0))
        assert panel.focusVisible

    def test_clicking_a_button_does_not_leave_a_ring(self, panel):
        """A button that keeps a ring after a click looks stuck."""
        x, y = panel.find('yes').rect.centre
        panel.pointer_pressed(x, y)
        panel.pointer_released(x, y)
        assert not panel.focusVisible

    def test_clicking_into_a_text_field_does_show_the_ring(self, metrics):
        entry = TextField(name='e')
        screen = Panel(children=[Column(children=[entry])], fill=True)
        screen.layout((400, 200), metrics)
        screen.pointer_pressed(*entry.rect.centre)
        screen.pointer_released(*entry.rect.centre)
        assert screen.focused_widget is entry
        assert screen.focusVisible

    def test_a_disabled_widget_is_skipped(self, panel):
        panel.find('yes').enabled = False
        panel.key('<tab>', (0, 0, 0))
        assert panel.focused_widget is panel.find('no')

    def test_a_panel_with_nothing_focusable_survives_tab(self, metrics):
        screen = Panel(children=[Label(text='x')])
        screen.layout((400, 200), metrics)
        screen.key('<tab>', (0, 0, 0))
        assert screen.focused_widget is None

    def test_typed_characters_go_to_the_focused_field(self, metrics):
        entry = TextField(name='e', value='ab')
        screen = Panel(children=[Column(children=[entry])], fill=True)
        screen.layout((400, 200), metrics)
        screen.key('<tab>', (0, 0, 0))
        screen.character('c')
        assert entry.read() == 'abc'

    def test_characters_with_nothing_focused_are_dropped(self, panel):
        assert not panel.character('x')


class TestKeyboard:
    def test_enter_runs_the_primary_button(self, panel):
        panel.key('<return>', (0, 0, 0))
        assert panel.fired == ['yes']

    def test_enter_goes_to_the_focused_widget_first(self, panel):
        panel.focus(panel.find('no'))
        panel.key('<return>', (0, 0, 0))
        assert panel.fired == ['no']

    def test_an_accelerator_fires_from_anywhere(self, panel):
        assert panel.key('n', (0, 0, 0))
        assert panel.fired == ['no']

    def test_escape_closes_the_panel(self, panel):
        panel.key('<escape>', (0, 0, 0))
        assert panel.closed

    def test_a_panel_can_refuse_to_close_on_escape(self, metrics):
        screen = Panel(closeOnEscape=False, children=[Label(text='x')])
        screen.layout((400, 200), metrics)
        screen.key('<escape>', (0, 0, 0))
        assert not screen.closed

    def test_closing_reports_the_result(self, panel):
        answers = []
        panel.on_close = lambda dialog: answers.append(dialog.result)
        panel.close('yes')
        assert answers == ['yes']

    def test_an_unrelated_key_is_still_consumed_by_a_modal(self, panel):
        """A modal overlay is a lid, not a filter: nothing reaches the world."""
        assert panel.modal
        assert panel.key('z', (0, 0, 0)) is False
        assert panel.fired == []


class TestCapturing:
    @pytest.fixture
    def capture_panel(self, metrics):
        capture = KeyCapture(keys=['w'], name='capture')
        cancel = Button(text='Cancel', accelerator='c', name='cancel')
        screen = Panel(capturing=True, children=[
            Column(children=[capture, cancel])])
        screen.fired = []
        cancel.on_activate = lambda widget: screen.fired.append('cancel')
        screen.layout((400, 200), metrics)
        screen.focus(capture)
        return screen

    def test_tab_is_captured_rather_than_traversing(self, capture_panel):
        capture_panel.key('<tab>', (0, 0, 0))
        assert capture_panel.find('capture').captured == '<tab>'
        assert capture_panel.focused_widget is capture_panel.find('capture')

    def test_enter_is_captured_rather_than_defaulting(self, capture_panel):
        capture_panel.key('<return>', (0, 0, 0))
        assert capture_panel.find('capture').captured == '<return>'

    def test_an_accelerator_is_captured_rather_than_run(self, capture_panel):
        capture_panel.key('c', (0, 0, 0))
        assert capture_panel.find('capture').captured == 'c'
        assert capture_panel.fired == []

    def test_escape_still_gets_you_out(self, capture_panel):
        capture_panel.key('<escape>', (0, 0, 0))
        assert capture_panel.closed
        assert capture_panel.find('capture').captured is None

    def test_a_mouse_button_can_be_bound(self, capture_panel):
        capture_panel.pointer_pressed(2, 2, button=1)
        assert capture_panel.find('capture').captured == '<mouse1>'


class TestCommands:
    def test_a_named_action_runs_a_registered_command(self, metrics):
        done = []
        button = Button(text='Apply', action='commit', name='apply')
        screen = Panel(children=[Column(children=[button])])
        screen.commands['commit'] = lambda dialog, widget: done.append(widget)
        screen.layout((400, 200), metrics)
        button.activate()
        assert done == [button]

    def test_an_unknown_action_is_ignored(self, metrics):
        button = Button(text='Apply', action='nosuch')
        screen = Panel(children=[Column(children=[button])])
        screen.layout((400, 200), metrics)
        button.activate()

    def test_close_is_a_command_every_panel_has(self, metrics):
        button = Button(text='Close', action='close')
        screen = Panel(children=[Column(children=[button])])
        screen.layout((400, 200), metrics)
        button.activate()
        assert screen.closed

    def test_a_value_change_marks_the_panel(self, metrics):
        toggle = Toggle(text='x', name='t')
        screen = Panel(children=[Column(children=[toggle])])
        screen.layout((400, 200), metrics)
        toggle.activate()
        assert screen.dirty


class TestArrowKeysMoveBetweenItems:
    """A menu is walked with the arrow keys, not only with Tab.

    Tab has always worked, and Space or Enter on the focused item has always
    activated it -- but a menu is a list and arrows are what a list is walked
    with, so pressing Down on one did nothing at all.

    Only what the focused widget did not want: a Select, a Slider and a
    Carousel all use arrows themselves, and taking them away would be worse
    than never having offered them.
    """

    def menu(self):
        from OpenGLContext.ui.layout import Column
        from OpenGLContext.ui.widgets import Button
        return Panel(children=[Column(children=[
            Button(text='One', name='one'),
            Button(text='Two', name='two'),
            Button(text='Three', name='three'),
        ])])

    def press(self, panel, name):
        return panel.key(name, (0, 0, 0))

    def test_down_moves_to_the_next_item(self):
        panel = self.menu()
        panel.focus(panel.find('one'))
        assert self.press(panel, '<down>')
        assert panel.focused_widget is panel.find('two')

    def test_up_moves_back(self):
        panel = self.menu()
        panel.focus(panel.find('two'))
        self.press(panel, '<up>')
        assert panel.focused_widget is panel.find('one')

    def test_it_wraps_at_the_end(self):
        panel = self.menu()
        panel.focus(panel.find('three'))
        self.press(panel, '<down>')
        assert panel.focused_widget is panel.find('one')

    def test_down_with_nothing_focused_takes_the_first(self):
        """Pressing an arrow at a fresh screen should land somewhere."""
        panel = self.menu()
        self.press(panel, '<down>')
        assert panel.focused_widget is panel.find('one')

    def test_space_activates_what_is_focused(self):
        panel = self.menu()
        chosen = []
        panel.find('two').on_activate = chosen.append
        panel.focus(panel.find('two'))
        self.press(panel, ' ')
        assert chosen == [panel.find('two')]

    def test_return_activates_what_is_focused(self):
        panel = self.menu()
        chosen = []
        panel.find('two').on_activate = chosen.append
        panel.focus(panel.find('two'))
        self.press(panel, '<return>')
        assert chosen == [panel.find('two')]

    def test_a_widget_that_wants_the_arrow_keeps_it(self):
        from OpenGLContext.ui.layout import Column
        from OpenGLContext.ui.widgets import Button, Select
        chooser = Select(name='pick', options=['a', 'b'], value='a')
        panel = Panel(children=[Column(children=[
            chooser, Button(text='Go', name='go')])])
        panel.focus(chooser)
        self.press(panel, '<right>')
        assert str(chooser.value) == 'b'
        assert panel.focused_widget is chooser, 'focus moved instead of choosing'

    def test_the_focus_ring_is_shown_once_the_keyboard_is_in_use(self):
        """Moving by arrow with no visible ring leaves you guessing where you are."""
        panel = self.menu()
        self.press(panel, '<down>')
        assert panel.focusVisible
