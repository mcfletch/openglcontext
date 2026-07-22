"""Regression: PointSet caches its VAO+VBO instead of rebuilding per frame.

The PointSet shader path rebuilt its entire GPU buffer every frame: a fresh
numpy interleave, glGenBuffers + full glBufferData re-upload, glGenVertexArrays,
draw, then glDeleteBuffers + glDeleteVertexArrays -- for the one node whose whole
job is dynamic points. When the point data is unchanged, none of that should
recur.

The driver renders a static coloured PointSet for several frames while counting
glGenBuffers inside the pointset module, and asserts it reaches steady state.
Skips when GL is unavailable.
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
    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph import pointset as pointset_mod

    counter = {'buf': 0}
    _real = pointset_mod.glGenVertexArrays
    def counting(*a, **k):
        counter['buf'] += 1
        return _real(*a, **k)
    pointset_mod.glGenVertexArrays = counting

    pts = [(x * 0.2 - 2, (x % 5) * 0.3 - 0.6, 0) for x in range(40)]
    cols = [(1, (x % 3) * 0.5, 0.5) for x in range(40)]

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[
                basenodes.Shape(
                    geometry=basenodes.PointSet(
                        coord=basenodes.Coordinate(point=pts),
                        color=basenodes.Color(color=cols), size=8.0)),
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
            STATE['warm'] = counter['buf']
    STATE['final'] = counter['buf']
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
if STATE['nonblack'] < 100:
    os._exit(5)   # didn't actually render the points
os._exit(0 if STATE['final'] == STATE['warm'] else 2)
'''


def test_pointset_reaches_steady_state():
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120, env=env)
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode != 5, (
        'PointSet rendered nothing; test premise broken\n%s' % proc.stderr)
    assert proc.returncode == 0, (
        'PointSet rebuilds its GPU buffer every frame (no caching)\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
