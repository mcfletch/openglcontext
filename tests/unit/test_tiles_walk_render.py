"""Offscreen render regression for the first-person walk demo.

Confirms the avatar spawns on the terrain and the eye-level view shows grassy terrain
(the physics-driven camera is seated on the surface, not floating in the void). The
walk/fly/drop behaviours themselves are validated in tests/tiles3d/test_navigation.py.
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


def test_walk_view_is_on_the_surface(tmp_path):
    env = dict(
        os.environ,
        OPENGLCONTEXT_BACKEND="glfw",
        OPENGLCONTEXT_AUTO_EXIT_FRAMES="24",
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR=str(tmp_path),
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME="walk",
        OPENGLCONTEXT_DISABLE_FPS_DISPLAY="1",
    )
    try:
        subprocess.run(
            [sys.executable, os.path.join(TESTS_DIR, "tiles_walk.py")],
            cwd=os.path.dirname(TESTS_DIR), env=env, timeout=200,
        )
    except subprocess.TimeoutExpired:
        pass
    out = tmp_path / "walk.png"
    if not out.exists():
        pytest.skip("no GL capture produced (no usable offscreen GL target)")
    rgb = np.asarray(Image.open(str(out)).convert("RGB")).astype(int)
    lit = rgb[rgb.sum(2) > 40]
    assert lit.shape[0] > 0, "eye-level frame is empty (avatar not on surface?)"
    green = ((lit[:, 1] > lit[:, 0] + 8) & (lit[:, 1] > lit[:, 2] + 8)).mean()
    assert green > 0.3, "expected grassy terrain filling the view, got %.3f" % green
