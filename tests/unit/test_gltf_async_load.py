"""Async scene-loading + screenshot logic for the glTF viewer/browser.

The download/decode of a model runs off the render thread; the result is handed back
and applied on the render thread (where GL uploads must happen). These tests exercise
that handoff -- request, poll, supersession, failure -- and the screenshot filename,
all without a GL context (the methods under test touch no GL themselves).
"""
import threading
import time

import pytest

from OpenGLContext.bin import view


def make_ctx():
    """A bare viewer instance with just the async-load state wired up (no GL)."""
    ctx = view.TestContext.__new__(view.TestContext)
    ctx._loadLock = threading.Lock()
    ctx._pendingScene = None
    ctx._loadToken = 0
    ctx.sceneLoading = False
    ctx.sceneLoaded = False
    ctx._screenshotPending = False
    ctx.overlayText = ''
    ctx.overlayError = False
    ctx.redraws = 0
    ctx.triggerRedraw = lambda *a: setattr(ctx, 'redraws', ctx.redraws + 1)
    return ctx


def wait_for_pending(ctx, timeout=5.0):
    """Block until a background load has posted its result (or time out)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with ctx._loadLock:
            if ctx._pendingScene is not None:
                return True
        time.sleep(0.005)
    return False


def test_request_shows_loading_overlay_immediately():
    """The overlay flips to the loading label the instant a load is requested, so the
    window shows progress before the download finishes."""
    ctx = make_ctx()
    ctx.requestScene(lambda: 'SCENE', 'Loading Foo ...')
    assert ctx.overlayText == 'Loading Foo ...'
    assert ctx.overlayError is False
    assert ctx.redraws >= 1
    assert wait_for_pending(ctx)


def test_background_load_applied_on_poll():
    """A completed background load is applied on the render thread by the poll."""
    ctx = make_ctx()
    applied = []
    ctx.applyLoadedScene = lambda scene: applied.append(scene)
    ctx.requestScene(lambda: 'SCENE', 'Loading ...')
    assert wait_for_pending(ctx)
    assert ctx.pollPendingScene() is True
    assert applied == ['SCENE']
    assert ctx.sceneLoading is False
    # a second poll with nothing pending is a no-op
    assert ctx.pollPendingScene() is False


def test_load_failure_routes_to_apply_failed():
    """A producer that raises does not kill the worker; the error surfaces via the
    failure overlay rather than crashing the loop."""
    ctx = make_ctx()

    def boom():
        raise ValueError("unreachable model")

    ctx.requestScene(boom, 'Loading ...')
    assert wait_for_pending(ctx)
    assert ctx.pollPendingScene() is True
    assert ctx.overlayError is True
    assert 'unreachable model' in ctx.overlayText


def test_superseded_load_is_dropped():
    """Requesting a second model while the first is still downloading discards the
    first's result (the user asked for the newer one)."""
    ctx = make_ctx()
    applied = []
    ctx.applyLoadedScene = lambda scene: applied.append(scene)
    release = threading.Event()

    def slow():
        release.wait(5)
        return 'OLD'

    ctx.requestScene(slow, 'old')          # token 1, blocks on release
    ctx.requestScene(lambda: 'NEW', 'new')  # token 2, supersedes it
    assert wait_for_pending(ctx)
    assert ctx.pollPendingScene() is True
    assert applied == ['NEW']
    # let the stale worker finish; its result must not be posted
    release.set()
    time.sleep(0.2)
    with ctx._loadLock:
        assert ctx._pendingScene is None


def test_request_screenshot_queues_capture():
    """The screenshot key only sets a flag + asks for a redraw; the actual grab
    happens later in presentFrame (before the buffer swap)."""
    ctx = make_ctx()
    ctx.requestScreenshot()
    assert ctx._screenshotPending is True
    assert ctx.redraws >= 1


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
