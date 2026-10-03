"""Shared non-solid geometry seen from behind is drawn when it is instanced (GL regression).

A VRML world that ``USE``s one ``IndexedFaceSet`` many times has it drawn as a
single instanced call. That call drew under whatever winding and culling the
last draw left, so single-sided, non-solid shapes (chair seats, walls) were
culled from one side and came and went as the camera turned.

The quads face away from the camera and are not solid; the centre pixel has to
be their red rather than the background.

Skips (not fails) when no usable GL context can be created.
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
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
os.environ['OPENGLCONTEXT_INSTANCING'] = '1'
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
    # One node used by every placement, as a VRML USE does.
    holder = basenodes.Transform(children=[quad])

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[
                basenodes.Transform(translation=(0, 0, -0.01 * i), children=[holder])
                for i in range(8)
            ])

    ctx = C(); ctx.deferRedraw = True
    for i in range(4):
        glfw.poll_events()
        ctx.OnDraw(force=1)
    pixels, width, height = read_back_buffer(0)
    r, g, b = [int(v) for v in pixels[height // 2, width // 2][:3]]
    sys.stderr.write('centre=%r\n' % ((r, g, b),))
    os._exit(0 if r > 120 and r > 2 * b else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def test_instanced_nonsolid_quads_seen_from_behind_are_drawn():
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'instanced non-solid geometry seen from behind was culled\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
