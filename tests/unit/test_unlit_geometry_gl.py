"""Geometry with no per-vertex colours draws, and draws in its material's colour.

Two things a caller has every right to expect of
``Shape(geometry=IndexedLineSet(...), appearance=Appearance(material=...))`` --
and of a ``PointSet`` said the same way: that it appears, and that it is the
colour the material says. A route drawn on an editor's map, a wireframe over a
model and a measuring line are all this shape, and all of them are one geometry
node and one material.

The scene is rendered for real and the pixels counted, because "the draw call
was issued" is not the same claim: the unlit program reads position from a
different attribute location than the line and point programs do, so geometry
can be submitted in full and land entirely at the origin.
"""
import os
import subprocess
import sys

import pytest

_DRIVER = r'''
import os, sys
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
os.environ['OPENGLCONTEXT_HIDDEN'] = '1'
try:
    import glfw
    import numpy as np
    from OpenGL import GL as gl
    from OpenGLContext import testingcontext
    from OpenGLContext.scenegraph.basenodes import (
        sceneGraph, Coordinate, IndexedLineSet, PointSet, Viewpoint)
    from OpenGLContext.scenegraph.appearance import Appearance
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    from OpenGLContext.scenegraph.shape import Shape

    COLOUR = (1.0, 0.2, 0.6)
    Base = testingcontext.getInteractive()

    class V(Base):
        def OnInit(self):
            points = [(-4.0, 0.0, 0.0), (4.0, 0.0, 0.0)]
            if os.environ.get('GEOMETRY') == 'points':
                geometry = PointSet(coord=Coordinate(point=points),
                                    color=None, size=9.0)
            else:
                geometry = IndexedLineSet(coord=Coordinate(point=points),
                                          coordIndex=[0, 1, -1], color=None)
            self.sg = sceneGraph(children=[
                Viewpoint(position=(0, 0, 12)),
                Shape(geometry=geometry,
                      appearance=Appearance(material=PBRMaterial(
                          baseColor=COLOUR, emissiveColor=COLOUR, unlit=True))),
            ])

    v = V(size=(240, 240))
    v.deferRedraw = True
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)

try:
    for _ in range(4):
        glfw.poll_events()
        v.OnDraw(force=1)
    width, height = v.getViewPort()
    pixels = gl.glReadPixels(0, 0, width, height, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
    frame = np.frombuffer(pixels, np.uint8).reshape(height, width, 3).astype(int)
    lit = frame.sum(axis=2) > 40
    columns = np.flatnonzero(lit.any(axis=0))
    spread = (int(columns[-1] - columns[0]) if len(columns) else 0)
    sys.stderr.write('lit pixels %d spread %d of %d\n'
                     % (int(lit.sum()), spread, width))
    # Both ends of the geometry are well off the middle of the view, so a
    # spread of nothing means every vertex landed at the origin -- which is
    # what a position bound to the attribute the shader does not read gives.
    if not lit.any() or spread < width // 3:
        sys.stderr.write('the geometry did not draw where it was put\n')
        os._exit(2)
    drawn = frame[lit]
    wanted = np.asarray([c * 255 for c in COLOUR])
    # The line is the only thing in the frame, so every lit pixel is it.
    off = np.abs(drawn.mean(axis=0) - wanted).max()
    sys.stderr.write('mean %s wanted %s\n' % (drawn.mean(axis=0), wanted))
    if off > 40:
        sys.stderr.write('the line is not its material colour\n')
        os._exit(4)
    os._exit(0)
except SystemExit:
    raise
except BaseException:
    import traceback; traceback.print_exc()
    os._exit(2)
'''


def _run(geometry):
    return subprocess.run([sys.executable, '-c', _DRIVER], capture_output=True,
                          text=True, timeout=120,
                          env={**os.environ, 'GEOMETRY': geometry})


@pytest.mark.parametrize('geometry', ['lines', 'points'])
def test_colourless_geometry_is_drawn(geometry):
    proc = _run(geometry)
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode != 2, (
        '%s with no per-vertex colours did not draw where it was put\n%s'
        % (geometry, proc.stderr))


@pytest.mark.parametrize('geometry', ['lines', 'points'])
def test_colourless_geometry_takes_its_material_colour(geometry):
    proc = _run(geometry)
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        '%s was not drawn in its material colour\n%s'
        % (geometry, proc.stderr))
