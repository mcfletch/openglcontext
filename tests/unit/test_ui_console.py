"""The console: scrollback, an input line, commands, and the log it shows."""

import logging

import pytest

from OpenGLContext.ui import console
from OpenGLContext.ui.metrics import FontMetrics


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


@pytest.fixture
def registry():
    made = console.CommandRegistry()
    made.add('echo', lambda panel, *words: ' '.join(words), 'repeat the words')
    return made


@pytest.fixture
def panel(registry, metrics):
    made = console.console_panel(registry=registry)
    made.layout((800, 600), metrics)
    return made


class TestRegistry:
    def test_a_command_runs_and_returns_its_output(self, registry):
        assert registry.dispatch(None, 'echo hello there') == 'hello there'

    def test_an_unknown_command_says_so(self, registry):
        assert 'unknown' in registry.dispatch(None, 'nosuch').lower()

    def test_an_empty_line_does_nothing(self, registry):
        assert registry.dispatch(None, '   ') is None

    def test_help_lists_what_there_is(self, registry):
        text = registry.dispatch(None, 'help')
        assert 'echo' in text
        assert 'repeat the words' in text

    def test_help_on_one_command_describes_it(self, registry):
        assert 'repeat the words' in registry.dispatch(None, 'help echo')

    def test_a_command_that_raises_reports_rather_than_dying(self, registry):
        def broken(panel):
            raise ValueError('deliberate')
        registry.add('broken', broken, 'always fails')
        assert 'deliberate' in registry.dispatch(None, 'broken')

    def test_commands_are_listed_in_order(self, registry):
        registry.add('alpha', lambda panel: '', 'first')
        assert registry.names()[0] == 'alpha'


class TestScrollback:
    def test_writing_adds_a_line(self, panel):
        panel.write('hello')
        assert panel.view.lines[-1].text == 'hello'

    def test_several_lines_at_once_are_split(self, panel):
        panel.write('one\ntwo')
        assert [line.text for line in panel.view.lines[-2:]] == ['one', 'two']

    def test_the_scrollback_is_bounded(self, panel):
        panel.view.maximumLines = 5
        for index in range(20):
            panel.write('line %d' % (index,))
        assert len(panel.view.lines) == 5
        assert panel.view.lines[-1].text == 'line 19'

    def test_clearing_empties_it(self, panel):
        panel.write('hello')
        panel.clear()
        assert panel.view.lines == []

    def test_a_level_is_kept_so_a_warning_can_be_coloured(self, panel):
        panel.write('careful', level=logging.WARNING)
        assert panel.view.lines[-1].level == logging.WARNING

    def test_new_output_scrolls_to_the_bottom(self, panel, metrics):
        for index in range(200):
            panel.write('line %d' % (index,))
        panel.layout((800, 600), metrics)
        assert panel.body.scroll == panel.body.maximumScroll

    def test_it_measures_as_tall_as_its_lines(self, panel, metrics):
        panel.write('one\ntwo\nthree')
        height = panel.view.natural_size(metrics)[1]
        assert height >= 3 * metrics.line_height


class TestTheInputLine:
    def test_typing_and_entering_runs_the_command(self, panel):
        panel.entry.write('echo hi')
        panel.submit()
        assert 'hi' in [line.text for line in panel.view.lines]

    def test_the_line_is_echoed_with_a_prompt(self, panel):
        panel.entry.write('echo hi')
        panel.submit()
        assert any(line.text.startswith(console.PROMPT)
                   for line in panel.view.lines)

    def test_submitting_clears_the_input(self, panel):
        panel.entry.write('echo hi')
        panel.submit()
        assert panel.entry.read() == ''

    def test_enter_submits_from_the_input_line(self, panel):
        panel.focus(panel.entry)
        panel.entry.write('echo hi')
        panel.key('<return>', (0, 0, 0))
        assert 'hi' in [line.text for line in panel.view.lines]

    def test_the_input_line_has_focus_when_it_opens(self, panel):
        assert panel.focused_widget is panel.entry

    def test_the_up_arrow_recalls_the_last_command(self, panel):
        panel.entry.write('echo one')
        panel.submit()
        panel.key('<up>', (0, 0, 0))
        assert panel.entry.read() == 'echo one'

    def test_the_down_arrow_comes_back_to_an_empty_line(self, panel):
        panel.entry.write('echo one')
        panel.submit()
        panel.key('<up>', (0, 0, 0))
        panel.key('<down>', (0, 0, 0))
        assert panel.entry.read() == ''

    def test_history_does_not_run_off_the_end(self, panel):
        panel.entry.write('echo one')
        panel.submit()
        for _ in range(5):
            panel.key('<up>', (0, 0, 0))
        assert panel.entry.read() == 'echo one'

    def test_an_empty_submission_does_nothing(self, panel):
        before = len(panel.view.lines)
        panel.submit()
        assert len(panel.view.lines) == before


class TestLogHandler:
    def test_a_log_record_reaches_the_console(self, panel):
        handler = console.ConsoleLogHandler(panel)
        logger = logging.getLogger('test.console')
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            logger.warning('something to see')
        finally:
            logger.removeHandler(handler)
        assert any('something to see' in line.text for line in panel.view.lines)

    def test_the_level_comes_through_so_it_can_be_coloured(self, panel):
        handler = console.ConsoleLogHandler(panel)
        record = logging.LogRecord('x', logging.ERROR, __file__, 1,
                                   'bad', (), None)
        handler.emit(record)
        assert panel.view.lines[-1].level == logging.ERROR

    def test_a_handler_whose_console_has_closed_stops_writing(self, panel):
        handler = console.ConsoleLogHandler(panel)
        panel.close(None)
        record = logging.LogRecord('x', logging.INFO, __file__, 1, 'late',
                                   (), None)
        handler.emit(record)
        assert not any('late' in line.text for line in panel.view.lines)


class TestPanelBehaviour:
    def test_it_sinks_input_while_it_is_up(self, panel):
        """Typing into a console must not also walk the character."""
        assert panel.modal

    def test_it_can_be_asked_for_modelessly(self, registry, metrics):
        made = console.console_panel(registry=registry, modal=False)
        assert not made.modal

    def test_escape_closes_it(self, panel):
        panel.key('<escape>', (0, 0, 0))
        assert panel.closed

    def test_it_scrolls_with_the_wheel(self, panel, metrics):
        for index in range(200):
            panel.write('line %d' % (index,))
        panel.layout((800, 400), metrics)
        before = panel.body.scroll
        panel.wheel(1, *panel.body.rect.centre)
        assert panel.body.scroll < before
