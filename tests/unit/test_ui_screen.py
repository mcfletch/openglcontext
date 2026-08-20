"""The screen-space layers a context draws over its frame, and their order.

None of this needs a window: the layers are laid out against a viewport and a
font, and what comes back is the list of trees the renderer would paint, in the
order it would paint them.
"""

import pytest

from OpenGLContext.ui.hudwidgets import HUDLayer, Readout
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.overlay import OverlayMixin
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.screen import ScreenMixin


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


class Window:
    """Only the parts of a context the screen layers touch."""

    def __init__(self):
        self.viewport = (800, 600)
        self.redraws = 0
        self.frameCounter = None
        self.coreProfile = True
        self.contextDefinition = None

    def getViewPort(self):
        return self.viewport

    def getViewPlatform(self):
        return None

    def triggerRedraw(self, force=0):
        self.redraws += 1

    def getInputState(self):
        raise AssertionError('a HUD never touches the input sampler')

    def suspendPointerCapture(self, suspend):
        raise AssertionError('a HUD never takes the pointer')


class Screen(ScreenMixin, Window):
    pass


class Game(OverlayMixin, ScreenMixin, Window):
    """A context with both a HUD and screens over it."""

    def __init__(self):
        super(Game, self).__init__()
        self.captureSuspended = None

    def getInputState(self):
        from OpenGLContext.events.inputstate import InputState
        if not hasattr(self, '_inputState'):
            self._inputState = InputState()
        return self._inputState

    def suspendPointerCapture(self, suspend):
        self.captureSuspended = suspend


class TestLayers:
    def test_a_context_starts_with_no_hud(self):
        assert Screen().hudLayers == []

    def test_a_layer_can_be_added_and_taken_away(self):
        screen = Screen()
        layer = HUDLayer()
        screen.addHUDLayer(layer)
        assert screen.hudLayers == [layer]
        screen.removeHUDLayer(layer)
        assert screen.hudLayers == []

    def test_adding_a_layer_asks_for_a_redraw(self):
        screen = Screen()
        screen.addHUDLayer(HUDLayer())
        assert screen.redraws == 1

    def test_removing_one_that_was_never_added_is_not_an_error(self):
        screen = Screen()
        screen.removeHUDLayer(HUDLayer())
        assert screen.hudLayers == []

    def test_the_layers_are_laid_out_for_the_window(self, metrics):
        screen = Screen()
        readout = Readout(value='100', anchor='bottom-left')
        screen.addHUDLayer(HUDLayer(children=[readout], margin=0))
        screen.screenTrees(metrics)
        assert readout.rect.x == 0
        assert readout.rect.y == 0

    def test_a_hidden_layer_is_not_drawn(self, metrics):
        screen = Screen()
        screen.addHUDLayer(HUDLayer(visible=False))
        assert screen.screenTrees(metrics) == []

    def test_the_layers_are_ticked_from_the_engine_s_clock(self, metrics):
        """One clock for the whole scene, and the HUD is in the scene.

        The engine's time source is what a recorded session replaces
        (:mod:`OpenGLContext.telemetry`), so a HUD reading it fades and expires
        exactly as it did when the session was recorded -- and a game whose own
        timings come from the same clock stays in step with what is drawn.
        """
        from OpenGLContext.events import systemtime
        from OpenGLContext.ui.hudwidgets import MessageQueue
        screen = Screen()
        queue = MessageQueue(duration=1.0)
        screen.addHUDLayer(HUDLayer(children=[queue]))
        queue.post('fresh', now=0.0)
        previous = systemtime.setTimeSource(lambda: 0.5)
        try:
            screen.screenTrees(metrics)
        finally:
            systemtime.setTimeSource(previous)
        assert [message.text for message in queue.messages] == ['fresh']

    def test_the_layers_are_ticked_before_they_are_drawn(self, metrics):
        from OpenGLContext.ui.hudwidgets import MessageQueue
        screen = Screen()
        queue = MessageQueue(duration=1.0)
        screen.addHUDLayer(HUDLayer(children=[queue]))
        queue.post('stale', now=0.0)
        screen.screenTrees(metrics, now=100.0)
        assert queue.messages == []


class TestDebugOverlay:
    def test_it_is_made_on_first_use_and_kept(self):
        screen = Screen()
        assert screen.debugOverlay is screen.debugOverlay

    def test_it_joins_the_hud_layers(self):
        screen = Screen()
        assert screen.debugOverlay in screen.hudLayers

    def test_it_comes_with_the_sections_every_context_can_answer(self):
        screen = Screen()
        titles = [section.title for section in screen.debugOverlay.sections()]
        assert 'Frame' in titles

    def test_toggling_shows_and_hides_it(self):
        screen = Screen()
        screen.debugOverlay.visible = False
        assert screen.toggleDebugOverlay() is True
        assert screen.toggleDebugOverlay() is False

    def test_toggling_asks_for_a_redraw(self):
        screen = Screen()
        before = screen.redraws
        screen.toggleDebugOverlay()
        assert screen.redraws > before

    def test_it_starts_hidden_when_captures_asked_for_a_clean_frame(
            self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_DISABLE_FPS_DISPLAY', '1')
        assert not Screen().debugOverlay.visible


class TestDrawingOrder:
    def test_the_hud_is_drawn_under_the_screens(self, metrics):
        game = Game()
        layer = HUDLayer()
        game.addHUDLayer(layer)
        panel = Panel(title='Settings')
        game.pushOverlay(panel)
        assert game.screenTrees(metrics) == [layer, panel]

    def test_a_game_with_no_screens_open_still_draws_its_hud(self, metrics):
        game = Game()
        layer = HUDLayer()
        game.addHUDLayer(layer)
        assert game.screenTrees(metrics) == [layer]

    def test_a_hud_never_sinks_an_event(self):
        """The layers exist; the world must still hear everything."""
        game = Game()
        game.addHUDLayer(HUDLayer(children=[Readout(value='100')]))

        class Event:
            type = 'keyboard'
            name = 'w'
            state = 1

            def getModifiers(self):
                return (0, 0, 0)

        assert game.overlaySinks(Event()) is False
