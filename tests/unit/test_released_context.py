"""A context whose window has been released draws nothing.

After ``releaseWindow`` the window system has no window to make current, so
a frame asked of the context -- by a late load finishing and asking every
context to redraw, say -- would be drawn into whichever GL context happens
to be current. ``OnDraw`` answers 0 instead.
"""
from types import SimpleNamespace

from OpenGLContext.windowsystem.base import WindowSystem


def test_a_window_system_is_open_while_it_has_a_window():
    assert WindowSystem.isOpen(SimpleNamespace(window=object()))
    assert not WindowSystem.isOpen(SimpleNamespace(window=None))


def test_a_released_context_draws_nothing(gl_context):
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    with scene_context([]) as context:
        context.OnDraw(force=1)
    drawn = []
    context.renderPasses = lambda found: drawn.append(found) or True
    assert context.OnDraw(force=1) == 0
    assert drawn == []
