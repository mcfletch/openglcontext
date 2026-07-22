"""Regression: shader geometry caches its VAO instead of gen/deleting per frame.

`render_shader_arrays`/`render_shader_interleaved` called `glGenVertexArrays` +
`glDeleteVertexArrays` on every draw, throwing away the VAO the whole point of
which is to record attribute layout once. These back every shader-mode
IndexedFaceSet (ArrayGeometry), every Sphere/Cone/Cylinder (Quadric), and Box.

The driver renders a Sphere for several frames in core profile while counting
`glGenVertexArrays` calls inside shadergeometry, and asserts the count reaches a
steady state -- no new VAO generated per warm frame. Skips when GL is
unavailable.
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
STATE = {'gl_ok': False, 'warm': None, 'final': None}
try:
    import glfw
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph import shadergeometry

    counter = {'gen': 0}
    _real_gen = shadergeometry.glGenVertexArrays
    def counting_gen(*a, **k):
        counter['gen'] += 1
        return _real_gen(*a, **k)
    shadergeometry.glGenVertexArrays = counting_gen

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[
                basenodes.DirectionalLight(direction=(0, 0, -1)),
                basenodes.Shape(
                    geometry=basenodes.Sphere(radius=2),
                    appearance=basenodes.Appearance(
                        material=basenodes.Material(diffuseColor=(0, 1, 0)))),
            ])

    inst = C()
    inst.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    for i in range(12):
        glfw.poll_events()
        inst.OnDraw(force=1)
        if i == 5:
            STATE['warm'] = counter['gen']
    STATE['final'] = counter['gen']
    STATE['gl_ok'] = True
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,))
    import traceback; traceback.print_exc()
    os._exit(3)

sys.stderr.write('GL_OK=%r warm(after frame5)=%r final(after frame11)=%r\n'
                 % (STATE['gl_ok'], STATE['warm'], STATE['final']))
if not STATE['gl_ok']:
    os._exit(3)
# Steady state: frames 6..11 must not each mint a new VAO.
os._exit(0 if STATE['final'] == STATE['warm'] else 2)
'''


def test_shader_vao_reaches_steady_state():
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120, env=env)
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'shader geometry regenerates VAOs every frame (no caching)\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
