"""A non-solid surface seen from behind is drawn in a scene that casts shadows (GL regression).

The shadow depth pass switches face culling off and puts back whatever the
caller had. The record of what GL has, which draws consult to skip a call that
changes nothing, kept the depth pass's last answer, so the colour pass's first
non-solid shape found the record agreeing with it and left culling on. A VRML
world of single-sided walls viewed from inside lost every wall.

The quad faces away from the camera and is not solid; its centre pixel has to be
red rather than the black background. The light reaches only its front face, so
the red it shows is the environment's.

Skips (not fails) when no usable GL context can be created.
"""
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.plugin import skip_if_child_had_no_context

DRIVER = r'''
import os, sys
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '1'
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
try:
    import glfw
    from OpenGLContext.context import Context as Base
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.testing.framebuffer_comparison import read_back_buffer

    quad = basenodes.Shape(
        geometry=basenodes.IndexedFaceSet(
            coord=basenodes.Coordinate(point=[(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]),
            # Clockwise from the default camera: its back faces the viewer.
            coordIndex=[3, 2, 1, 0, -1], solid=False),
        appearance=basenodes.Appearance(
            material=basenodes.Material(diffuseColor=(0.9, 0.1, 0.1))))

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[
                quad,
                basenodes.DirectionalLight(direction=(0.2, -1, -0.5), intensity=1.0,
                                           shadows=True),
            ])

    ctx = C(); ctx.deferRedraw = True
    for i in range(4):
        glfw.poll_events()
        ctx.OnDraw(force=1)
    pixels, width, height = read_back_buffer(0)
    r, g, b = [int(v) for v in pixels[height // 2, width // 2][:3]]
    sys.stderr.write('centre=%r\n' % ((r, g, b),))
    os._exit(0 if r > 40 and r > 2 * b else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def test_nonsolid_quad_seen_from_behind_is_drawn_with_shadows_on():
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    skip_if_child_had_no_context(proc.returncode, proc.stderr)
    assert proc.returncode == 0, (
        'a non-solid surface seen from behind was culled\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
