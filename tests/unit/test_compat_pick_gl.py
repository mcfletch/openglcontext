"""Regression: a mouse pick in the DEFAULT (compatibility) profile must not
crash the render loop (needs GL).

The compatibility ``FlatPass.selectRender`` colour-id readback used the Python-2
``long()`` builtin (and a Python-2 ``cmp()`` transparent sort lived alongside it).
On Python 3 the first pick event raised ``NameError: name 'long' is not defined``
which propagated out of the draw call -- i.e. every pick crashed the loop.

The driver builds a Box in the compatibility profile, confirms GL renders one
frame, then injects a centre-of-viewport pick and renders again. A NameError in
the pick path is reported distinctly from "no usable GL context" so the bug can
never masquerade as a skip. Skips (not fails) when GL is unavailable.
"""
import subprocess
import sys

import pytest

from OpenGLContext.testing.gl_env import gl_subprocess_env

DRIVER = r'''
import os, sys
os.environ['OPENGLCONTEXT_PROFILE'] = 'compatibility'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
STATE = {'gl_ok': False, 'crashed': None, 'hit': False}
try:
    import glfw
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.events.mouseevents import MouseButtonEvent

    class C(Base):
        def OnInit(self):
            self.target = basenodes.Shape(
                geometry=basenodes.Box(size=(6, 6, 6)),
                appearance=basenodes.Appearance(
                    material=basenodes.Material(diffuseColor=(0, 1, 0))))
            self.sg = basenodes.sceneGraph(children=[
                basenodes.Transform(children=[self.target])])
            self.addEventHandler(
                'mousebutton', button=0, state=1, function=self.hit)

        def hit(self, event):
            paths = event.getObjectPaths()
            STATE['hit'] = bool(
                paths and paths[0] and paths[0][-1] is self.target)

    inst = C()
    inst.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    w, h = inst.getViewPort()
    # Warm frame(s) with no pick: proves GL actually renders here.
    for _ in range(3):
        glfw.poll_events()
        inst.OnDraw(force=1)
    STATE['gl_ok'] = True
    # Now inject a pick at the viewport centre and drive the pick path.
    for i in range(6):
        glfw.poll_events()
        ev = MouseButtonEvent(); ev.button = 0; ev.state = 1
        ev.modifiers = (0, 0, 0); ev.pickPoint = (w // 2, h // 2)
        inst.addPickEvent(ev)
        inst.OnDraw(force=1)
    STATE['crashed'] = False
except SystemExit:
    raise
except BaseException as e:
    import traceback
    if STATE['gl_ok']:
        STATE['crashed'] = repr(e)
        sys.stderr.write('PICK_CRASH %r\n' % (e,))
        traceback.print_exc()
    else:
        sys.stderr.write('NOGL %r\n' % (e,))
        os._exit(3)

sys.stderr.write('GL_OK=%r CRASHED=%r HIT=%r\n'
                 % (STATE['gl_ok'], STATE['crashed'], STATE['hit']))
if not STATE['gl_ok']:
    os._exit(3)
if STATE['crashed']:
    os._exit(2)
os._exit(0)
'''


@pytest.mark.gl_context(profile='compatibility')
def test_compatibility_profile_pick_does_not_crash():
    """Declared, so a driver that offers only a core profile passes this over
    rather than failing it: there is nothing here for such a driver to run."""
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120,
                          env=gl_subprocess_env())
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'compatibility-profile pick crashed the render loop\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
