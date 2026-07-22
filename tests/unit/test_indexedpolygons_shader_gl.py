"""Regression: per-vertex-normal IFS renders under core profile (needs GL).

`IndexedFaceSetCompile` prefers `IndexedPolygonsCompiler` (weight 1.05 > 1.0) for
any IFS with per-vertex normals, but `IndexedPolygons.render()` had no shader
path -- it unconditionally issued `glEnableClientState`/`glVertexPointer`, which
don't exist in core profile, so such content silently failed to render under
`OPENGLCONTEXT_PROFILE=core`.

The driver builds a per-vertex-normal quad facing the camera, lit head-on, and
asserts a meaningful region of the framebuffer is lit. Skips when GL is
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
STATE = {'gl_ok': False, 'nonblack': -1, 'via_ip': False}
try:
    import glfw, numpy as np
    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph.indexedfaceset import IndexedPolygonsCompiler

    def build_ifs():
        # A camera-facing quad (front toward +Z) with explicit per-vertex normals.
        return basenodes.IndexedFaceSet(
            coord=basenodes.Coordinate(point=[
                (-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)]),
            coordIndex=[0, 1, 2, -1, 0, 2, 3, -1],
            normal=basenodes.Normal(vector=[(0, 0, 1)] * 4),
            normalIndex=[0, 1, 2, -1, 0, 2, 3, -1],
            normalPerVertex=True,
            solid=False,
        )

    ifs = build_ifs()
    STATE['via_ip'] = (IndexedPolygonsCompiler.weight(ifs) == 1.05)

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[
                basenodes.DirectionalLight(direction=(0, 0, -1), intensity=1.0),
                basenodes.Shape(
                    geometry=build_ifs(),
                    appearance=basenodes.Appearance(
                        material=basenodes.Material(diffuseColor=(1, 1, 1)))),
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
    px = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
    arr = np.frombuffer(bytes(px), dtype=np.uint8).reshape(h, w, 3)
    STATE['nonblack'] = int((arr.sum(axis=2) > 60).sum())
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,))
    import traceback; traceback.print_exc()
    os._exit(3)

sys.stderr.write('GL_OK=%r via_IndexedPolygons=%r nonblack=%d\n'
                 % (STATE['gl_ok'], STATE['via_ip'], STATE['nonblack']))
if not STATE['gl_ok']:
    os._exit(3)
if not STATE['via_ip']:
    os._exit(4)   # premise broken: didn't route to IndexedPolygons
os._exit(0 if STATE['nonblack'] > 3000 else 2)
'''


def test_indexedpolygons_renders_under_core():
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120, env=env)
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode != 4, (
        'premise broken: IFS no longer routes to IndexedPolygonsCompiler\n%s'
        % proc.stderr)
    assert proc.returncode == 0, (
        'per-vertex-normal IFS did not render under core profile\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
