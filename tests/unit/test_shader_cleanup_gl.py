"""GL smoke test for the shader-cleanup batch (needs GL, off-screen).

After folding the shared `#include`s in the four non-lit shaders
are now assembled through `preprocess_shader`, so this confirms every VRML97
program still compiles and that lit / per-vertex-colour / point / line geometry
all render (a blank frame or a compile error would fail). Skips without GL.
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
STATE = {'gl_ok': False, 'nonblack': -1, 'programs_ok': False}
try:
    import glfw, numpy as np
    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes as b

    class C(Base):
        def OnInit(self):
            # lit Box, per-vertex-colour IFS, PointSet, IndexedLineSet -> exercises
            # the lit / vertex_color / point / line programs respectively.
            vc_ifs = b.IndexedFaceSet(
                coord=b.Coordinate(point=[(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)]),
                coordIndex=[0,1,2,-1,0,2,3,-1],
                color=b.Color(color=[(1,0,0),(0,1,0),(0,0,1),(1,1,0)]),
                colorPerVertex=True, solid=False)
            self.sg = b.sceneGraph(children=[
                b.DirectionalLight(direction=(0,0,-1)),
                b.Transform(translation=(-4,0,0), children=[b.Shape(geometry=b.Box(size=(2,2,2)),
                    appearance=b.Appearance(material=b.Material(diffuseColor=(0,1,1))))]),
                b.Transform(translation=(-1.5,0,0), children=[b.Shape(geometry=vc_ifs)]),
                b.Transform(translation=(1.5,0,0), children=[b.Shape(geometry=b.PointSet(
                    coord=b.Coordinate(point=[(0,0,0),(0.4,0.4,0),(-0.4,-0.4,0)]),
                    color=b.Color(color=[(1,1,1),(1,0,0),(0,1,0)]), size=20.0))]),
                b.Transform(translation=(4,0,0), children=[b.Shape(geometry=b.IndexedLineSet(
                    coord=b.Coordinate(point=[(-1,-1,0),(1,1,0),(1,-1,0)]),
                    coordIndex=[0,1,2,-1],
                    color=b.Color(color=[(1,0,0),(0,1,0),(0,0,1)]), colorPerVertex=True))]),
            ])

    inst = C(); inst.deferRedraw = True
    try: glfw.swap_interval(0)
    except Exception: pass
    w, h = inst.getViewPort()
    for _ in range(6):
        glfw.poll_events(); inst.OnDraw(force=1)
    STATE['gl_ok'] = True
    # All VRML97 programs must have compiled.
    fp = getattr(__import__('OpenGLContext.passes.renderpass', fromlist=['FLAT']), 'FLAT', None)
    sp = getattr(fp, 'shader_program', None)
    STATE['programs_ok'] = bool(sp and sp.program and sp.unlit_program
                                and sp.vertex_color_program and sp.point_program
                                and sp.line_program)
    px = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
    arr = np.frombuffer(bytes(px), dtype=np.uint8).reshape(h, w, 3)
    STATE['nonblack'] = int((arr.sum(axis=2) > 60).sum())
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,)); import traceback; traceback.print_exc(); os._exit(3)

sys.stderr.write('GL_OK=%r programs_ok=%r nonblack=%d\n'
                 % (STATE['gl_ok'], STATE['programs_ok'], STATE['nonblack']))
if not STATE['gl_ok']:
    os._exit(3)
if not STATE['programs_ok']:
    os._exit(4)
os._exit(0 if STATE['nonblack'] > 3000 else 2)
'''


def test_all_vrml97_programs_compile_and_render():
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120, env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s' % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode != 4, ('a VRML97 shader program failed to compile\n%s'
                                  % proc.stderr)
    assert proc.returncode == 0, ('shader-cleanup broke rendering\nstdout:\n%s\nstderr:\n%s'
                                  % (proc.stdout, proc.stderr))
