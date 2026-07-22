"""The instanced draw path must not gen/delete a VAO+VBO every frame (GL).

``draw_instanced_mesh`` originally built an ephemeral VAO and per-instance VBO on
every call and deleted them before returning -- real GL-object churn that grows
with (group count * passes) each frame. This regression-locks the fix: after the
first frame the per-instance VAO and VBO are cached on the mesh GPU object and
reused, so steady-state frames create no new vertex arrays for the instanced
draw. Renders a small sphere field (one instanced group), counts
``glGenVertexArrays`` per frame, and asserts the steady-state frames add none.

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
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
os.environ['OPENGLCONTEXT_INSTANCE_MIN'] = '3'
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
try:
    import glfw
    import OpenGL.GL as GL

    STATE = {'gen': 0, 'per_frame': []}
    _real_gen = GL.glGenVertexArrays
    def _counting_gen(*a, **k):
        n = a[0] if a else 1
        STATE['gen'] += n
        return _real_gen(*a, **k)
    GL.glGenVertexArrays = _counting_gen

    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes

    material = basenodes.Material(diffuseColor=(0.2, 0.6, 1.0))
    xs = [-3.0, -1.5, 0.0, 1.5, 3.0]
    def inst(x):
        return basenodes.Transform(translation=(x, 0, 0), children=[
            basenodes.Shape(geometry=basenodes.Sphere(radius=0.6),
                            appearance=basenodes.Appearance(material=material))])

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[inst(x) for x in xs])

    ctx = C(); ctx.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    for i in range(8):
        glfw.poll_events()
        before = STATE['gen']
        ctx.OnDraw(force=1)
        STATE['per_frame'].append(STATE['gen'] - before)

    # The last few frames are steady state: the instanced group's VAO must be
    # cached, so no glGenVertexArrays there. (Frame 0 legitimately builds it.)
    steady = STATE['per_frame'][3:]
    ok = (sum(steady) == 0)
    sys.stderr.write('PER_FRAME=%r STEADY=%r\n' % (STATE['per_frame'], steady))
    os._exit(0 if ok else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def test_instanced_draw_caches_vao_across_frames():
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'instanced draw path still churns a VAO every frame\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))


# The PBR material-array path packs each group's distinct materials into a UBO.
# It originally gen/deleted that UBO every frame; it must now reuse one persistent
# buffer. Counts glGenBuffers per frame for a material-varying instanced group.
DRIVER_UBO = r'''
import os, sys
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
os.environ['OPENGLCONTEXT_INSTANCE_MIN'] = '3'
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
try:
    import glfw
    import OpenGL.GL as GL

    STATE = {'gen': 0, 'per_frame': []}
    _real = GL.glGenBuffers
    def _counting(*a, **k):
        n = a[0] if a else 1
        STATE['gen'] += n
        return _real(*a, **k)
    GL.glGenBuffers = _counting

    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

    quad = PBRMesh(
        positions=[(-.35, -.35, 0), (.35, -.35, 0), (.35, .35, 0), (-.35, .35, 0)],
        normals=[(0, 0, 1)] * 4, indices=[0, 1, 2, 0, 2, 3])
    xs = [-2.4, -0.8, 0.8, 2.4]
    COLORS = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)]
    def inst(x, color):
        return basenodes.Transform(translation=(x, 0, 0), children=[
            basenodes.Shape(geometry=quad,
                appearance=basenodes.Appearance(
                    material=PBRMaterial(unlit=True, baseColor=color)))])

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[
                inst(x, c) for x, c in zip(xs, COLORS)])

    ctx = C(); ctx.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    for i in range(8):
        glfw.poll_events()
        before = STATE['gen']
        ctx.OnDraw(force=1)
        STATE['per_frame'].append(STATE['gen'] - before)

    steady = STATE['per_frame'][3:]
    ok = (sum(steady) == 0)
    sys.stderr.write('PER_FRAME=%r STEADY=%r\n' % (STATE['per_frame'], steady))
    os._exit(0 if ok else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def test_instanced_material_ubo_reused_across_frames():
    proc = subprocess.run([sys.executable, '-c', DRIVER_UBO],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'PBR instanced material-array UBO still gen/deleted every frame\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
