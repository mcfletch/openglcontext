"""A shape that fails part way through its draw leaves the next one drawable.

A geometry binds a program of its own (a line set binds the line program)
before it draws, and puts the pass's lit program back afterwards. One that
raises in between leaves its program bound; the pass then sets the next
shape's matrices at the lit program's uniform locations on the wrong program,
which GL refuses, and that shape is lost too. The pass puts its own program
back after any failed draw.

The driver draws two line sets, made to raise after binding the line
program, and a red box, and reports the failures the pass recorded, how much
of the frame is red, and which program was bound each time matrices were set
for a named one.
"""
import os
import subprocess
import sys

from OpenGLContext.testing.plugin import skip_if_child_had_no_context

DRIVER = r'''
import os, sys
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
os.environ['OPENGLCONTEXT_INSTANCING'] = '0'
try:
    import glfw, numpy as np
    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
    from OpenGLContext.context import Context as Base
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph import indexedlineset

    def broken(self, mode, has_colors):
        raise ValueError('the line buffer cannot be built')
    indexedlineset.IndexedLineSet._line_buffer = broken

    # Each time matrices are set for a named program, which program is bound
    from OpenGL.GL import glGetIntegerv, GL_CURRENT_PROGRAM
    from OpenGLContext.passes.shaderpass import VRML97ShaderProgram
    bound = []
    set_matrices = VRML97ShaderProgram.set_matrices
    def recording(self, *args, program=None, **named):
        if program:
            bound.append((int(glGetIntegerv(GL_CURRENT_PROGRAM)), int(program)))
        return set_matrices(self, *args, program=program, **named)
    VRML97ShaderProgram.set_matrices = recording

    class C(Base):
        def OnInit(self):
            lines = [basenodes.Transform(translation=(0, y, 4), children=[basenodes.Shape(
                geometry=basenodes.IndexedLineSet(
                    coord=basenodes.Coordinate(point=[(-1, 0, 0), (1, 0, 0)]),
                    coordIndex=[0, 1, -1],
                    color=basenodes.Color(color=[(0, 1, 0), (0, 1, 0)])))])
                for y in (-0.5, 0.5)]
            self.sg = basenodes.sceneGraph(children=lines + [
                basenodes.Shape(
                    appearance=basenodes.Appearance(material=basenodes.Material(
                        diffuseColor=(0, 0, 0), emissiveColor=(1, 0, 0))),
                    geometry=basenodes.Box(size=(4, 4, 4))),
            ])

    inst = C()
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    for _ in range(2):
        glfw.poll_events()
        inst.OnDraw(force=1)
    w, h = inst.getViewPort()
    px = inst.drawAndReadFrame(lambda: glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE))
    arr = np.frombuffer(bytes(px), dtype=np.uint8).reshape(h, w, 3).astype(int)
    red = int(((arr[..., 0] > 150) & (arr[..., 1] < 80)).sum())
    from OpenGLContext.passes import renderpass
    failures = [(entry.where, entry.description.splitlines()[-1])
                for entry in renderpass.FLAT.failures.summary()]
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,))
    import traceback; traceback.print_exc()
    from OpenGLContext.testing.plugin import NO_CONTEXT_STATUS
    os._exit(NO_CONTEXT_STATUS)
print('RED', red)
for current, lit in bound:
    print('BOUND', current, lit)
for where, last in failures:
    print('FAILED', where, last)
sys.stdout.flush()
os._exit(0)
'''


def test_the_shape_after_a_failed_draw_still_draws():
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120, env=dict(os.environ))
    skip_if_child_had_no_context(proc.returncode, proc.stderr)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    red = int(next(line for line in lines if line.startswith('RED')).split()[1])
    failed = [line for line in lines if line.startswith('FAILED')]
    assert failed and all('the line buffer cannot be built' in line for line in failed), (
        proc.stdout + proc.stderr)
    assert red > 1000, proc.stdout + proc.stderr
    bound = [line.split()[1:] for line in lines if line.startswith('BOUND')]
    assert bound and all(current == lit for current, lit in bound), proc.stdout
