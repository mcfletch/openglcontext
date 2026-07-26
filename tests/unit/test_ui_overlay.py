"""The overlay stack and the context mix-in that feeds it.

Modality is the rule with the most consequences in the system, so it is pinned
here from both ends: what the stack passes on, and what a context does with the
events it sinks.
"""

import pytest

from OpenGLContext.events.inputstate import InputState
from OpenGLContext.ui.layout import Column
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.overlay import OverlayMixin, OverlayStack
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import Button, Label


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


def dialog(**named):
    button = Button(text='Ok', name='ok', accelerator='o')
    named.setdefault('children', [Column(children=[Label(text='hi'), button])])
    return Panel(**named)


class FakeEvent:
    """The shape of an OpenGLContext event, with only what routing reads."""

    def __init__(self, type, name='', state=1, button=0, pick=(10, 10),
                 modifiers=(0, 0, 0)):
        self.type = type
        self.name = name
        self.state = state
        self.button = button
        self.pickPoint = pick
        self._modifiers = modifiers

    def getPickPoint(self):
        return self.pickPoint

    def getModifiers(self):
        return self._modifiers


class World:
    """Stands in for the rest of the context: records what got through."""

    def __init__(self):
        self.dispatched = []
        self.redraws = 0
        self.captureSuspended = None
        self.inputState = InputState()
        self.viewport = (800, 600)

    def getViewPort(self):
        return self.viewport

    def getInputState(self):
        return self.inputState

    def triggerRedraw(self, force=0):
        self.redraws += 1

    def suspendPointerCapture(self, suspend):
        self.captureSuspended = suspend

    def hasMouseMoveHandlers(self):
        return False

    def ProcessEvent(self, event):
        self.inputState.process(event)
        self.dispatched.append(event)
        return event


class FakeContext(OverlayMixin, World):
    """The real mix-in over a stand-in world, with no window at all."""

    def overlayMetrics(self):
        return FontMetrics(8, 16, 2)


