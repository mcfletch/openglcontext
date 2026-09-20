"""A lake tagged in a file really moves (GL, PBR core).

What the tag is for, end to end: a document carrying nothing but geometry, a
material and an ``OGLC_hook`` custom property is loaded, and the surface it
describes is somewhere else a moment after ``scene.advance``. No application
code registers anything -- the ``water`` kind ships bound -- and nothing is
re-uploaded to move it.

The reading is asserted without a window in ``test_gltf_water_hook.py``; this is
the claim that needs one.
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
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
os.environ['OPENGLCONTEXT_HIDDEN'] = '1'
try:
    import glfw
    import numpy as np
    from OpenGL import GL as gl
    from OpenGLContext import testingcontext
    from OpenGLContext.loaders import gltf
    from OpenGLContext.loaders.gltf.writer import write_glb
    from OpenGLContext.scenegraph.basenodes import sceneGraph, Viewpoint
    from OpenGLContext.scenegraph.water import water_surface

    def tagged_document():
        """A meshed sheet whose material says, in the file, that it is water.

        Built flat and unmoving -- everything that makes it water comes back
        off the tag when the document is read.
        """
        sheet = water_surface(-12.0, 12.0, -12.0, 12.0, level=0.0,
                              resolution=65, on_gpu=False)
        # Bright and unlit, so the picture shows the shape of the surface
        # rather than what a dark material reflects.
        sheet.material.baseColor = (0.9, 0.9, 0.9)
        sheet.material.emissiveColor = (0.6, 0.7, 0.9)
        sheet.material.roughness = 0.3
        sheet.material.transparency = 0.0
        sheet.material.alphaMode = 'OPAQUE'
        sheet.material.extras = {'OGLC_hook': {'kind': 'water',
                                               'style': 'choppy'}}
        return write_glb(sheet)

    scene = gltf.load_gltf(tagged_document())
    if scene.hook_data.get('water') is None:
        sys.stderr.write('the tag never reached the water hook\n')
        os._exit(6)

    Base = testingcontext.getInteractive()

    class V(Base):
        def OnInit(self):
            self.scene = scene
            self.sg = sceneGraph(children=[
                Viewpoint(position=(0, 6, 16), orientation=(1, 0, 0, -0.32)),
                scene.group,
            ])

    v = V(size=(240, 240))
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
    def frame():
        glfw.poll_events()
        v.OnDraw(force=1)
        width, height = v.getViewPort()
        raw = gl.glReadPixels(0, 0, width, height, gl.GL_RGB,
                              gl.GL_UNSIGNED_BYTE)
        return np.frombuffer(raw, np.uint8).reshape(height, width, 3).astype(int)

    def settled():
        """Draw until two consecutive frames agree, and return that picture.

        The analytic-sky IBL converges over several frames, and reading the
        colour buffer after OnDraw has swapped returns the frame before it, so
        a single read after changing anything still shows the old state.
        """
        previous = frame()
        for _ in range(30):
            current = frame()
            if np.array_equal(current, previous):
                return current
            previous = current
        sys.stderr.write('the picture never settled\n')
        os._exit(5)

    if scene.advance(0.0) is not True:
        sys.stderr.write('a choppy lake reported nothing to redraw\n')
        os._exit(7)
    still = settled()
    # The same moment twice: a world rendered twice is the same world.
    scene.advance(0.0)
    again = frame()
    if np.abs(still - again).max() > 2:
        sys.stderr.write('the same moment drew differently\n')
        os._exit(4)
    # A second later it has moved, and nothing was re-uploaded to do it.
    scene.advance(0.9)
    later = settled()
    moved = int((np.abs(still - later).sum(axis=2) > 12).sum())
    sys.stderr.write('pixels that moved: %d\n' % moved)
    if moved < 200:
        sys.stderr.write('the wave did not move\n')
        os._exit(2)
    os._exit(0)
except SystemExit:
    raise
except BaseException:
    import traceback; traceback.print_exc()
    os._exit(2)
'''


def _run():
    return subprocess.run([sys.executable, '-c', DRIVER], capture_output=True,
                          text=True, timeout=180, env=dict(os.environ))


def _checked(proc):
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode != 6, (
        'the OGLC_hook tag in the document never reached the water hook\n%s'
        % proc.stderr)
    assert proc.returncode != 7, (
        'advance() reported nothing to redraw for a choppy lake\n%s'
        % proc.stderr)
    return proc


def test_a_tagged_lake_moves_between_two_advances():
    proc = _checked(_run())
    assert proc.returncode != 2, (
        'the surface a file tagged as water did not move when the scene was '
        'advanced\n%s' % proc.stderr)


def test_the_same_moment_draws_the_same_water():
    proc = _checked(_run())
    assert proc.returncode != 5, (
        'the picture never stopped changing at a fixed moment\n%s' % proc.stderr)
    assert proc.returncode != 4, (
        'the same moment drew two different pictures\n%s' % proc.stderr)
