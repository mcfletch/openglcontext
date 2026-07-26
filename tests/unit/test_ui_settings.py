"""The game settings screen: what it offers, and when a change takes effect."""

import pytest

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.move import modes as movemodes
from OpenGLContext.ui import settings
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.overlay import OverlayMixin
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import Slider, Toggle


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


class World:
    def __init__(self, definition):
        self.contextDefinition = definition
        self.redraws = 0
        self.captureSuspended = None
        from OpenGLContext.events.inputstate import InputState
        self.inputState = InputState()

    def getViewPort(self):
        return (1024, 768)

    def getInputState(self):
        return self.inputState

    def triggerRedraw(self, force=0):
        self.redraws += 1

    def suspendPointerCapture(self, suspend):
        self.captureSuspended = suspend

    def hasMouseMoveHandlers(self):
        return False

    def ProcessEvent(self, event):
        return event


class Context(OverlayMixin, World):
    def overlayMetrics(self):
        return FontMetrics(8, 16, 2)


@pytest.fixture
def context():
    return Context(ContextDefinition(
        movementModes=[movemodes.WalkMode(name='walk'),
                       movemodes.FPSMode(name='fps')]))


@pytest.fixture
def screen(context, metrics):
    panel = settings.settings_panel(context)
    panel.layout((1024, 768), metrics)
    return panel


class TestTheScreen:
    def test_it_offers_the_rendering_features(self, screen):
        for name in ('shadows', 'bloom', 'ibl', 'maximumLights',
                     'transmission', 'instancing', 'tessellationLOD'):
            assert screen.find(name) is not None, name

    def test_shadows_are_a_toggle_and_lights_a_slider(self, screen):
        assert isinstance(screen.find('shadows'), Toggle)
        assert isinstance(screen.find('maximumLights'), Slider)

    def test_it_is_modal_and_fills_the_window(self, screen):
        assert screen.modal
        assert screen.fill

    def test_it_scrolls_when_there_is_more_than_fits(self, context, metrics):
        panel = settings.settings_panel(context)
        panel.layout((400, 240), metrics)
        assert panel.find('body').maximumScroll > 0

    def test_apply_is_the_primary_action(self, screen):
        assert screen.primary() is screen.find('apply')

    def test_apply_starts_disabled_because_nothing_has_changed(self, screen):
        assert not screen.find('apply').enabled


class TestEditingIsOnACopy:
    def test_a_change_does_not_reach_the_live_definition(self, screen, context):
        screen.find('shadows').activate()
        assert context.contextDefinition.shadows

    def test_apply_writes_it_through(self, screen, context):
        screen.find('shadows').activate()
        screen.find('apply').activate()
        assert not context.contextDefinition.shadows

    def test_cancel_throws_it_away(self, screen, context):
        screen.find('shadows').activate()
        screen.find('cancel').activate()
        assert context.contextDefinition.shadows

    def test_escape_is_a_cancel(self, screen, context):
        screen.find('shadows').activate()
        screen.key('<escape>', (0, 0, 0))
        assert context.contextDefinition.shadows

    def test_a_change_lights_the_apply_button(self, screen):
        screen.find('shadows').activate()
        assert screen.find('apply').enabled

    def test_applying_closes_the_screen(self, screen):
        screen.find('apply').activate()
        assert screen.closed

    def test_applying_asks_for_a_redraw(self, screen, context):
        before = context.redraws
        screen.find('shadows').activate()
        screen.find('apply').activate()
        assert context.redraws > before

    def test_applying_tells_the_context_to_re_read_its_settings(self, screen,
                                                                context):
        """The swap interval and the buffer format are not read per frame."""
        seen = []
        context.settingsChanged = lambda: seen.append(True)
        screen.find('apply').activate()
        assert seen == [True]

    def test_a_slider_writes_a_whole_number_of_lights(self, screen, context):
        lights = screen.find('maximumLights')
        lights.key('<left>', (0, 0, 0))
        screen.find('apply').activate()
        assert context.contextDefinition.maximumLights == 7