class TestStack:
    def test_a_new_stack_shows_nothing(self):
        assert not OverlayStack().visible

    def test_pushing_makes_it_visible(self):
        stack = OverlayStack()
        stack.push(dialog())
        assert stack.visible
        assert stack.top is stack.panels[0]

    def test_the_last_pushed_is_on_top(self):
        stack = OverlayStack()
        first, second = dialog(), dialog()
        stack.push(first)
        stack.push(second)
        assert stack.top is second

    def test_closing_the_top_pops_it(self):
        stack = OverlayStack()
        first, second = dialog(), dialog()
        stack.push(first)
        stack.push(second)
        second.close('done')
        assert stack.top is first
        assert second.result == 'done'

    def test_popping_the_last_leaves_nothing_visible(self):
        stack = OverlayStack()
        panel = dialog()
        stack.push(panel)
        stack.pop()
        assert not stack.visible

    def test_a_panel_pushed_over_another_suspends_it(self):
        stack = OverlayStack()
        first = dialog()
        stack.push(first)
        first.pointer_moved(*first.find('ok').rect.centre)
        stack.push(dialog())
        assert not first.find('ok').hovered

    def test_closing_a_child_gives_focus_back_to_the_parent(self, metrics):
        stack = OverlayStack()
        first = dialog()
        stack.push(first, viewport=(800, 600), metrics=metrics)
        first.focus(first.find('ok'))
        second = dialog()
        stack.push(second, viewport=(800, 600), metrics=metrics)
        second.close(None)
        assert first.focused_widget is first.find('ok')

    def test_only_the_top_panel_hears_a_key(self, metrics):
        stack = OverlayStack()
        first, second = dialog(), dialog()
        fired = []
        first.find('ok').on_activate = lambda widget: fired.append('first')
        second.find('ok').on_activate = lambda widget: fired.append('second')
        stack.push(first, viewport=(800, 600), metrics=metrics)
        stack.push(second, viewport=(800, 600), metrics=metrics)
        stack.key('o', (0, 0, 0))
        assert fired == ['second']

    def test_a_modeless_panel_does_not_sink(self, metrics):
        stack = OverlayStack()
        stack.push(dialog(modal=False), viewport=(800, 600), metrics=metrics)
        assert not stack.sinks()

    def test_a_modal_panel_sinks(self, metrics):
        stack = OverlayStack()
        stack.push(dialog(), viewport=(800, 600), metrics=metrics)
        assert stack.sinks()

    def test_a_modeless_panel_under_a_modal_one_still_sinks(self, metrics):
        stack = OverlayStack()
        stack.push(dialog(modal=False), viewport=(800, 600), metrics=metrics)
        stack.push(dialog(modal=True), viewport=(800, 600), metrics=metrics)
        assert stack.sinks()

    def test_clear_closes_everything(self, metrics):
        stack = OverlayStack()
        first, second = dialog(), dialog()
        stack.push(first)
        stack.push(second)
        stack.clear()
        assert not stack.visible
        assert first.closed and second.closed

    def test_removing_something_not_in_the_stack_is_harmless(self):
        stack = OverlayStack()
        stack.remove(dialog())
        assert not stack.visible

    def test_popping_an_empty_stack_gives_nothing(self):
        assert OverlayStack().pop() is None

    def test_only_a_capturing_top_panel_reports_capturing(self, metrics):
        stack = OverlayStack()
        assert not stack.capturing()
        stack.push(dialog(capturing=True))
        assert stack.capturing()
        stack.push(dialog())
        assert not stack.capturing()

    def test_the_wheel_goes_to_the_top_panel(self, metrics):
        from OpenGLContext.ui.scroll import ScrollViewport
        from OpenGLContext.ui.widgets import Label
        stack = OverlayStack()
        view = ScrollViewport(name='view', flex=1,
                              children=[Label(text='line\n' * 80)])
        panel = Panel(fill=True, children=[view])
        stack.push(panel, viewport=(400, 200), metrics=metrics)
        assert stack.wheel(-1, *view.rect.centre)
        assert view.scroll > 0

    def test_an_empty_stack_ignores_input(self, metrics):
        stack = OverlayStack()
        assert not stack.key('a', (0, 0, 0))
        assert not stack.character('a')
        assert not stack.pointer_moved(1, 1)
        assert not stack.pointer_pressed(1, 1)
        assert not stack.pointer_released(1, 1)
        assert not stack.wheel(1, 1, 1)

    def test_layout_reaches_every_panel(self, metrics):
        stack = OverlayStack()
        first, second = dialog(), dialog()
        stack.push(first)
        stack.push(second)
        stack.layout((640, 480), metrics)
        assert first.rect.width and second.rect.width


