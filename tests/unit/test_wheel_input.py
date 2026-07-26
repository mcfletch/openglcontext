"""A wheel notch has to reach the widget under the pointer.

A notch is spelled as a press and release of a button no physical mouse has --
``WHEEL_UP`` and ``WHEEL_DOWN``, the X11 numbering used throughout
OpenGLContext -- so it travels the same route as a click: a pick event carrying
a pick point, then :meth:`OverlayMixin.overlaySinks`, which turns the pair into
one call on the panel under the pointer.

Every backend has to produce that spelling, and they do not agree on how the
wheel arrives.  GLUT reports it as those buttons already.  GLFW has a callback
of its own reporting offsets rather than buttons, and on a touchpad reports
fractions of one, where a notch is the sum of a stream of them.
"""

import pytest

from OpenGLContext.context import Context
from OpenGLContext.events import glutevents
from OpenGLContext.events.inputstate import InputState
from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.overlay import OverlayMixin
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.scroll import ScrollViewport
from OpenGLContext.ui.widgets import Label

glfw = pytest.importorskip('glfw')
from OpenGLContext.events import glfwevents        # noqa: E402  (needs glfw)

VIEWPORT = (800, 600)


def mock_glfw(monkeypatch, cursor=(100.0, 100.0), window=VIEWPORT,
              framebuffer=VIEWPORT):
    monkeypatch.setattr(glfwevents.glfw, 'get_window_size', lambda w: window)
    monkeypatch.setattr(glfwevents.glfw, 'get_framebuffer_size',
                        lambda w: framebuffer)
    monkeypatch.setattr(glfwevents.glfw, 'get_cursor_pos', lambda w: cursor)


class GLFWRecorder(glfwevents.EventHandlerMixin):
    """Enough of a context to drive the GLFW callbacks and keep the events."""

    currentPass = None

    def __init__(self):
        self.picked = []

    def getViewPort(self):
        return VIEWPORT

    def addPickEvent(self, event):
        self.picked.append(event)

    def triggerPick(self):
        pass

    def buttons(self):
        """The (button, state) pairs the backend produced, in order."""
        return [(event.button, event.state) for event in self.picked]


@pytest.fixture
def recorder(monkeypatch):
    mock_glfw(monkeypatch)
    return GLFWRecorder()


class TestTheGLFWBackendReportsNotches:
    """GLFW's scroll callback has to become the buttons the rest expects."""

    def test_the_scroll_callback_is_registered(self, monkeypatch):
        """Nothing else can be right if the platform is never asked."""
        from OpenGLContext import glfwcontext
        registered = {}
        for name in ('key', 'char', 'mouse_button', 'cursor_pos',
                     'framebuffer_size', 'window_close', 'window_focus',
                     'scroll'):
            monkeypatch.setattr(
                glfwcontext.glfw, 'set_%s_callback' % name,
                lambda window, callback, name=name: registered.__setitem__(
                    name, callback))
        context = glfwcontext.GLFWContext.__new__(glfwcontext.GLFWContext)
        context.window = object()
        context.setupCallbacks()
        assert 'scroll' in registered

    def test_the_registered_callback_reaches_the_handler(self, monkeypatch):
        from OpenGLContext import glfwcontext
        seen = []
        monkeypatch.setattr(
            glfwcontext.glfw, 'set_scroll_callback',
            lambda window, callback: seen.append(callback))
        for name in ('key', 'char', 'mouse_button', 'cursor_pos',
                     'framebuffer_size', 'window_close', 'window_focus'):
            monkeypatch.setattr(glfwcontext.glfw, 'set_%s_callback' % name,
                                lambda window, callback: None)
        context = glfwcontext.GLFWContext.__new__(glfwcontext.GLFWContext)
        context.window = object()
        context.setupCallbacks()
        forwarded = []
        context.glfwOnScroll = lambda *arguments: forwarded.append(arguments)
        seen[0](context.window, 0.0, 1.0)
        assert forwarded == [(context.window, 0.0, 1.0)]

    def test_scrolling_up_is_a_press_and_release_of_the_up_button(
            self, recorder):
        recorder.glfwOnScroll(object(), 0.0, 1.0)
        assert recorder.buttons() == [(WHEEL_UP, 1), (WHEEL_UP, 0)]

    def test_scrolling_down_is_the_down_button(self, recorder):
        recorder.glfwOnScroll(object(), 0.0, -1.0)
        assert recorder.buttons() == [(WHEEL_DOWN, 1), (WHEEL_DOWN, 0)]

    def test_a_notch_carries_the_pointer_as_its_pick_point(self, monkeypatch):
        """The widget scrolled is the one under the pointer, so it must know."""
        mock_glfw(monkeypatch, cursor=(120.0, 40.0))
        recorder = GLFWRecorder()
        recorder.glfwOnScroll(object(), 0.0, 1.0)
        assert recorder.picked[0].pickPoint == (120, 600 - 40)

    def test_the_pick_point_is_in_framebuffer_pixels(self, monkeypatch):
        """As for a click: a scaled display reports the cursor in logical ones."""
        mock_glfw(monkeypatch, cursor=(100.0, 50.0), window=(800, 600),
                  framebuffer=(1600, 1200))
        recorder = GLFWRecorder()
        recorder.getViewPort = lambda: (1600, 1200)
        recorder.glfwOnScroll(object(), 0.0, -1.0)
        assert recorder.picked[0].pickPoint == (200, 1200 - 100)

    def test_several_lines_at_once_are_several_notches(self, recorder):
        recorder.glfwOnScroll(object(), 0.0, 3.0)
        assert recorder.buttons() == [(WHEEL_UP, 1), (WHEEL_UP, 0)] * 3

    def test_a_horizontal_scroll_alone_does_nothing(self, recorder):
        """There is nothing in the interface that scrolls sideways."""
        recorder.glfwOnScroll(object(), 1.0, 0.0)
        assert recorder.buttons() == []


