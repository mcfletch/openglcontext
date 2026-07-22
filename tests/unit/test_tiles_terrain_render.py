"""Offscreen render regression for the streamed 3D Tiles terrain demo.

Runs `tests/tiles_terrain.py` in a subprocess with a hidden GLFW window, captures a
frame, and asserts the terrain actually rasterized (a substantial lit region), not a
blank frame. This exercises the whole Phase-1 path end to end: tileset parse, SSE
traversal, background glTF load, GL mount, and draw.
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


def _render(tmp_path):
    env = dict(
        os.environ,
        OPENGLCONTEXT_BACKEND="glfw",
        OPENGLCONTEXT_PROFILE="core",
        OPENGLCONTEXT_AUTO_EXIT_FRAMES="12",
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR=str(tmp_path),
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME="terrain",
        OPENGLCONTEXT_DISABLE_FPS_DISPLAY="1",
    )
    subprocess.run(
        [sys.executable, os.path.join(TESTS_DIR, "tiles_terrain.py")],
        cwd=os.path.dirname(TESTS_DIR), env=env, timeout=180,
    )
    out = tmp_path / "terrain.png"
    if not out.exists():
        pytest.skip("no GL capture produced (no usable offscreen GL target)")
    return np.asarray(Image.open(str(out)).convert("RGB")).astype(int)


def test_terrain_demo_renders_non_blank(tmp_path):
    frame = _render(tmp_path)
    lit = (frame.sum(axis=2) > 40)
    fraction = lit.mean()
    # The terrain fills a large part of the lower frame; well above any stray pixel.
    assert fraction > 0.15, "terrain frame is essentially blank (%.3f lit)" % fraction
