"""Shared display / offscreen-GL availability check for the test suite.

Single source of truth for "can OpenGL render here?", used by the pytest
collection hook and the subprocess script runners. Copy-pasted variants of this
check drifted apart -- one omitted the offscreen-platform case -- which made the
visual suite silently skip (and read green) on a headless runner configured with
an offscreen GL platform. Import ``display_available`` instead of re-implementing.
"""
import os
from collections.abc import Mapping

# Offscreen PyOpenGL platforms that render without an X/Wayland display, so the
# visual suite can run on a headless CI runner instead of skipping.
OFFSCREEN_GL_PLATFORMS = ('egl', 'osmesa')


def display_available(env: Mapping[str, str] | None = None) -> bool:
    """Return True if OpenGL can render: a windowed display OR an offscreen platform.

    A headless runner has no ``DISPLAY``/``WAYLAND_DISPLAY`` but can still render
    through an offscreen platform (EGL/OSMesa) selected via ``PYOPENGL_PLATFORM``.
    Counting that as available is what stops the visual suite from silently
    skipping and reporting green without having rendered anything.

    ``env`` defaults to ``os.environ``; pass a dict to test without mutating it.
    """
    env = os.environ if env is None else env
    if env.get('DISPLAY') or env.get('WAYLAND_DISPLAY'):
        return True
    return env.get('PYOPENGL_PLATFORM', '').lower() in OFFSCREEN_GL_PLATFORMS
