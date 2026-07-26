"""Rebinding a key: a capturing dialog, and a confirmation raised over it."""

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

    def test_the_new_binding_is_saved(self, page, context):
        page.find('walk.forward').activate()
        context.overlays.key('t', (0, 0, 0))
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
