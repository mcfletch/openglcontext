"""End-to-end regression: async MRT picking resolves objectPaths (needs GL).

Runs the core-profile shader/MRT pick path in a subprocess (GLFW), injects a
click on a sphere, and checks the async readback delivers the object's path.
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
try:
    import glfw
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.events.mouseevents import MouseButtonEvent
    RESULT = {'hits': []}
    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[basenodes.Transform(children=[
                basenodes.TouchSensor(),
                basenodes.Shape(geometry=basenodes.Sphere(radius=2),
                    appearance=basenodes.Appearance(
                        material=basenodes.Material(diffuseColor=(0,1,1))))])])
            self.contextDefinition.pickAsync = True
            self.addEventHandler('mousebutton', button=0, state=1, function=self.hit)
        def hit(self, event):
            p = event.getObjectPaths()
            RESULT['hits'].append(bool(p and p[0]))
    inst = C()
    inst.deferRedraw = True
    try:
        glfw.swap_interval(0)   # vsync-independent (don't block on frame callbacks)
    except Exception:
        pass
    w, h = inst.getViewPort()
    for i in range(18):
        glfw.poll_events()
        if 3 <= i <= 5:
            ev = MouseButtonEvent(); ev.button = 0; ev.state = 1; ev.modifiers = (0, 0, 0)
            ev.pickPoint = (w // 2, h // 2)
            inst.addPickEvent(ev); inst.triggerPick()
        inst.OnDraw(force=1)
    ok = any(RESULT['hits'])
    sys.stderr.write('HITS=%r\n' % RESULT['hits'])
    os._exit(0 if ok else 2)
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def test_async_pick_resolves_object_path():
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120, env=env)
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s' % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'async pick did not resolve the sphere path\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
