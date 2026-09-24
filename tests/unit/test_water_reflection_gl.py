"""Water reflects what stands beside it (GL, PBR core).

A bright red box stands at the far edge of a sheet of water and the camera
looks across the water at it. With the reflection on, the box is in the water
below it; with it off, the water holds only the sky. The arithmetic is asserted
without a window in ``test_water_reflection.py``; this is the claim that needs
one.
"""
import os
import subprocess
import sys

import pytest

DRIVER = r'''
import os, sys
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
os.environ['OPENGLCONTEXT_HIDDEN'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
os.environ['OPENGLCONTEXT_WATER_REFLECTION'] = sys.argv[1]
try:
    import glfw
    import numpy as np
    from OpenGL import GL as gl
    from OpenGLContext import testingcontext
    from OpenGLContext.scenegraph.basenodes import (
        Appearance, Box, Material, Shape, Transform, Viewpoint, sceneGraph)
    from OpenGLContext.scenegraph.water import STILL, water_surface

    water = water_surface(-10.0, 10.0, -12.0, 8.0, level=0.0, resolution=9,
                          style=STILL, on_gpu=True)
    box = Transform(translation=(0.0, 2.0, -9.0), children=[Shape(
        geometry=Box(size=(3.0, 4.0, 1.0)),
        appearance=Appearance(material=Material(
            diffuseColor=(1.0, 0.0, 0.0), emissiveColor=(1.0, 0.0, 0.0))))])
    Base = testingcontext.getInteractive()

    class V(Base):
        def OnInit(self):
            self.sg = sceneGraph(children=[
                Viewpoint(position=(0.0, 1.5, 8.0), orientation=(1, 0, 0, -0.12)),
                Shape(geometry=water, appearance=Appearance(material=water.material)),
                box,
            ])

    v = V(size=(160, 160))
    v.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)

try:
    for _ in range(6):
        glfw.poll_events()
        v.OnDraw(force=1)
    width, height = v.getViewPort()
    raw = gl.glReadPixels(0, 0, width, height, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
    image = np.frombuffer(raw, np.uint8).reshape(height, width, 3).astype(int)
    # glReadPixels reads bottom row first: the lower third is water.
    water_rows = image[: height // 3]
    red = (water_rows[..., 0] > 80) & (water_rows[..., 0] > water_rows[..., 1] + 40)
    sys.stdout.write('%d\n' % int(red.sum()))
    sys.stdout.flush()
    os._exit(0)
except BaseException:
    import traceback; traceback.print_exc()
    os._exit(2)
'''


def _reflected_red(on):
    proc = subprocess.run([sys.executable, '-c', DRIVER, '1' if on else '0'],
                          capture_output=True, text=True, timeout=180,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, proc.stderr
    return int(proc.stdout.strip().splitlines()[-1])


def test_the_box_is_in_the_water():
    assert _reflected_red(on=True) > 100


def test_switched_off_the_water_holds_only_the_sky():
    assert _reflected_red(on=False) == 0
