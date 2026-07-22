"""Offscreen render regression for instanced vegetation on terrain.

Renders the vegetation demo and asserts many green (foliage) pixels appear over the
terrain — i.e. the scattered, instanced shrubs actually rasterized.
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


def test_vegetation_renders_green_foliage(tmp_path):
    env = dict(
        os.environ,
        OPENGLCONTEXT_IBL="off",
        OPENGLCONTEXT_BACKEND="glfw",
        OPENGLCONTEXT_PROFILE="core",
        OPENGLCONTEXT_AUTO_EXIT_FRAMES="12",
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR=str(tmp_path),
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME="veg",
        OPENGLCONTEXT_DISABLE_FPS_DISPLAY="1",
    )
    subprocess.run(
        [sys.executable, os.path.join(TESTS_DIR, "tiles_vegetation.py")],
        cwd=os.path.dirname(TESTS_DIR), env=env, timeout=180,
    )
    out = tmp_path / "veg.png"
    if not out.exists():
        pytest.skip("no GL capture produced (no usable offscreen GL target)")
    rgb = np.asarray(Image.open(str(out)).convert("RGB")).astype(int)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    # Foliage: clearly green pixels (green channel dominant over red and blue).
    green = (g > 60) & (g > r + 25) & (g > b + 25)
    assert green.sum() > 500, "expected scattered green foliage, got %d px" % green.sum()
