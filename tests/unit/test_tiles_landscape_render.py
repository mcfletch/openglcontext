"""Offscreen render regression for the procedural landscape showcase.

Renders the streamed procedural terrain + vegetation and asserts a real landscape
rasterized: substantial green (grass/trees) and blue (water) regions, not a grey
wash.
"""
import os
import sys

import pytest

pytest.importorskip("pygltflib")
pytest.importorskip("glfw")

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))

from tests.unit.viewcapture import run_to_frame


def test_landscape_renders_grass_and_water(tmp_path):
    env = dict(
        os.environ,
        OPENGLCONTEXT_BACKEND="glfw",
        OPENGLCONTEXT_AUTO_EXIT_FRAMES="10",
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR=str(tmp_path),
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME="landscape",
        OPENGLCONTEXT_DISABLE_FPS_DISPLAY="1",
    )
    rgb = run_to_frame([sys.executable, os.path.join(TESTS_DIR, "tiles_landscape.py")],
                       str(tmp_path / "landscape.png"), env=env, timeout=200)
    lit = rgb[rgb.sum(2) > 40]
    r, g, b = lit[:, 0], lit[:, 1], lit[:, 2]
    green = ((g > r + 8) & (g > b + 8)).mean()
    blue = ((b > r + 8) & (b > g + 3)).mean()
    assert green > 0.2, "expected substantial grass/foliage, got %.3f" % green
    assert blue > 0.02, "expected visible water, got %.3f" % blue
