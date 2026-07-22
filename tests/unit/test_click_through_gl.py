"""End-to-end regression for the ``pickable=False`` click-through flag (needs GL).

Runs the core-profile MRT pick path in a subprocess (GLFW), injects a click at
the viewport centre, and checks what the async readback resolves for several
occlusion arrangements:

  opaque_pickable        a plain opaque shape is selected (control).
  opaque_nonpickable     the same shape marked pickable=False is NOT selected --
                         it writes no id, so the pick returns empty.
  transparent_control    a transparent shape over an opaque one, both pickable:
                         the pick hits the (front) transparent shape.
  transparent_readthrough the front transparent shape marked pickable=False: the
                         pick reads THROUGH it to the opaque shape behind (the
                         water-surface case).

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
SCENARIO = sys.argv[1]
try:
    import glfw
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.events.mouseevents import MouseButtonEvent

    def shape(color, transparency=0.0, geometry=None, pickable=True):
        return basenodes.Shape(
            geometry=geometry or basenodes.Sphere(radius=3),
            appearance=basenodes.Appearance(
                material=basenodes.Material(diffuseColor=color,
                                            transparency=transparency)),
            pickable=pickable,
        )

    RESULT = {'hit': 'PENDING'}

    class C(Base):
        def OnInit(self):
            self.front = self.back = None
            if SCENARIO in ('opaque_pickable', 'opaque_nonpickable'):
                self.back = shape((0, 1, 1),
                                  pickable=(SCENARIO == 'opaque_pickable'))
                children = [basenodes.Transform(children=[self.back])]
            else:
                # Opaque box behind, transparent panel in front (closer to camera).
                self.back = shape((1, 0, 0), geometry=basenodes.Box(size=(6, 6, 1)))
                front_pickable = (SCENARIO == 'transparent_control')
                self.front = shape((0, 0, 1), transparency=0.5,
                                   geometry=basenodes.Box(size=(6, 6, 1)),
                                   pickable=front_pickable)
                children = [
                    basenodes.Transform(translation=(0, 0, -4), children=[self.back]),
                    basenodes.Transform(translation=(0, 0, 2), children=[self.front]),
                ]
            self.sg = basenodes.sceneGraph(children=children)
            self.contextDefinition.pickAsync = True
            self.addEventHandler('mousebutton', button=0, state=1, function=self.hit)

        def hit(self, event):
            paths = event.getObjectPaths()
            node = paths[0][-1] if (paths and paths[0]) else None
            if node is None:
                RESULT['hit'] = 'NONE'
            elif node is self.front:
                RESULT['hit'] = 'FRONT'
            elif node is self.back:
                RESULT['hit'] = 'BACK'
            else:
                RESULT['hit'] = 'OTHER'

    inst = C()
    inst.deferRedraw = True
    try:
        glfw.swap_interval(0)   # vsync-independent (don't block on frame callbacks)
    except Exception:
        pass
    w, h = inst.getViewPort()
    for i in range(24):
        glfw.poll_events()
        if 3 <= i <= 5:
            ev = MouseButtonEvent(); ev.button = 0; ev.state = 1
            ev.modifiers = (0, 0, 0); ev.pickPoint = (w // 2, h // 2)
            inst.addPickEvent(ev); inst.triggerPick()
        inst.OnDraw(force=1)

    expected = {
        'opaque_pickable': 'BACK',
        'opaque_nonpickable': 'NONE',
        'transparent_control': 'FRONT',
        'transparent_readthrough': 'BACK',
    }[SCENARIO]
    got = RESULT['hit']
    sys.stderr.write('SCENARIO=%s EXPECTED=%s GOT=%s\n' % (SCENARIO, expected, got))
    os._exit(0 if got == expected else 2)
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


@pytest.mark.parametrize('scenario', [
    'opaque_pickable',
    'opaque_nonpickable',
    'transparent_control',
    'transparent_readthrough',
])
def test_pickable_flag_click_through(scenario):
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, '-c', DRIVER, scenario],
                          capture_output=True, text=True, timeout=120, env=env)
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'click-through scenario %r resolved the wrong object\n'
        'stdout:\n%s\nstderr:\n%s' % (scenario, proc.stdout, proc.stderr))
