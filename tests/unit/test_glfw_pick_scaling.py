"""HiDPI pick-point scaling for the GLFW backend (pure/headless).

GLFW reports the cursor in logical window coordinates while the viewport and
selection buffer are sized in physical framebuffer pixels. On a scaled display
the two differ, so the cursor must be scaled to framebuffer pixels before it
becomes a pick point. These tests mock the glfw size queries; no GL context or
window is created.
"""
import pytest

glfw = pytest.importorskip("glfw")
from OpenGLContext.events import glfwevents


class FakeContext(glfwevents.EventHandlerMixin):
    """Just enough context to drive the GLFW mouse callbacks."""

    currentPass = None

    def __init__(self, fb_size):
        # getViewPort() returns (width, height); callers build the 4-tuple
        # viewport as (0, 0) + getViewPort().
        self._fb_size = fb_size
        self.picked = []

    def getViewPort(self):
        return self._fb_size

    def addPickEvent(self, event):
        self.picked.append(event)

    def triggerPick(self):
        pass


def _mock_sizes(monkeypatch, window_size, fb_size, cursor):
    monkeypatch.setattr(glfwevents.glfw, "get_window_size", lambda w: window_size)
    monkeypatch.setattr(glfwevents.glfw, "get_framebuffer_size", lambda w: fb_size)
    monkeypatch.setattr(glfwevents.glfw, "get_cursor_pos", lambda w: cursor)


def test_cursor_scaled_to_framebuffer_2x(monkeypatch):
    _mock_sizes(monkeypatch, (800, 600), (1600, 1200), (100.0, 50.0))
    ctx = FakeContext((1600, 1200))
    x, y = ctx._cursorToFramebuffer(object(), 100.0, 50.0)
    assert (x, y) == (200.0, 100.0)


def test_pickpoint_hidpi_lands_on_rendered_pixel(monkeypatch):
    """A 2x display: click at logical (100,50) -> framebuffer (200,100),
    y-flipped against framebuffer height (1200) -> pickPoint (200, 1100)."""
    _mock_sizes(monkeypatch, (800, 600), (1600, 1200), (100.0, 50.0))
    ctx = FakeContext((1600, 1200))
    ctx.glfwOnMouseButton(object(), glfw.MOUSE_BUTTON_LEFT, glfw.PRESS, 0)
    ev = ctx.picked[-1]
    assert ev.pickPoint == (200, 1200 - 100)


def test_pickpoint_unscaled_display_unchanged(monkeypatch):
    """At 1x scale the framebuffer equals the window, so behaviour is the old
    (correct) y-flip with no horizontal shift -- guards against regressing the
    common non-HiDPI case."""
    _mock_sizes(monkeypatch, (800, 600), (800, 600), (100.0, 50.0))
    ctx = FakeContext((800, 600))
    ctx.glfwOnMouseButton(object(), glfw.MOUSE_BUTTON_LEFT, glfw.PRESS, 0)
    ev = ctx.picked[-1]
    assert ev.pickPoint == (100, 600 - 50)


def test_move_event_scaled(monkeypatch):
    _mock_sizes(monkeypatch, (800, 600), (1600, 1200), (0.0, 0.0))
    ctx = FakeContext((1600, 1200))
    ctx.glfwOnCursorPos(object(), 400.0, 300.0)
    ev = ctx.picked[-1]
    # (400,300) logical -> (800,600) framebuffer -> y-flip 1200-600 = 600
    assert ev.pickPoint == (800, 1200 - 600)


def test_zero_window_size_does_not_divide(monkeypatch):
    """A degenerate/minimized window (0 size) must not raise ZeroDivisionError."""
    _mock_sizes(monkeypatch, (0, 0), (0, 0), (10.0, 10.0))
    ctx = FakeContext((0, 0))
    x, y = ctx._cursorToFramebuffer(object(), 10.0, 10.0)
    assert (x, y) == (10.0, 10.0)
