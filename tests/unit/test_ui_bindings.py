"""Rebinding a key: a capturing dialog, and a confirmation raised over it."""

import os

import pytest

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.move import bindingstore, modes as movemodes
from OpenGLContext.move.navigation import NavigationManager
from OpenGLContext.ui import bindings
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.overlay import OverlayMixin


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


class Platform:
    submerged = False


class World:
    def __init__(self, definition):
        self.contextDefinition = definition
        self.redraws = 0
        from OpenGLContext.events.inputstate import InputState
        self.inputState = InputState()

    def getViewPort(self):
        return (1024, 768)

    def getInputState(self):
        return self.inputState

    def triggerRedraw(self, force=0):
        self.redraws += 1

    def suspendPointerCapture(self, suspend):
        pass

    def hasMouseMoveHandlers(self):
        return False

    def ProcessEvent(self, event):
        return event


class Context(OverlayMixin, World):
    def overlayMetrics(self):
        return FontMetrics(8, 16, 2)

    def getNavigation(self):
        return self.navigation


@pytest.fixture
def context(tmp_path):
    made = Context(ContextDefinition(movementModes=[
        movemodes.WalkMode(name='walk'), movemodes.FlyMode(name='fly')]))
    made.navigation = NavigationManager(made.contextDefinition, Platform())
    made.bindingsPath = str(tmp_path / 'keys.json')
    return made


@pytest.fixture
def page(context, metrics):
    panel = bindings.bindings_panel(context, context.navigation,
                                    path=context.bindingsPath)
    context.pushOverlay(panel)
    return panel


class TestThePage:
    def test_every_declared_binding_has_a_row(self, page, context):
        for mode_name, binding in context.navigation.binding_table():
            assert page.find('%s.%s' % (mode_name, binding.command)) is not None

    def test_a_row_shows_the_keys_it_is_bound_to(self, page):
        assert 'w' in page.find('walk.forward').text

    def test_it_scrolls_because_there_are_many(self, page, context, metrics):
        page.layout((640, 300), metrics)
        assert page.find('body').maximumScroll > 0

    def test_a_command_bound_to_space_says_so(self, page):
        """Jump is bound to space; a blank row reads as unbound."""
        assert page.find('walk.jump').text == '<space>'

    def test_reset_is_marked_dangerous(self, page):
        assert page.find('reset').role == 'danger'


class TestCapturing:
    def test_clicking_a_row_opens_a_capturing_dialog(self, page, context):
        page.find('walk.forward').activate()
        assert context.overlays.top is not page
        assert context.overlays.top.capturing

    def test_the_dialog_says_escape_is_the_way_out(self, page, context):
        page.find('walk.forward').activate()
        text = ' '.join(getattr(widget, 'text', '')
                        for widget in context.overlays.top.walk())
        assert 'scape' in text

    def test_tab_is_captured_rather_than_traversing(self, page, context):
        page.find('walk.forward').activate()
        context.overlays.key('<tab>', (0, 0, 0))
        assert context.navigation.modes()[0].keys_for('forward') == ('<tab>',)

    def test_escape_leaves_the_binding_alone(self, page, context):
        page.find('walk.forward').activate()
        context.overlays.key('<escape>', (0, 0, 0))
        assert context.navigation.modes()[0].keys_for('forward') == ('w', '<up>')

    def test_capturing_an_unused_key_binds_it_at_once(self, page, context):
        page.find('walk.forward').activate()
        context.overlays.key('t', (0, 0, 0))
        assert context.navigation.modes()[0].keys_for('forward') == ('t',)

    def test_binding_closes_the_capture_dialog(self, page, context):
        page.find('walk.forward').activate()
        context.overlays.key('t', (0, 0, 0))
        assert context.overlays.top is page

    def test_the_row_shows_the_new_key(self, page, context):
        page.find('walk.forward').activate()
        context.overlays.key('t', (0, 0, 0))
        assert page.find('walk.forward').text == 't'

    def test_the_new_binding_is_saved_once_the_page_is_saved(self, page,
                                                             context):
        """The capture takes effect at once; the file waits for Save."""
        page.find('walk.forward').activate()
        context.overlays.key('t', (0, 0, 0))
        page.find('save').activate()
        fresh = NavigationManager(context.contextDefinition, Platform())
        for mode in fresh.modes():
            mode.bindings = list(mode.defaultBindings())
        bindingstore.load_bindings(fresh, context.bindingsPath)
        assert fresh.modes()[0].keys_for('forward') == ('t',)


