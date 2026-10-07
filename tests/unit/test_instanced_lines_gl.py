"""Line sets drawn through the instanced path land where the shader reads them (GL regression).

``IndexedLineSet`` nodes that share one geometry are drawn as one instanced
call, through the same VAO machinery as meshes. The vertex arrays have to be
at the attribute locations ``scenegraph/vertexsemantics.py`` fixes, since a VAO
records locations: positions at any other location leave the shader reading a
zero position for every vertex, and every line collapses to a point.

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
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
os.environ['OPENGLCONTEXT_INSTANCING'] = sys.argv[1]
try:
    import glfw
    from OpenGLContext.context import Context as Base
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.testing.framebuffer_comparison import read_back_buffer

    line = basenodes.Shape(
        geometry=basenodes.IndexedLineSet(
            coord=basenodes.Coordinate(point=[(-1, 0, 0), (1, 0, 0)]),
            coordIndex=[0, 1, -1]),
        appearance=basenodes.Appearance(material=basenodes.Material(
            diffuseColor=(0.05, 0.05, 0.05), emissiveColor=(0.9, 0.9, 0.1))))
    holder = basenodes.Transform(children=[line])

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[
                basenodes.Transform(translation=(0, 0.1 * i - 0.4, 0), children=[holder])
                for i in range(8)
            ])

    ctx = C(); ctx.deferRedraw = True
    for i in range(4):
        glfw.poll_events()
        ctx.OnDraw(force=1)
    pixels, width, height = read_back_buffer(0)
    yellow = int(((pixels[..., 0] > 150) & (pixels[..., 2] < 100)).sum())
    sys.stderr.write('yellow=%d\n' % yellow)
    os._exit(0 if yellow > 100 else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    from OpenGLContext.testing.plugin import NO_CONTEXT_STATUS
    os._exit(NO_CONTEXT_STATUS)
'''


@pytest.mark.parametrize('instancing', ['1', '0'], ids=['instanced', 'per-shape'])
def test_shared_line_sets_are_drawn(instancing):
    proc = subprocess.run([sys.executable, '-c', DRIVER, instancing],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    skip_if_child_had_no_context(proc.returncode, proc.stderr)
    assert proc.returncode == 0, (
        'shared line sets were not drawn (instancing=%s)\n'
        'stdout:\n%s\nstderr:\n%s' % (instancing, proc.stdout, proc.stderr))
