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
import sys

import pytest

from OpenGLContext.testing.paths import tests_root
from tests.unit.viewcapture import run_child

HERE = str(tests_root(__file__))
DRIVER = os.path.join(HERE, '_gltf_toggle_driver.py')
MODEL = os.path.join(HERE, 'wrls', 'instanced_lattice.gltf')


@pytest.mark.parametrize('mode', ['physics', 'nophysics', 'walk'])
def test_walk_freefly_toggle(mode):
    env = dict(os.environ, OPENGLCONTEXT_BACKEND='glfw')
    result = run_child([sys.executable, DRIVER, MODEL, mode], env=env, timeout=120)
    assert 'TOGGLE_OK' in result.stdout, (result.stdout + result.stderr)[-3000:]
