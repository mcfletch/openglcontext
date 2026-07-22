"""Headless-CI viability and timing configurability.

4.31: the visual suite must not silently skip (green-because-skipped) on a
headless runner that uses an offscreen GL platform (EGL / OSMesa) instead of an
X DISPLAY. 4.33: the capture delay must be tunable so CI can be generous without
editing source.
"""

import importlib
import sys
from pathlib import Path

from OpenGLContext.testing.paths import tests_root

# test_all_scripts stays in the tests root (it runs the demo scripts there).
sys.path.insert(0, str(tests_root(__file__)))
import test_all_scripts as tas


def test_display_detected_from_x11(monkeypatch):
    monkeypatch.setenv('DISPLAY', ':0')
    monkeypatch.delenv('PYOPENGL_PLATFORM', raising=False)
    assert tas._check_display_available() is True


def test_headless_egl_counts_as_display(monkeypatch):
    """An offscreen EGL platform is a usable render target, not a skip (4.31)."""
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.setenv('PYOPENGL_PLATFORM', 'egl')
    assert tas._check_display_available() is True


def test_no_display_no_offscreen_is_skip(monkeypatch):
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.delenv('PYOPENGL_PLATFORM', raising=False)
    assert tas._check_display_available() is False


def test_capture_delay_env_override(monkeypatch):
    """OPENGLCONTEXT_CAPTURE_DELAY tunes the stabilization wait (4.33)."""
    monkeypatch.setenv('OPENGLCONTEXT_CAPTURE_DELAY', '2.5')
    import OpenGLContext.testing.framebuffer_comparison as fbc
    importlib.reload(fbc)
    try:
        assert fbc.DEFAULT_CAPTURE_DELAY == 2.5
    finally:
        monkeypatch.delenv('OPENGLCONTEXT_CAPTURE_DELAY', raising=False)
        importlib.reload(fbc)