class TestContextRouting:
    @pytest.fixture
    def context(self):
        return FakeContext()

    def test_events_reach_the_world_with_no_overlay(self, context):
        event = FakeEvent('keyboard', name='w')
        assert context.ProcessEvent(event) is event
        assert context.dispatched == [event]

    def test_a_modal_overlay_sinks_a_key_it_does_not_want(self, context):
        context.pushOverlay(dialog())
        context.ProcessEvent(FakeEvent('keyboard', name='z'))
        assert context.dispatched == []

    def test_a_sunk_key_is_not_recorded_as_held(self, context):
        """Otherwise the player walks into a wall while typing."""
        context.pushOverlay(dialog())
        context.ProcessEvent(FakeEvent('keyboard', name='w', state=1))
        assert not context.getInputState().held('w')

    def test_opening_an_overlay_forgets_what_was_held(self, context):
        context.ProcessEvent(FakeEvent('keyboard', name='w', state=1))
        assert context.getInputState().held('w')
        context.pushOverlay(dialog())
        assert not context.getInputState().held('w')

    def test_closing_the_last_overlay_starts_from_nothing_held(self, context):
        panel = dialog()
        context.pushOverlay(panel)
        context.ProcessEvent(FakeEvent('keyboard', name='w', state=1))
        panel.close(None)
        assert not context.getInputState().held('w')

    def test_opening_an_overlay_hands_the_pointer_back(self, context):
        context.pushOverlay(dialog())
        assert context.captureSuspended is True

    def test_closing_the_last_overlay_takes_the_pointer_again(self, context):
        panel = dialog()
        context.pushOverlay(panel)
        panel.close(None)
        assert context.captureSuspended is False

    def test_a_click_reaches_the_overlay(self, context):
        panel = dialog()
        fired = []
        panel.find('ok').on_activate = lambda widget: fired.append(widget)
        context.pushOverlay(panel)
        x, y = panel.find('ok').rect.centre
        context.ProcessEvent(FakeEvent('mousebutton', button=0, state=1, pick=(x, y)))
        context.ProcessEvent(FakeEvent('mousebutton', button=0, state=0, pick=(x, y)))
        assert len(fired) == 1
        assert context.dispatched == []

    def test_a_typed_character_reaches_a_field(self, context):
        from OpenGLContext.ui.widgets import TextField
        entry = TextField(name='e', value='')
        panel = Panel(children=[Column(children=[entry])])
        context.pushOverlay(panel)
        panel.focus(entry)
        context.ProcessEvent(FakeEvent('keypress', name='a'))
        assert entry.read() == 'a'

    def test_mouse_move_handlers_are_kept_alive_for_hover(self, context):
        assert not context.hasMouseMoveHandlers()
        context.pushOverlay(dialog())
        assert context.hasMouseMoveHandlers()

    def test_a_modeless_overlay_lets_the_world_keep_moving(self, context):
        context.pushOverlay(dialog(modal=False))
        event = FakeEvent('keyboard', name='w')
        context.ProcessEvent(event)
        assert context.dispatched == [event]

    def test_the_overlay_is_relaid_out_when_the_window_resizes(self, context, metrics):
        panel = dialog()
        context.pushOverlay(panel)
        first = panel.rect
        context.viewport = (400, 300)
        context.layoutOverlays()
        assert panel.rect != first

    def test_pushing_asks_for_a_redraw(self, context):
        before = context.redraws
        context.pushOverlay(dialog())
        assert context.redraws > before

    def test_a_wheel_notch_reaches_the_overlay(self, context):
        from OpenGLContext.ui.scroll import ScrollViewport
        view = ScrollViewport(name='view', flex=1,
                              children=[Label(text='line\n' * 80)])
        panel = Panel(fill=True, children=[view])
        context.pushOverlay(panel)
        context.ProcessEvent(FakeEvent('mousebutton', button=4, state=1,
                                       pick=view.rect.centre))
        assert view.scroll > 0
        assert context.dispatched == []

    def test_the_wheel_release_is_sunk_without_acting(self, context):
        context.pushOverlay(dialog())
        context.ProcessEvent(FakeEvent('mousebutton', button=3, state=0))
        assert context.dispatched == []

    def test_a_key_release_is_sunk_but_not_acted_on(self, context):
        context.pushOverlay(dialog())
        context.ProcessEvent(FakeEvent('keyboard', name='w', state=0))
        assert context.dispatched == []

    def test_an_event_with_no_pick_point_is_ignored(self, context):
        context.pushOverlay(dialog())
        context.ProcessEvent(FakeEvent('mousemove', pick=()))
        context.ProcessEvent(FakeEvent('mousebutton', pick=()))
        assert context.dispatched == []

    def test_an_event_type_the_overlay_knows_nothing_about_is_still_sunk(
            self, context):
        context.pushOverlay(dialog())
        context.ProcessEvent(FakeEvent('mousein'))
        assert context.dispatched == []

    def test_layout_waits_until_there_are_metrics(self, context):
        context.pushOverlay(dialog())
        context.overlayMetrics = lambda: None
        context.overlays.invalidate()
        assert not context.layoutOverlays()

    def test_layout_is_not_repeated_for_the_same_window(self, context):
        panel = context.pushOverlay(dialog())
        assert context.layoutOverlays()
        first = panel.rect
        assert context.layoutOverlays()
        assert panel.rect == first

    def test_nothing_to_lay_out_reports_so(self, context):
        assert not context.layoutOverlays()

    def test_pop_closes_the_top_panel(self, context):
        panel = dialog()
        context.pushOverlay(panel)
        context.popOverlay()
        assert panel.closed
        assert not context.overlays.visible
