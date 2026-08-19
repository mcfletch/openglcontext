"""The shadow depth pass keeps its own program bound (GL, PBR core).

A caster is free to bind whatever program it needs while it draws -- an
IndexedLineSet draws through the line/unlit program and leaves the lit one
bound behind it. The depth pass uploads each caster's light-space modelview
against the *depth* program, so it has to bind that program itself rather than
trust the caster before it to have left it there: a uniform location resolved
for one program and uploaded into another writes into whatever happens to sit
at that location, and raises GL_INVALID_OPERATION when nothing does.

The scene is the shape an editor's plan view has -- a meshed ground, a drawn
line over it and markers at distinct transforms -- because the markers are what
make the wrong upload happen: two casters sharing a transform skip the upload
entirely and hide it.
"""
import os
import subprocess
import sys

import pytest

DRIVER = r'''
import os, sys
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '1'
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
os.environ['OPENGLCONTEXT_HIDDEN'] = '1'
os.environ['OPENGLCONTEXT_INSTANCING'] = '0'
try:
    import glfw
    import numpy as np
    from OpenGL import GL as gl
    from OpenGLContext import testingcontext
    from OpenGLContext.scenegraph.basenodes import (
        sceneGraph, DirectionalLight, Coordinate, IndexedLineSet)
    from OpenGLContext.scenegraph.appearance import Appearance
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    from OpenGLContext.scenegraph.shape import Shape
    from OpenGLContext.scenegraph.transform import Transform
    from OpenGLContext.passes import shaderpass

    # Record every uniform upload the depth pass makes against a program that is
    # not the one bound: that is the defect, whether or not the driver raises.
    wrong = []
    _orig = shaderpass.VRML97ShaderProgram.set_matrices
    def watched(self, modelview, projection, program=None):
        if program is not None:
            current = int(gl.glGetIntegerv(gl.GL_CURRENT_PROGRAM))
            if current != int(program):
                wrong.append((current, int(program)))
        return _orig(self, modelview, projection, program=program)
    shaderpass.VRML97ShaderProgram.set_matrices = watched

    def _quad(y):
        positions = np.array([(-4, y, -4), (4, y, -4), (4, y, 4), (-4, y, 4)], 'f')
        normals = np.array([(0, 1, 0)] * 4, 'f')
        return PBRMesh(positions=positions, normals=normals,
                       indices=np.array([0, 1, 2, 0, 2, 3], np.uint32))

    def _marker(x, z):
        return Transform(translation=(x, 1.0, z), children=[Shape(
            geometry=_quad(0.0),
            appearance=Appearance(material=PBRMaterial(baseColor=(1, 0.7, 0.2),
                                                       unlit=True)))])

    Base = testingcontext.getInteractive()

    class V(Base):
        def OnInit(self):
            self.sg = sceneGraph(children=[
                DirectionalLight(direction=(-0.3, -0.8, -0.5), intensity=1.2),
                Shape(geometry=_quad(0.0),
                      appearance=Appearance(material=PBRMaterial(
                          baseColor=(0.4, 0.6, 0.3)))),
                Shape(geometry=IndexedLineSet(
                    coord=Coordinate(point=[(-3, 2, 0), (3, 2, 0), (3, 2, 3)]),
                    coordIndex=[0, 1, 2, -1])),
                _marker(-2.0, -1.0),
                _marker(2.0, 1.5),
            ])

    v = V()
    v.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)

try:
    # Past here GL is up, so a failure is the pass's, not the environment's.
    for _ in range(3):
        glfw.poll_events()
        v.OnDraw(force=1)
    if wrong:
        sys.stderr.write('uploaded into the bound program %r instead of the '
                         'named one\n' % (wrong[:4],))
        os._exit(2)
    sys.stderr.write('clean\n')
    os._exit(0)
except SystemExit:
    raise
except BaseException:
    import traceback; traceback.print_exc()
    os._exit(2)
'''


def test_depth_pass_uploads_into_the_program_it_names():
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'the shadow depth pass uploaded a uniform into whichever program a '
        'caster left bound\nstdout:\n%s\nstderr:\n%s'
        % (proc.stdout, proc.stderr))