class TestATouchpadScrollsSmoothly:
    """A touchpad reports a fraction of a notch at a time, not a detent.

    Summed, so a slow drag still scrolls once it has asked for a whole notch
    and a fast one scrolls no further than it was pushed.
    """

    def test_a_fraction_of_a_notch_does_not_scroll_yet(self, recorder):
        recorder.glfwOnScroll(object(), 0.0, 0.3)
        assert recorder.buttons() == []

    def test_fractions_add_up_to_a_notch(self, recorder):
        for _ in range(4):
            recorder.glfwOnScroll(object(), 0.0, 0.3)
        assert recorder.buttons() == [(WHEEL_UP, 1), (WHEEL_UP, 0)]

    def test_the_remainder_is_kept_rather_than_dropped(self, recorder):
        """Ten tenths are one notch however they were delivered."""
        for _ in range(10):
            recorder.glfwOnScroll(object(), 0.0, 0.1)
        assert recorder.buttons() == [(WHEEL_UP, 1), (WHEEL_UP, 0)]

    def test_fractions_downward_scroll_downward(self, recorder):
        for _ in range(4):
            recorder.glfwOnScroll(object(), 0.0, -0.3)
        assert recorder.buttons() == [(WHEEL_DOWN, 1), (WHEEL_DOWN, 0)]

    def test_turning_back_does_not_bank_the_remainder(self, recorder):
        """Otherwise a jitter over the pad scrolls the way it is not moving."""
        for _ in range(3):
            recorder.glfwOnScroll(object(), 0.0, 0.3)
        for _ in range(3):
            recorder.glfwOnScroll(object(), 0.0, -0.3)
        assert recorder.buttons() == []


class TestTheGLUTBackendReportsNotches:
    """GLUT names the wheel with the buttons already; it must keep them."""

    class Context:
        currentPass = None

        def getViewPort(self):
            return VIEWPORT

    def event(self, button, state):
        return glutevents.GLUTMouseButtonEvent(self.Context(), button, state,
                                               10, 10)

    def test_a_notch_keeps_its_button_number(self):
        """Collapsed to -1 it is not a notch any more, it is a stray click."""
        assert self.event(WHEEL_UP, 0).button == WHEEL_UP
        assert self.event(WHEEL_DOWN, 0).button == WHEEL_DOWN

    def test_a_notch_is_not_a_held_button(self):
        """No wheel is ever down, so a drag started by one would never end."""
        before = list(glutevents.GLUTXEvent.CURRENTBUTTONSTATES)
        self.event(WHEEL_UP, 0)
        assert glutevents.GLUTXEvent.CURRENTBUTTONSTATES == before

    def test_a_button_that_is_neither_is_still_refused(self, caplog):
        event = self.event(11, 0)
        assert event.button == -1
        assert 'Unrecognized button' in caplog.text


class TestThePygameBackendReportsNotches:
    """Pygame numbers every button one higher, the wheel included."""

    pygame = pytest.importorskip('pygame')

    @pytest.fixture(autouse=True)
    def display(self, monkeypatch):
        """Modifier state comes from SDL, which wants a video driver first."""
        monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
        self.pygame.display.init()
        yield
        self.pygame.display.quit()

    class Context:
        currentPass = None

        def getViewPort(self):
            return VIEWPORT

    class Event:
        def __init__(self, button):
            self.button = button
            self.pos = (10, 10)

    def event(self, button, state=1):
        from OpenGLContext.events import pygameevents
        return pygameevents.PygameMouseButtonEvent(
            self.Context(), self.Event(button), state)

    def test_a_notch_lands_on_the_wheel_buttons(self):
        assert self.event(4).button == WHEEL_UP
        assert self.event(5).button == WHEEL_DOWN

    def test_a_notch_is_not_a_held_button(self):
        from OpenGLContext.events import pygameevents
        before = list(pygameevents.PygameXEvent.CURRENTBUTTONSTATES)
        self.event(4)
        assert pygameevents.PygameXEvent.CURRENTBUTTONSTATES == before

    def test_a_notch_is_not_worth_a_warning(self, caplog):
        """One per notch would bury a log under an ordinary scroll."""
        self.event(4)
        self.event(5)
        assert 'Unrecognised button' not in caplog.text

    def test_a_button_that_is_neither_is_still_reported(self, caplog):
        self.event(11)
        assert 'Unrecognised button' in caplog.text


