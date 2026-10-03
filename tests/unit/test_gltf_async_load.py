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
from OpenGLContext.loaders.sceneloader import SceneLoader


def make_ctx():
    """A bare viewer instance with the loader a context would hold (no GL)."""
    ctx = view.TestContext.__new__(view.TestContext)
    ctx.sceneLoader = SceneLoader(owner=ctx)
    ctx.sceneLoaded = False
    ctx._screenshotPending = False
    ctx.overlayText = ''
    ctx.overlayError = False
    ctx.redraws = 0
    ctx.triggerRedraw = lambda *_a: setattr(ctx, 'redraws', ctx.redraws + 1)
    return ctx


def deliver(ctx, timeout=5.0):
    """Poll the loader until a request is delivered; how many were."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        delivered = ctx.sceneLoader.poll()
        if delivered:
            return delivered
        time.sleep(0.005)
    return 0


def test_request_shows_loading_overlay_immediately():
    """The overlay flips to the loading label the instant a load is requested, so the
    window shows progress before the download finishes."""
    ctx = make_ctx()
    ctx.applyLoadedScene = lambda scene: None
    ctx.requestScene(lambda: 'SCENE', 'Loading Foo ...')
    assert ctx.overlayText == 'Loading Foo ...'
    assert ctx.overlayError is False
    assert ctx.redraws >= 1
    assert deliver(ctx)


def test_background_load_applied_on_poll():
    """A completed background load is applied on the render thread by the poll."""
    ctx = make_ctx()
    applied = []
    ctx.applyLoadedScene = lambda scene: applied.append(scene)
    ctx.requestScene(lambda: 'SCENE', 'Loading ...')
    assert deliver(ctx) == 1
    assert applied == ['SCENE']
    assert ctx.sceneLoader.loading is False
    # a second poll with nothing pending is a no-op
    assert ctx.sceneLoader.poll() == 0


def test_load_failure_routes_to_apply_failed():
    """A producer that raises does not kill the worker; the error surfaces via the
    failure overlay rather than crashing the loop."""
    ctx = make_ctx()

    def boom():
        raise ValueError("unreachable model")

    ctx.requestScene(boom, 'Loading ...')
    assert deliver(ctx) == 1
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

    ctx.requestScene(slow, 'old')          # blocks on release
    ctx.requestScene(lambda: 'NEW', 'new')  # cancels it
    assert deliver(ctx) == 1
    assert applied == ['NEW']
    # let the stale worker finish; its result must not be delivered
    release.set()
    time.sleep(0.2)
    assert ctx.sceneLoader.poll() == 0
    assert applied == ['NEW']


def test_request_screenshot_queues_capture():
    """The screenshot key only sets a flag + asks for a redraw; the actual grab
    happens later in presentFrame (before the buffer swap)."""
    ctx = make_ctx()
    ctx.requestScreenshot()
    assert ctx._screenshotPending is True
    assert ctx.redraws >= 1


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
