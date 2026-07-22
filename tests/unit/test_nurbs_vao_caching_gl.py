"""Regression: NURBS caches its VAO instead of gen/deleting per frame (needs GL).

`NurbsSurface._render_shader` cached its tessellated VBO (per LOD level) but still
`glGenVertexArrays`/`glDeleteVertexArrays` and re-bound every attribute on every
frame -- the VAO churn the other geometry types shed. It now reuses a VAO cached
per (program, VBO) via the shared `_get_or_build_vao`.

The driver renders a NURBS surface for several frames, counting glGenVertexArrays
inside the nurbs module, and asserts steady state. Skips without GL.
"""
import os
import subprocess
import sys

import pytest

DRIVER = r'''
import os, sys
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
os.environ['OPENGLCONTEXT_LOD'] = '0'   # pin LOD level 0 so one VBO is used
STATE = {'gl_ok': False, 'warm': None, 'final': None, 'nonblack': -1}
try:
    import glfw, numpy as np
    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph import nurbs
    from OpenGLContext.scenegraph import shadergeometry

    # Count VAO generation whether it comes from the old in-module gen (pre-fix,
    # per frame) or the shared cached _get_or_build_vao (post-fix, once).
    counter = {'vao': 0}
    for mod in (nurbs, shadergeometry):
        real = mod.glGenVertexArrays
        def counting(*a, _real=real, **k):
            counter['vao'] += 1
            return _real(*a, **k)
        mod.glGenVertexArrays = counting

    KNOT = [0, 0, 0, 0, 1, 1, 1, 1]
    cps = [[x - 1.5, y - 1.5, (0.8 if (x + y) % 2 else -0.8)]
           for y in range(4) for x in range(4)]

    class C(Base):
        def OnInit(self):
            surf = nurbs.NurbsSurface(controlPoint=cps, uDimension=4, vDimension=4,
                                      uKnot=KNOT, vKnot=KNOT)
            self.sg = basenodes.sceneGraph(children=[
                basenodes.DirectionalLight(direction=(0, 0, -1)),
                basenodes.Shape(geometry=surf, appearance=basenodes.Appearance(
                    material=basenodes.Material(diffuseColor=(0.2, 0.6, 1.0)))),
            ])

    inst = C()
    inst.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    w, h = inst.getViewPort()
    for i in range(12):
        glfw.poll_events()
        inst.OnDraw(force=1)
        if i == 5:
            STATE['warm'] = counter['vao']
    STATE['final'] = counter['vao']
    STATE['gl_ok'] = True
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,)); import traceback; traceback.print_exc(); os._exit(3)

sys.stderr.write('GL_OK=%r warm=%r final=%r\n'
                 % (STATE['gl_ok'], STATE['warm'], STATE['final']))
if not STATE['gl_ok']:
    os._exit(3)
if STATE['final'] < 1:
    os._exit(5)   # the shader render path never built a VAO -> test is meaningless
os._exit(0 if STATE['final'] == STATE['warm'] else 2)
'''


def test_nurbs_reaches_steady_state():
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120, env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode != 5, ('NURBS surface rendered nothing\n%s' % proc.stderr)
    assert proc.returncode == 0, (
        'NURBS regenerates its VAO every frame (no caching)\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
