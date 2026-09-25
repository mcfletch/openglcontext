"""A tooltip in a real window that draws only when something happens.

The GLFW main loop draws a frame when one is asked for and otherwise only asks
the event cascade whether anything changed. The pointer coming to rest on a
control asks for one frame, before the pause a tip waits for is up; these
drive the loop itself in a hidden window and read which trees it drew.
"""
import time

import pytest

glfw = pytest.importorskip("glfw")

from OpenGLContext.events.mouseevents import MouseMoveEvent
from OpenGLContext.looptrace import LoopTrace
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.ui.layout import Column
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.tooltip import TOOLTIP_PAUSE, Tooltip
from OpenGLContext.ui.widgets import Button
from tests.unit.glrender import base_env
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.ui.overlay import OverlayMixin


@pytest.fixture
def window(monkeypatch):
    base_env(monkeypatch)
    if not glfw.init():
        pytest.skip('glfw init failed')
    from OpenGLContext import testingcontext

    drawn = []

    class Tipped(OverlayMixin, testingcontext.getInteractive()):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[])

        def screenTrees(self, metrics, now=None):
            trees = super().screenTrees(metrics, now)
            drawn.append(list(trees))
            return trees

    reason = profile_unavailable('core')
    if reason:
        pytest.skip(reason)
    context = Tipped()
    context.deferRedraw = True
    try:
        yield context, drawn
    finally:
        context.releaseWindow()


def _rest_on_a_button(context):
    button = Button(text='Ok', name='ok')
    button.tooltip = 'Say yes'
    panel = Panel(modal=False, children=[Column(children=[button])])
    context.overlays.push(panel)
    context.OnDraw(force=1)
    event = MouseMoveEvent()
    event.pickPoint = button.rect.centre
    event.modifiers = (0, 0, 0)
    context.ProcessEvent(event)
    return button


def test_the_tip_is_drawn_once_the_pointer_has_rested(window):
    context, drawn = window
    _rest_on_a_button(context)
    trace = LoopTrace()
    rendered = True
    deadline = time.monotonic() + TOOLTIP_PAUSE * 2.5
    while time.monotonic() < deadline:
        rendered = context._loopIteration(trace, rendered)
        if drawn and any(isinstance(tree, Tooltip) for tree in drawn[-1]):
            break
    assert drawn and any(isinstance(tree, Tooltip) for tree in drawn[-1]), \
        '%d frames drawn, none with the tip' % len(drawn)


def test_a_window_with_nothing_pending_stays_idle(window):
    """Once the tip is up the loop goes back to drawing nothing."""
    context, drawn = window
    _rest_on_a_button(context)
    trace = LoopTrace()
    rendered = True
    deadline = time.monotonic() + TOOLTIP_PAUSE * 2.5
    while time.monotonic() < deadline:
        rendered = context._loopIteration(trace, rendered)
    settled = len(drawn)
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        rendered = context._loopIteration(trace, rendered)
    assert len(drawn) == settled
