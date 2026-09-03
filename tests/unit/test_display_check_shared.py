"""Regression: one shared display/offscreen-GL check, no drifted copies.

`_check_display_available` was copy-pasted into several test files and the visual
regression copy drifted -- it checked only DISPLAY/WAYLAND_DISPLAY and omitted the
EGL/OSMesa offscreen detection the others have. On a headless runner with
PYOPENGL_PLATFORM=egl the visual regressions therefore silently skipped and read
as green. All copies now route through OpenGLContext.testing.display.
"""
import sys
from pathlib import Path

from OpenGLContext.testing.paths import tests_root

# test_visual_regression sits beside this file (tests/unit/); test_all_scripts
# stays in the tests root -- both must be importable.
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(tests_root(__file__)))


class TestSharedHelper:
    def test_windowed_display_is_available(self):
        from OpenGLContext.testing.display import display_available
        assert display_available({'DISPLAY': ':0'}) is True
        assert display_available({'WAYLAND_DISPLAY': 'wayland-0'}) is True

    def test_offscreen_platform_is_available(self):
        from OpenGLContext.testing.display import display_available
        assert display_available({'PYOPENGL_PLATFORM': 'egl'}) is True
        assert display_available({'PYOPENGL_PLATFORM': 'osmesa'}) is True

    def test_no_display_no_offscreen_is_unavailable(self):
        from OpenGLContext.testing.display import display_available
        assert display_available({}, platform='linux') is False
        assert display_available({'PYOPENGL_PLATFORM': 'glx'}, platform='linux') is False

    def test_windows_and_macos_always_have_one(self):
        """Neither names its display in the environment.

        DISPLAY and WAYLAND_DISPLAY are X11 and Wayland; a Windows or macOS
        session reaches its window server without them, so asking for those
        variables there answers "headless" for a machine with a screen -- and
        the whole visual suite skips and reads green.
        """
        from OpenGLContext.testing.display import display_available
        assert display_available({}, platform='win32') is True
        assert display_available({}, platform='darwin') is True


class TestCopiesAgreeOnOffscreen:
    """The exact bug: the visual-regression copy must count EGL as a usable
    render target, like the other copies, so it doesn't false-skip on headless CI."""

    def test_visual_regression_counts_egl(self, monkeypatch):
        import test_visual_regression as tvr
        monkeypatch.delenv('DISPLAY', raising=False)
        monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
        monkeypatch.setenv('PYOPENGL_PLATFORM', 'egl')
        assert tvr._check_display_available() is True

    def test_all_scripts_counts_egl(self, monkeypatch):
        import test_all_scripts as tas
        monkeypatch.delenv('DISPLAY', raising=False)
        monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
        monkeypatch.setenv('PYOPENGL_PLATFORM', 'egl')
        assert tas._check_display_available() is True
