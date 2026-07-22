"""Regression: IndexedLineSet caches its VAO+VBO instead of per-polyline churn.

The IndexedLineSet shader path created one VAO per frame and then, inside a
per-polyline loop, glGenBuffers/glBufferData/glDeleteBuffers plus a Python
list-comprehension vertex build for each polyline, every frame. When the line
data is unchanged none of that should recur.

The driver renders a static multi-polyline coloured IndexedLineSet for several
frames while counting glGenVertexArrays (patched at OpenGL.GL so it is seen
whether the module imports it at call time or module scope), and asserts steady
state. Skips when GL is unavailable.
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
STATE = {'gl_ok': False, 'warm': None, 'final': None, 'nonblack': -1}
try:
    import glfw, numpy as np
    import OpenGL.GL as GL
    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes

    from OpenGLContext.scenegraph import indexedlineset as ils_mod
    counter = {'vao': 0}
    _real = GL.glGenVertexArrays
    def counting(*a, **k):
        counter['vao'] += 1
        return _real(*a, **k)
    # Patch both the OpenGL.GL wrapper (caught by a call-time ``import``) and the
    # module's own copied name (caught by the module-scope ``import *``), so the
    # counter sees per-frame VAO churn regardless of how the code imports it.
    GL.glGenVertexArrays = counting
    ils_mod.glGenVertexArrays = counting

    # Two polylines forming a wide zig-zag near the origin, coloured per-vertex.
    pts = [(-3, 0, 0), (-1, 2, 0), (1, -2, 0), (3, 0, 0),
           (-3, -1, 0), (0, 1, 0), (3, -1, 0)]
    cidx = [0, 1, 2, 3, -1, 4, 5, 6, -1]
    cols = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0),
            (1, 0, 1), (0, 1, 1), (1, 1, 1)]

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[
                basenodes.Shape(
                    geometry=basenodes.IndexedLineSet(
                        coord=basenodes.Coordinate(point=pts),
                        coordIndex=cidx,
                        color=basenodes.Color(color=cols),
                        colorPerVertex=True)),
            ])

    inst = C()
    inst.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    w, h = inst.getViewPort()
    # Count only VAOs generated after warmup, isolating per-frame churn from any
    # one-time framework VAO allocation.
    for i in range(12):
        glfw.poll_events()
        inst.OnDraw(force=1)
        if i == 5:
            STATE['warm'] = counter['vao']
    STATE['final'] = counter['vao']
    px = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
    arr = np.frombuffer(bytes(px), dtype=np.uint8).reshape(h, w, 3)
    STATE['nonblack'] = int((arr.sum(axis=2) > 60).sum())
    STATE['gl_ok'] = True
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,))
    import traceback; traceback.print_exc()
    os._exit(3)

sys.stderr.write('GL_OK=%r warm=%r final=%r nonblack=%d\n'
                 % (STATE['gl_ok'], STATE['warm'], STATE['final'], STATE['nonblack']))
if not STATE['gl_ok']:
    os._exit(3)
if STATE['nonblack'] < 50:
    os._exit(5)
os._exit(0 if STATE['final'] == STATE['warm'] else 2)
'''


def test_indexedlineset_reaches_steady_state():
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120, env=env)
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode != 5, (
        'IndexedLineSet rendered nothing; test premise broken\n%s' % proc.stderr)
    assert proc.returncode == 0, (
        'IndexedLineSet churns VAOs/VBOs every frame (no caching)\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