class TestMovementSubPage:
    def test_the_screen_offers_one_page_per_declared_mode(self, screen):
        assert screen.find('mode.walk') is not None
        assert screen.find('mode.fps') is not None

    def test_opening_one_pushes_a_dialog_over_the_screen(self, screen, context):
        context.pushOverlay(screen)
        screen.find('mode.walk').activate()
        assert context.overlays.top is not screen
        assert context.overlays.top.title.lower().startswith('walk')

    def test_the_sub_page_shows_the_modes_own_tunables(self, screen, context):
        context.pushOverlay(screen)
        screen.find('mode.walk').activate()
        page = context.overlays.top
        assert page.find('walkSpeed') is not None
        assert page.find('runSpeed') is not None

    def test_the_modes_name_is_not_offered_for_editing(self, screen, context):
        """Bindings are saved under it and a game refers to it by it."""
        context.pushOverlay(screen)
        screen.find('mode.walk').activate()
        assert context.overlays.top.find('name') is None

    def test_applying_the_sub_page_does_not_save(self, screen, context):
        context.pushOverlay(screen)
        screen.find('mode.walk').activate()
        page = context.overlays.top
        page.find('walkSpeed').write(9.0)
        page.find('apply').activate()
        assert context.contextDefinition.movementModes[0].walkSpeed == 3.0

    def test_applying_the_sub_page_then_the_screen_saves(self, screen, context):
        context.pushOverlay(screen)
        screen.find('mode.walk').activate()
        page = context.overlays.top
        page.find('walkSpeed').write(9.0)
        page.find('apply').activate()
        screen.find('apply').activate()
        assert context.contextDefinition.movementModes[0].walkSpeed == 9.0

    def test_cancelling_the_screen_undoes_an_applied_sub_page(self, screen, context):
        """Cancel at the top must be honest about everything below it."""
        context.pushOverlay(screen)
        screen.find('mode.walk').activate()
        page = context.overlays.top
        page.find('walkSpeed').write(9.0)
        page.find('apply').activate()
        screen.find('cancel').activate()
        assert context.contextDefinition.movementModes[0].walkSpeed == 3.0

    def test_cancelling_the_sub_page_changes_nothing(self, screen, context):
        context.pushOverlay(screen)
        screen.find('mode.walk').activate()
        page = context.overlays.top
        page.find('walkSpeed').write(9.0)
        page.find('cancel').activate()
        screen.find('apply').activate()
        assert context.contextDefinition.movementModes[0].walkSpeed == 3.0

    def test_an_applied_sub_page_lights_the_screens_apply(self, screen, context):
        context.pushOverlay(screen)
        screen.find('mode.walk').activate()
        page = context.overlays.top
        page.find('walkSpeed').write(9.0)
        page.find('apply').activate()
        assert screen.find('apply').enabled


class TestResetToDefaults:
    def test_reset_is_marked_dangerous(self, screen):
        assert screen.find('reset').role == 'danger'

    def test_reset_asks_first(self, screen, context):
        context.pushOverlay(screen)
        screen.find('reset').activate()
        assert context.overlays.top is not screen
        assert context.contextDefinition.shadows

    def test_confirming_the_reset_restores_the_defaults_in_the_draft(
            self, screen, context):
        context.pushOverlay(screen)
        screen.find('shadows').activate()
        screen.find('reset').activate()
        context.overlays.top.key('y', (0, 0, 0))
        assert screen.find('shadows').read()

    def test_declining_the_reset_keeps_the_edits(self, screen, context):
        context.pushOverlay(screen)
        screen.find('shadows').activate()
        screen.find('reset').activate()
        context.overlays.top.key('n', (0, 0, 0))
        assert not screen.find('shadows').read()


class TestOpeningItFromAContext:
    def test_a_context_can_open_its_own_settings(self, context):
        panel = settings.open_settings(context)
        assert isinstance(panel, Panel)
        assert context.overlays.top is panel

    def test_opening_it_twice_does_not_stack_two(self, context):
        settings.open_settings(context)
        settings.open_settings(context)
        assert len(context.overlays.panels) == 1
