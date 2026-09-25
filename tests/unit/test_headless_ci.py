"""Headless-CI viability and timing configurability.

4.31: the visual suite must not silently skip (green-because-skipped) on a
headless runner that uses an offscreen GL platform (EGL / OSMesa) instead of an
X DISPLAY. 4.33: the capture delay must be tunable so CI can be generous without
editing source.
"""

import argparse
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
    """A runner that names neither a display nor an offscreen platform.

    Said of a host whose display *is* named in the environment: DISPLAY and
    WAYLAND_DISPLAY are X11's and Wayland's. Windows and macOS reach their
    window server without either, so there the absence says nothing.
    """
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.delenv('PYOPENGL_PLATFORM', raising=False)
    assert tas._check_display_available(platform='linux') is False


def test_capture_delay_env_override(monkeypatch):
    """OPENGLCONTEXT_CAPTURE_DELAY tunes the stabilization wait (4.33).

    Set after the module is imported, as a harness sets it for the program it
    is about to run, and it is still the delay a regression parser offers.
    """
    from OpenGLContext.testing import framebuffer_comparison as fbc

    monkeypatch.setenv('OPENGLCONTEXT_CAPTURE_DELAY', '2.5')
    parser = fbc.AutomatedRegressionContext.add_regression_arguments(
        argparse.ArgumentParser())
    assert parser.parse_args([]).capture_delay == 2.5


def test_capture_delay_defaults_to_half_a_second(monkeypatch):
    from OpenGLContext.testing import framebuffer_comparison as fbc

    monkeypatch.delenv('OPENGLCONTEXT_CAPTURE_DELAY', raising=False)
    parser = fbc.AutomatedRegressionContext.add_regression_arguments(
        argparse.ArgumentParser())
    assert parser.parse_args([]).capture_delay == fbc.DEFAULT_CAPTURE_DELAY == 0.5
