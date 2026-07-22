"""Regression: VRML97 shader lighting is two-sided for solid=FALSE (needs GL).

The fixed-function path gave solid=FALSE geometry automatic two-sided lighting
(GL_LIGHT_MODEL_TWO_SIDE). The core-profile shaders dropped it: neither
vrml97_lighting.frag nor vrml97_vertex_color.frag flipped the normal on back
faces, so the reverse side of double-sided geometry rendered dark. The fix adds
``if (!gl_FrontFacing) normal = -normal;`` to both.

Each scenario renders a single quad whose *front* faces away from the camera
(so only its back face is visible), lit head-on by a directional light. With
correct two-sided lighting the visible back face is bright; without the flip it
is near-black. The driver reads the centre pixel and reports its luminance.
Skips (not fails) when GL is unavailable.
"""
import os
import subprocess
import sys

import pytest

DRIVER = r'''
import os, sys
SCENARIO = sys.argv[1]
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
STATE = {'gl_ok': False, 'lum': -1.0}
try:
    import glfw
    from OpenGL.GL import (
        glReadPixels, GL_RGB, GL_UNSIGNED_BYTE)
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes

    # Quad in the z=0 plane, wound so its front faces -Z (away from the default
    # +Z camera); the camera therefore sees the back face -> gl_FrontFacing false.
    COORD = [(-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)]
    CINDEX = [0, 3, 2, 1, -1]
    NORMAL = [(0, 0, -1)] * 4  # matches the -Z front; flipped to +Z on back faces

    def build():
        common = dict(
            coord=basenodes.Coordinate(point=COORD),
            coordIndex=CINDEX,
            normal=basenodes.Normal(vector=NORMAL),
            normalPerVertex=True,
            solid=False,
        )
        if SCENARIO == 'vertexcolor':
            geom = basenodes.IndexedFaceSet(
                color=basenodes.Color(color=[(1, 1, 1)] * 4),
                colorPerVertex=True, **common)
            mat = basenodes.Material(diffuseColor=(1, 1, 1))
        else:
            geom = basenodes.IndexedFaceSet(**common)
            mat = basenodes.Material(diffuseColor=(1, 1, 1))
        return basenodes.Shape(
            geometry=geom, appearance=basenodes.Appearance(material=mat))

    class C(Base):
        def OnInit(self):
            # Directional light pointing into the screen (-Z): illuminates the
            # camera-facing side once the back-face normal is flipped toward +Z.
            self.sg = basenodes.sceneGraph(children=[
                basenodes.DirectionalLight(direction=(0, 0, -1), intensity=1.0),
                build(),
            ])

    inst = C()
    inst.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    w, h = inst.getViewPort()
    for _ in range(6):
        glfw.poll_events()
        inst.OnDraw(force=1)
    STATE['gl_ok'] = True
    import numpy as np
    px = glReadPixels(w // 2, h // 2, 1, 1, GL_RGB, GL_UNSIGNED_BYTE)
    flat = np.frombuffer(bytes(px), dtype=np.uint8).reshape(-1)
    r, g, b = int(flat[0]), int(flat[1]), int(flat[2])
    STATE['lum'] = (r + g + b) / 3.0
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,))
    import traceback; traceback.print_exc()
    os._exit(3)

sys.stderr.write('SCENARIO=%s GL_OK=%r LUM=%.1f\n'
                 % (SCENARIO, STATE['gl_ok'], STATE['lum']))
if not STATE['gl_ok']:
    os._exit(3)
# Lit back face should be clearly bright; dark (unflipped) is near-zero.
os._exit(0 if STATE['lum'] > 60.0 else 2)
'''


@pytest.mark.parametrize('scenario', ['material', 'vertexcolor'])
def test_twosided_lighting(scenario):
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, '-c', DRIVER, scenario],
                          capture_output=True, text=True, timeout=120, env=env)
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'two-sided lighting failed for %r (back face rendered dark)\n'
        'stdout:\n%s\nstderr:\n%s' % (scenario, proc.stdout, proc.stderr))
