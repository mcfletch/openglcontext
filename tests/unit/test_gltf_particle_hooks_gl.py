"""A fire tagged in a file really burns (GL, PBR core).

A document carrying nothing but an empty node and an ``OGLC_hook`` tag saying
``fire`` is loaded and drawn for a second of frames; the flame is there, warm
and above where the node stands. The same document with the tag left unread
draws nothing there. No application code registers anything -- the kind ships
bound.

What the tag makes is asserted without a window in
``test_gltf_particle_hooks.py``; this is the claim that needs one.
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
os.environ['OPENGLCONTEXT_GLTF_HOOKS'] = sys.argv[1]
try:
    import glfw
    import numpy as np
    from OpenGL import GL as gl
    from OpenGLContext import testingcontext
    from OpenGLContext.events import systemtime
    from OpenGLContext.loaders import gltf
    from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
    from OpenGLContext.scenegraph.basenodes import sceneGraph, Viewpoint
    from OpenGLContext.video.clock import FixedStepClock

    # A second of flame in thirty frames, whatever the machine's speed.
    systemtime.setTimeSource(FixedStepClock(fps=30))
    scene = gltf.load_gltf(write_glb(SceneNode(
        name='torch', hook={'kind': 'fire', 'seed': 7})))

    Base = testingcontext.getInteractive()

    class V(Base):
        def OnInit(self):
            self.scene = scene
            self.sg = sceneGraph(children=[
                Viewpoint(position=(0, 1.0, 5.0)),
                scene.group,
            ])

    v = V(size=(160, 160))
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
    for _ in range(30):
        glfw.poll_events()
        v.OnDraw(force=1)
        systemtime.timeSource().advance()
    width, height = v.getViewPort()
    raw = gl.glReadPixels(0, 0, width, height, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
    image = np.frombuffer(raw, np.uint8).reshape(height, width, 3).astype(int)
    warm = (image[..., 0] > 120) & (image[..., 0] > image[..., 2] + 60)
    sys.stdout.write('%d\n' % int(warm.sum()))
    sys.stdout.flush()
    os._exit(0)
except BaseException:
    import traceback; traceback.print_exc()
    os._exit(2)
'''


def _warm_pixels(hooks_on):
    proc = subprocess.run([sys.executable, '-c', DRIVER, '1' if hooks_on else '0'],
                          capture_output=True, text=True, timeout=180,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, proc.stderr
    return int(proc.stdout.strip().splitlines()[-1])


def test_a_tagged_empty_burns():
    assert _warm_pixels(hooks_on=True) > 150


def test_the_same_file_with_tags_unread_does_not():
    assert _warm_pixels(hooks_on=False) == 0
