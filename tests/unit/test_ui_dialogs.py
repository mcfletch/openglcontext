"""The ready-made dialogs: a question, a message, and how wide they get."""

import pytest

from OpenGLContext.ui import dialogs
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import Label, PRIMARY


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


class TestPreferredWidth:
    def test_a_preferred_width_keeps_a_dialog_narrow(self, metrics):
        """Otherwise one long sentence makes a dialog as wide as the window."""
        panel = Panel(preferredColumns=40, children=[
            Label(text='word ' * 60, wrap=True)])
        panel.layout((1600, 900), metrics)
        assert panel.rect.width < 1600 // 2

    def test_the_text_is_measured_at_the_width_it_will_get(self, metrics):
        panel = Panel(preferredColumns=20, children=[
            Label(text='word ' * 20, wrap=True, name='text')])
        panel.layout((1600, 900), metrics)
        label = panel.find('text')
        assert label.rect.height >= 4 * metrics.line_height
        assert label.rect.top <= panel.rect.top

    def test_every_wrapped_line_fits(self, metrics):
        panel = Panel(preferredColumns=30, children=[
            Label(text='a moderately long sentence that must be wrapped',
                  wrap=True, name='text')])
        panel.layout((1600, 900), metrics)
        label = panel.find('text')
        for line in label.display_lines(metrics):
            assert metrics.text_width(line) <= label.rect.width

    def test_a_preferred_width_still_yields_to_a_small_window(self, metrics):
        panel = Panel(preferredColumns=80, children=[Label(text='x')])
        panel.layout((200, 200), metrics)
        assert panel.rect.width <= 200


class TestConfirm:
    @pytest.fixture
    def prompt(self, metrics):
        self.answers = []
        panel = dialogs.confirm(
            'Download the core textures?',
            detail='They are about 40MB and will be cached.',
            on_answer=self.answers.append)
        panel.layout((800, 600), metrics)
        return panel

    def test_yes_is_the_primary_and_so_the_enter_default(self, prompt):
        assert prompt.primary() is prompt.find('yes')
        assert prompt.find('yes').role == PRIMARY

    def test_clicking_yes_answers_true(self, prompt):
        x, y = prompt.find('yes').rect.centre
        prompt.pointer_pressed(x, y)
        prompt.pointer_released(x, y)
        assert self.answers == [True]

    def test_clicking_no_answers_false(self, prompt):
        x, y = prompt.find('no').rect.centre
        prompt.pointer_pressed(x, y)
        prompt.pointer_released(x, y)
        assert self.answers == [False]

    def test_the_keys_are_still_accelerators(self, prompt):
        prompt.key('y', (0, 0, 0))
        assert self.answers == [True]

    def test_escape_answers_no(self, prompt):
        prompt.key('<escape>', (0, 0, 0))
        assert self.answers == [False]

    def test_answering_closes_it(self, prompt):
        prompt.key('n', (0, 0, 0))
        assert prompt.closed

    def test_it_is_modal_and_dims_the_world(self, prompt):
        assert prompt.modal
        assert prompt.scrim

    def test_answering_twice_only_reports_once(self, prompt):
        prompt.key('y', (0, 0, 0))
        prompt.key('n', (0, 0, 0))
        assert self.answers == [True]

    def test_the_message_stays_inside_the_panel(self, prompt, metrics):
        for widget in prompt.walk():
            if isinstance(widget, Label):
                for line in widget.display_lines(metrics):
                    assert metrics.text_width(line) <= widget.rect.width
                assert prompt.rect.contains(widget.rect.x, widget.rect.y)

    def test_a_dangerous_question_marks_its_yes(self, metrics):
        panel = dialogs.confirm('Reset every binding?', danger=True)
        panel.layout((800, 600), metrics)
        assert panel.find('yes').role == 'danger'

    def test_the_labels_can_be_named_for_the_question(self, metrics):
        panel = dialogs.confirm('Overwrite?', yes='Overwrite', no='Keep')
        panel.layout((800, 600), metrics)
        assert panel.find('yes').text == 'Overwrite'


class TestMessage:
    def test_it_has_one_button_that_closes_it(self, metrics):
        panel = dialogs.message('Saved.', title='Settings')
        panel.layout((800, 600), metrics)
        panel.key('<return>', (0, 0, 0))
        assert panel.closed

    def test_it_reports_when_it_is_dismissed(self, metrics):
        seen = []
        panel = dialogs.message('Saved.', on_close=lambda p: seen.append(p))
        panel.layout((800, 600), metrics)
        panel.key('<escape>', (0, 0, 0))
        assert seen == [panel]


class TestNotice:
    def test_a_long_notice_scrolls_rather_than_growing(self, metrics):
        """These run to thousands of words; a panel that grew to fit one would
        be taller than any screen."""
        panel = dialogs.notice('Licence', 'word ' * 5000)
        panel.layout((800, 600), metrics)
        assert panel.rect.height <= 600
        assert panel.find('body').maximumScroll > 0

    def test_the_text_is_wrapped_inside_the_viewport(self, metrics):
        panel = dialogs.notice('Licence', 'word ' * 500)
        panel.layout((800, 600), metrics)
        text = panel.find('text')
        for line in text.display_lines(metrics)[:20]:
            assert metrics.text_width(line) <= text.rect.width

    def test_the_wheel_scrolls_it(self, metrics):
        panel = dialogs.notice('Licence', 'word ' * 5000)
        panel.layout((800, 600), metrics)
        body = panel.find('body')
        assert panel.wheel(-1, *body.rect.centre)
        assert body.scroll > 0

    def test_it_closes_on_its_button(self, metrics):
        panel = dialogs.notice('Licence', 'short')
        panel.layout((800, 600), metrics)
        panel.find('close').activate()
        assert panel.closed
