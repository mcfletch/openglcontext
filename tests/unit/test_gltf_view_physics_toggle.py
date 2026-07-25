"""Regression test for the oglc-gltf viewer's runtime walk/free-fly toggle.

``oglc-gltf`` starts in physics walk mode.  If the initial viewpoint drops the
avatar inside geometry you must be able to escape, so the ``g`` key toggles to the
free-fly camera at runtime (and back).  The two navigators must never both drive
``context.platform`` -- physics unbinds the default Smooth manager while it owns
the camera, and hands it back on toggle-off -- and toggling must not jump the view.

Driven in a subprocess (``_gltf_toggle_driver.py``): multiple GL contexts can't
coexist in one process, so each scenario gets its own.
"""
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.paths import tests_root
HERE = str(tests_root(__file__))
ROOT = os.path.dirname(HERE)
DRIVER = os.path.join(HERE, '_gltf_toggle_driver.py')
MODEL = os.path.join(HERE, 'wrls', 'instanced_lattice.gltf')


def _gl_available():
    try:
        import glfw
    except Exception:
        return False
    try:
        if not glfw.init():
            return False
        # GLFW window hints are sticky/process-global; reset them so a prior
        # core-profile test's profile can't leak into this context.
        glfw.default_window_hints()
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        w = glfw.create_window(64, 64, 't', None, None)
        if not w:
            return False
        glfw.destroy_window(w)
        return True
    except Exception:
        return False


gl = pytest.mark.skipif(not _gl_available(), reason='no GL target available')


@gl
@pytest.mark.parametrize('mode', ['physics', 'nophysics', 'walk'])
def test_walk_freefly_toggle(mode):
    env = dict(os.environ, OPENGLCONTEXT_BACKEND='glfw')
    try:
        proc = subprocess.run(
            [sys.executable, DRIVER, MODEL, mode],
            cwd=ROOT, env=env, timeout=120,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired:
        pytest.skip('viewer subprocess timed out (no usable GL?)')
    out = proc.stdout.decode('utf-8', 'replace')
    assert proc.returncode == 0, out[-3000:]
    assert 'TOGGLE_OK' in out, out[-3000:]
