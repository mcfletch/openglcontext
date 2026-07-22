"""Regression: unlit geometry is selectable via MRT picking (needs GL).

Two shaders historically hard-coded object-id 0, making anything drawn unlit
silently non-pickable:

  pbr_unlit   a KHR_materials_unlit PBRMaterial (common in real glTF assets),
              drawn by the PBR program's unlit branch.
  pointset    a PointSet with no per-vertex colour, drawn by the shared unlit
              program -- which also requires the object id to follow the
              program switch away from the lit program.

Each scenario clicks the geometry at the viewport centre and asserts the async
readback resolves its path. Skips (not fails) with no usable GL context.
"""
import os
import subprocess
import sys

import pytest

DRIVER = r'''
import os, sys
SCENARIO = sys.argv[1]
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
if SCENARIO == 'pbr_unlit':
    os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
try:
    import glfw
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.events.mouseevents import MouseButtonEvent

    def build():
        if SCENARIO == 'pbr_unlit':
            from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
            shape = basenodes.Shape(
                geometry=basenodes.Box(size=(6, 6, 6)),
                appearance=basenodes.Appearance(
                    material=PBRMaterial(unlit=True, baseColor=(0, 1, 1))))
        else:  # a big point at the origin (projects to, and covers, screen centre)
            # Coloured so it renders through point_program at a real point size;
            # this exercises the object-id following the program switch away from
            # the lit program (the fix that makes non-lit geometry pickable).
            shape = basenodes.Shape(
                geometry=basenodes.PointSet(
                    coord=basenodes.Coordinate(point=[(0, 0, 0)]),
                    color=basenodes.Color(color=[(0, 1, 1)]), size=40.0))
        return shape

    RESULT = {'hit': False}

    class C(Base):
        def OnInit(self):
            self.target = build()
            self.sg = basenodes.sceneGraph(children=[
                basenodes.Transform(children=[self.target])])
            self.contextDefinition.pickAsync = True
            self.addEventHandler('mousebutton', button=0, state=1, function=self.hit)

        def hit(self, event):
            paths = event.getObjectPaths()
            RESULT['hit'] = bool(paths and paths[0] and paths[0][-1] is self.target)

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
    sys.stderr.write('SCENARIO=%s HIT=%r\n' % (SCENARIO, RESULT['hit']))
    os._exit(0 if RESULT['hit'] else 2)
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


@pytest.mark.parametrize('scenario', ['pbr_unlit', 'pointset'])
def test_unlit_geometry_is_pickable(scenario):
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, '-c', DRIVER, scenario],
                          capture_output=True, text=True, timeout=120, env=env)
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'unlit %r geometry was not pickable\n'
        'stdout:\n%s\nstderr:\n%s' % (scenario, proc.stdout, proc.stderr))