class TestConflicts:
    def test_taking_a_key_already_bound_asks_first(self, page, context):
        """The natural nested modal: a confirmation over the capture dialog."""
        page.find('walk.forward').activate()
        capture = context.overlays.top
        context.overlays.key('s', (0, 0, 0))       # 's' is Back in walk mode
        assert context.overlays.top is not capture
        assert context.navigation.modes()[0].keys_for('forward') == ('w', '<up>')

    def test_the_question_names_what_would_lose_the_key(self, page, context):
        page.find('walk.forward').activate()
        context.overlays.key('s', (0, 0, 0))
        text = ' '.join(getattr(widget, 'text', '')
                        for widget in context.overlays.top.walk())
        assert 'Back' in text

    def test_confirming_steals_the_key(self, page, context):
        page.find('walk.forward').activate()
        context.overlays.key('s', (0, 0, 0))
        context.overlays.key('y', (0, 0, 0))
        assert context.navigation.modes()[0].keys_for('forward') == ('s',)
        assert context.navigation.modes()[0].keys_for('back') == ('<down>',)

    def test_declining_leaves_both_bindings_alone(self, page, context):
        page.find('walk.forward').activate()
        context.overlays.key('s', (0, 0, 0))
        context.overlays.key('n', (0, 0, 0))
        assert context.navigation.modes()[0].keys_for('forward') == ('w', '<up>')
        assert context.navigation.modes()[0].keys_for('back') == ('s', '<down>')

    def test_declining_leaves_the_capture_dialog_up_to_try_again(self, page,
                                                                 context):
        page.find('walk.forward').activate()
        capture = context.overlays.top
        context.overlays.key('s', (0, 0, 0))
        context.overlays.key('n', (0, 0, 0))
        assert context.overlays.top is capture

    def test_the_same_key_in_another_mode_is_not_a_conflict(self, page, context):
        page.find('fly.forward').activate()
        context.overlays.key('w', (0, 0, 0))
        assert context.navigation.modes()[1].keys_for('forward') == ('w',)


class TestReset:
    def test_reset_asks_before_throwing_every_binding_away(self, page, context):
        page.find('walk.forward').activate()
        context.overlays.key('t', (0, 0, 0))
        page.find('reset').activate()
        assert context.navigation.modes()[0].keys_for('forward') == ('t',)
        context.overlays.key('y', (0, 0, 0))
        assert context.navigation.modes()[0].keys_for('forward') == ('w', '<up>')

    def test_declining_the_reset_keeps_the_rebinding(self, page, context):
        page.find('walk.forward').activate()
        context.overlays.key('t', (0, 0, 0))
        page.find('reset').activate()
        context.overlays.key('n', (0, 0, 0))
        assert context.navigation.modes()[0].keys_for('forward') == ('t',)

    def test_the_rows_show_the_defaults_again_after_a_reset(self, page, context):
        page.find('walk.forward').activate()
        context.overlays.key('t', (0, 0, 0))
        page.find('reset').activate()
        context.overlays.key('y', (0, 0, 0))
        assert 'w' in page.find('walk.forward').text


class TestTheBindingsPageSavesOnlyOnSave:
    """Rebinding is an edit like any other, and Cancel undoes it.

    Writing the file on every captured key means there is no way back from a
    mis-hit, and it puts a save between the player and every keystroke.  So the
    page edits the live bindings -- a mode resolves a command to keys when it
    samples, so the change is visible at once -- and the file is written only
    when the page is left with Save.
    """

    @pytest.fixture
    def page(self, context, tmp_path):
        path = str(tmp_path / 'keys.json')
        panel = bindings.bindings_panel(context, context.getNavigation(),
                                        path=path)
        context.overlays.push(panel)
        panel.path = path
        return panel

    def _rebind(self, context, page, command, key):
        page.find('walk.%s' % (command,)).activate()
        capture = context.overlays.top.find('capture')
        capture.key(key, (0, 0, 0))

    def test_capturing_a_key_does_not_write_the_file(self, context, page):
        self._rebind(context, page, 'forward', 'z')
        assert not os.path.exists(page.path), "saved before Save was pressed"

    def test_capturing_a_key_takes_effect_at_once(self, context, page):
        self._rebind(context, page, 'forward', 'z')
        mode = context.getNavigation().modes()[0]
        assert list(mode.keys_for('forward')) == ['z']

    def test_save_writes_the_file(self, context, page):
        self._rebind(context, page, 'forward', 'z')
        page.find('save').activate()
        assert os.path.exists(page.path)
        assert 'z' in open(page.path).read()

    def test_cancel_puts_the_bindings_back(self, context, page):
        before = list(context.getNavigation().modes()[0].keys_for('forward'))
        self._rebind(context, page, 'forward', 'z')
        page.find('cancel').activate()
        assert list(context.getNavigation().modes()[0].keys_for('forward')) == before

    def test_cancel_writes_nothing(self, context, page):
        self._rebind(context, page, 'forward', 'z')
        page.find('cancel').activate()
        assert not os.path.exists(page.path)

    def test_escape_is_a_cancel(self, context, page):
        before = list(context.getNavigation().modes()[0].keys_for('forward'))
        self._rebind(context, page, 'forward', 'z')
        page.key('<escape>', (0, 0, 0))
        assert list(context.getNavigation().modes()[0].keys_for('forward')) == before
        assert not os.path.exists(page.path)

    def test_a_reset_is_undone_by_cancel_too(self, context, tmp_path):
        """Reset is an edit on the page, not an act of its own."""
        navigation = context.getNavigation()
        navigation.modes()[0].bindings[0].keys = ['z']       # what it opens with
        panel = bindings.bindings_panel(context, navigation,
                                        path=str(tmp_path / 'keys.json'))
        context.overlays.push(panel)
        panel.find('reset').activate()
        context.overlays.top.find('yes').activate()
        assert list(navigation.modes()[0].keys_for('forward')) != ['z']
        panel.find('cancel').activate()
        assert list(navigation.modes()[0].keys_for('forward')) == ['z']

    def test_a_reset_that_is_saved_sticks(self, context, page):
        self._rebind(context, page, 'forward', 'z')
        page.find('reset').activate()
        context.overlays.top.find('yes').activate()
        page.find('save').activate()
        assert 'z' not in open(page.path).read()

    def test_save_is_the_default_action(self, context, page):
        assert page.primary() is page.find('save')