class TestEveryNotchSurvivesTheFrame:
    """The pick queue keeps one event per button and state, and must not here.

    Two clicks of one button in a frame are the same question asked twice and
    the last answer is the only one worth having.  Two notches of the wheel are
    two lines, and a frame that arrives with three notches in it -- an ordinary
    flick, since scrolling is reported far faster than frames are drawn -- has
    to scroll three.
    """

    class Queue:
        """The context's own pick queue, with nothing else attached to it."""

        contextDefinition = None
        addPickEvent = Context.addPickEvent

        def __init__(self):
            self.pickEvents = {}

    def notch(self, queue, button=WHEEL_UP):
        queue.addPickEvent(glfwevents.GLFWMouseButtonEvent(
            _Viewport(), button, 1, 10, 10))

    def test_three_notches_in_one_frame_are_three_notches(self):
        queue = self.Queue()
        for _ in range(3):
            self.notch(queue)
        assert len(queue.pickEvents) == 3

    def test_a_click_repeated_in_one_frame_is_still_one_click(self):
        """The wheel is the exception; nothing else changes about the queue."""
        queue = self.Queue()
        for _ in range(3):
            self.notch(queue, button=0)
        assert len(queue.pickEvents) == 1

    def test_a_notch_up_is_not_confused_with_a_notch_down(self):
        queue = self.Queue()
        self.notch(queue, WHEEL_UP)
        self.notch(queue, WHEEL_DOWN)
        assert len(queue.pickEvents) == 2


class _Viewport:
    """A stand-in context for building an event: only the viewport is read."""

    currentPass = None

    def getViewPort(self):
        return VIEWPORT


class WheelContext(OverlayMixin, glfwevents.EventHandlerMixin):
    """A context wired as the real one is: GLFW's events into an overlay.

    ``addPickEvent`` dispatches at once, standing in for the selection pass,
    which is what delivers a pick event to ``ProcessEvent`` in a running frame.
    """

    currentPass = None

    def __init__(self):
        self.inputState = InputState()
        self.dispatched = []

    def getViewPort(self):
        return VIEWPORT

    def getInputState(self):
        return self.inputState

    def triggerRedraw(self, force=0):
        pass

    def suspendPointerCapture(self, suspend):
        pass

    def hasMouseMoveHandlers(self):
        return False

    def overlayMetrics(self):
        return FontMetrics(8, 16, 2)

    def addPickEvent(self, event):
        self.ProcessEvent(event)

    def triggerPick(self):
        pass

    def ProcessEvent(self, event):
        handled = self.overlaySinks(event)
        if not handled:
            self.dispatched.append(event)
        return event


class TestTheWheelScrollsThePanelUnderIt:
    """The whole path, from the platform callback to the scrolled content."""

    @pytest.fixture
    def context(self, monkeypatch):
        mock_glfw(monkeypatch, cursor=(400.0, 300.0))
        return WheelContext()

    @pytest.fixture
    def view(self, context):
        view = ScrollViewport(name='view', flex=1,
                              children=[Label(text='line\n' * 80)])
        context.pushOverlay(Panel(fill=True, children=[view]))
        return view

    def test_a_notch_down_scrolls_the_content_down(self, context, view):
        context.glfwOnScroll(object(), 0.0, -1.0)
        assert view.scroll > 0

    def test_a_notch_up_scrolls_it_back(self, context, view):
        context.glfwOnScroll(object(), 0.0, -3.0)
        scrolled = view.scroll
        context.glfwOnScroll(object(), 0.0, 1.0)
        assert 0 < view.scroll < scrolled

    def test_the_world_never_sees_the_notch(self, context, view):
        """A wheel the interface used must not also turn the player's view."""
        context.glfwOnScroll(object(), 0.0, -1.0)
        assert context.dispatched == []

    def test_a_notch_does_not_press_the_widget_under_the_pointer(
            self, context):
        """A notch is not a click, whatever button number carries it."""
        pressed = []
        from OpenGLContext.ui.widgets import Button
        button = Button(text='Ok', name='ok')
        button.on_activate = lambda widget: pressed.append(widget)
        context.pushOverlay(Panel(fill=True, children=[button]))
        context.glfwOnScroll(object(), 0.0, -1.0)
        assert pressed == []
