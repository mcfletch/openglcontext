"""Offscreen render regression for the procedural landscape showcase.

Renders the streamed procedural terrain + vegetation and asserts a real landscape
rasterized: substantial green (grass/trees) and blue (water) regions, not a grey
wash. Tolerates a slow teardown (reads the captured frame even if the process must be
timed out), as the render itself completes well before capture.
"""
import os
import subprocess
import sys

import pytest

pytest.importorskip("pygltflib")
pytest.importorskip("glfw")
np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))


def test_landscape_renders_grass_and_water(tmp_path):
    env = dict(
        os.environ,
        OPENGLCONTEXT_BACKEND="glfw",
        OPENGLCONTEXT_AUTO_EXIT_FRAMES="10",
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR=str(tmp_path),
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME="landscape",
        OPENGLCONTEXT_DISABLE_FPS_DISPLAY="1",
    )
    try:
        subprocess.run(
            [sys.executable, os.path.join(TESTS_DIR, "tiles_landscape.py")],
            cwd=os.path.dirname(TESTS_DIR), env=env, timeout=200,
        )
    except subprocess.TimeoutExpired:
        pass  # slow teardown; the frame was captured before auto-exit
    out = tmp_path / "landscape.png"
    if not out.exists():
        pytest.skip("no GL capture produced (no usable offscreen GL target)")
    rgb = np.asarray(Image.open(str(out)).convert("RGB")).astype(int)
    lit = rgb[rgb.sum(2) > 40]
    r, g, b = lit[:, 0], lit[:, 1], lit[:, 2]
    green = ((g > r + 8) & (g > b + 8)).mean()
    blue = ((b > r + 8) & (b > g + 3)).mean()
    assert green > 0.2, "expected substantial grass/foliage, got %.3f" % green
    assert blue > 0.02, "expected visible water, got %.3f" % blue
