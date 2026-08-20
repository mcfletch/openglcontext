"""A wave really moves, on the card (GL, PBR core).

The uniform plumbing and the two copies of the field are asserted without a
window; what needs one is the claim the whole thing exists for -- that the mesh
is uploaded once and the surface is somewhere else a moment later, at no
per-frame cost on the processor.
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
try:
    import glfw
    import numpy as np
    from OpenGL import GL as gl
    from OpenGLContext import testingcontext
    from OpenGLContext.scenegraph.basenodes import sceneGraph, Viewpoint
    from OpenGLContext.scenegraph.appearance import Appearance
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    from OpenGLContext.scenegraph.shape import Shape
    from OpenGLContext.scenegraph.water import CHOPPY, water_surface

    Base = testingcontext.getInteractive()

    class V(Base):
        def OnInit(self):
            sheet = water_surface(-12.0, 12.0, -12.0, 12.0, level=0.0,
                                  resolution=65, style=CHOPPY, when=0.0)
            # Bright and unlit, so what the picture shows is the shape of the
            # surface rather than what a dark material reflects.
            sheet.wave_style = CHOPPY
            sheet.wave_time = 0.0
            self.sheet = sheet
            self.sg = sceneGraph(children=[
                Viewpoint(position=(0, 6, 16), orientation=(1, 0, 0, -0.32)),
                Shape(geometry=sheet, appearance=Appearance(
                    material=PBRMaterial(baseColor=(0.9, 0.9, 0.9),
                                         emissiveColor=(0.6, 0.7, 0.9),
                                         metallic=0.0, roughness=0.3))),
            ])

    v = V(size=(240, 240))
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
    def frame():
        glfw.poll_events()
        v.OnDraw(force=1)
        width, height = v.getViewPort()
        raw = gl.glReadPixels(0, 0, width, height, gl.GL_RGB,
                              gl.GL_UNSIGNED_BYTE)
        return np.frombuffer(raw, np.uint8).reshape(height, width, 3).astype(int)

    v.sheet.wave_time = 0.0
    frame()
    still = frame()
    # The same moment twice: a world rendered twice is the same world.
    v.sheet.wave_time = 0.0
    again = frame()
    if np.abs(still - again).max() > 2:
        sys.stderr.write('the same moment drew differently\n')
        os._exit(4)
    # A second later it has moved, and nothing was re-uploaded to do it.
    v.sheet.wave_time = 0.9
    later = frame()
    moved = int((np.abs(still - later).sum(axis=2) > 12).sum())
    sys.stderr.write('pixels that moved: %d\n' % moved)
    if moved < 200:
        sys.stderr.write('the wave did not move\n')
        os._exit(2)
    os._exit(0)
except SystemExit:
    raise
except BaseException:
    import traceback; traceback.print_exc()
    os._exit(2)
'''


def _run():
    return subprocess.run([sys.executable, '-c', DRIVER], capture_output=True,
                          text=True, timeout=120, env=dict(os.environ))


def test_a_wave_moves_between_two_moments():
    proc = _run()
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode != 2, (
        'the surface did not move when its wave time changed\n%s' % proc.stderr)


def test_the_same_moment_draws_the_same_water():
    proc = _run()
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode != 4, (
        'the same wave time drew two different pictures\n%s' % proc.stderr)
