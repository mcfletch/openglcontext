"""Async scene-loading + screenshot logic for the glTF viewer/browser.

The download/decode of a model runs off the render thread; the result is handed back
and applied on the render thread (where GL uploads must happen). These tests exercise
that handoff -- request, poll, supersession, failure -- and the screenshot filename,
all without a GL context (the methods under test touch no GL themselves).
"""
import os
import re
import threading
import time

import pytest

from OpenGLContext.bin import gltf_view


def make_ctx():
    """A bare viewer instance with just the async-load state wired up (no GL)."""
    ctx = gltf_view.TestContext.__new__(gltf_view.TestContext)
    ctx._load_lock = threading.Lock()
    ctx._pending = None
    ctx._load_token = 0
    ctx._loading = False
    ctx._scene_loaded = False
    ctx._screenshot_pending = False
    ctx.overlay_text = ''
    ctx.overlay_error = False
    ctx.redraws = 0
    ctx.triggerRedraw = lambda *a: setattr(ctx, 'redraws', ctx.redraws + 1)
    return ctx


def wait_for_pending(ctx, timeout=5.0):
    """Block until a background load has posted its result (or time out)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with ctx._load_lock:
            if ctx._pending is not None:
                return True
        time.sleep(0.005)
    return False


def test_request_shows_loading_overlay_immediately():
    """The overlay flips to the loading label the instant a load is requested, so the
    window shows progress before the download finishes."""
    ctx = make_ctx()
    ctx._request_scene(lambda: 'SCENE', 'Loading Foo ...')
    assert ctx.overlay_text == 'Loading Foo ...'
    assert ctx.overlay_error is False
    assert ctx.redraws >= 1
    assert wait_for_pending(ctx)


def test_background_load_applied_on_poll():
    """A completed background load is applied on the render thread by the poll."""
    ctx = make_ctx()
    applied = []
    ctx._apply_loaded = lambda scene: applied.append(scene)
    ctx._request_scene(lambda: 'SCENE', 'Loading ...')
    assert wait_for_pending(ctx)
    assert ctx._poll_pending_scene() is True
    assert applied == ['SCENE']
    assert ctx._loading is False
    # a second poll with nothing pending is a no-op
    assert ctx._poll_pending_scene() is False


def test_load_failure_routes_to_apply_failed():
    """A producer that raises does not kill the worker; the error surfaces via the
    failure overlay rather than crashing the loop."""
    ctx = make_ctx()

    def boom():
        raise ValueError("unreachable model")

    ctx._request_scene(boom, 'Loading ...')
    assert wait_for_pending(ctx)
    assert ctx._poll_pending_scene() is True
    assert ctx.overlay_error is True
    assert 'unreachable model' in ctx.overlay_text


def test_superseded_load_is_dropped():
    """Requesting a second model while the first is still downloading discards the
    first's result (the user asked for the newer one)."""
    ctx = make_ctx()
    applied = []
    ctx._apply_loaded = lambda scene: applied.append(scene)
    release = threading.Event()

    def slow():
        release.wait(5)
        return 'OLD'

    ctx._request_scene(slow, 'old')          # token 1, blocks on release
    ctx._request_scene(lambda: 'NEW', 'new')  # token 2, supersedes it
    assert wait_for_pending(ctx)
    assert ctx._poll_pending_scene() is True
    assert applied == ['NEW']
    # let the stale worker finish; its result must not be posted
    release.set()
    time.sleep(0.2)
    with ctx._load_lock:
        assert ctx._pending is None


def test_request_screenshot_queues_capture():
    """The screenshot key only sets a flag + asks for a redraw; the actual grab
    happens later in SwapBuffers (before the buffer swap)."""
    ctx = make_ctx()
    ctx._request_screenshot()
    assert ctx._screenshot_pending is True
    assert ctx.redraws >= 1


def test_screenshot_path_is_iso_dated_in_cwd(tmp_path, monkeypatch):
    """The saved file is an iso-dated PNG in the current working directory."""
    ctx = make_ctx()
    import OpenGLContext.capture as capmod
    saved = []
    monkeypatch.setattr(capmod, 'capture_to_png',
                        lambda path, **kw: saved.append(path) or True)
    monkeypatch.chdir(tmp_path)
    ctx._save_screenshot()
    assert len(saved) == 1
    assert os.path.dirname(saved[0]) == str(tmp_path)
    name = os.path.basename(saved[0])
    assert re.match(r'gltf-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.png$', name), name


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
