"""Cluster culling must draw exactly the same instances as per-object culling (GL).

Cluster culling (OPENGLCONTEXT_INSTANCE_CLUSTER_CULL=1) is a cost optimization of
the pass's per-object frustum filter, not a change in what is visible. This renders
a large field of spheres -- some on-screen, many off to one side -- and captures the
set of instance object-ids handed to the instanced draw in the final frame, once
with cluster culling OFF and once ON. The two sets must be identical (equivalence),
and must be a strict subset of all instances (so off-screen culling actually
happened and the test is meaningful).

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
# argv[1] = '1' to enable cluster culling, '0' to use the per-object filter.
if sys.argv[1] == '1':
    os.environ['OPENGLCONTEXT_INSTANCE_CLUSTER_CULL'] = '1'
else:
    os.environ.pop('OPENGLCONTEXT_INSTANCE_CLUSTER_CULL', None)
try:
    import glfw
    from OpenGLContext.passes import instancing

    STATE = {'oids': None}
    _od = instancing.draw_instanced_mesh
    def _cd(gpu, mvs, oids, material_indices=None, **named):
        # Accumulate every instance drawn this frame (reset each frame below).
        STATE['oids'].extend(int(o) for o in oids)
        return _od(gpu, mvs, oids, material_indices)
    instancing.draw_instanced_mesh = _cd

    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.events.mouseevents import MouseButtonEvent

    material = basenodes.Material(diffuseColor=(0.3, 0.6, 1.0))
    # A 20x20 grid in the xy plane; the far half (large +x) sits outside the view.
    kids = []
    for gx in range(20):
        for gy in range(20):
            x = -6.0 + gx * 0.6      # gx>=20 would be off-screen; big +x is culled
            y = -6.0 + gy * 0.6
            kids.append(basenodes.Transform(translation=(x + 40.0 * (gx // 10), y, 0),
                children=[basenodes.Shape(geometry=basenodes.Sphere(radius=0.2),
                    appearance=basenodes.Appearance(material=material))]))

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=kids)
            self.contextDefinition.pickAsync = True
            self.addEventHandler('mousebutton', button=0, state=1, function=lambda e: None)

    ctx = C(); ctx.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    w, h = ctx.getViewPort()
    for i in range(8):
        glfw.poll_events()
        STATE['oids'] = []
        if 3 <= i <= 5:
            ev = MouseButtonEvent(); ev.button = 0; ev.state = 1
            ev.modifiers = (0, 0, 0); ev.pickPoint = (w // 2, h // 2)
            ctx.addPickEvent(ev); ctx.triggerPick()
        ctx.OnDraw(force=1)

    drawn = sorted(set(STATE['oids']))
    sys.stderr.write('TOTAL=%d DRAWN=%d\n' % (len(kids), len(drawn)))
    # Emit the drawn id set on stdout for the parent to compare across runs.
    sys.stdout.write(repr((len(kids), drawn)))
    sys.stdout.flush(); sys.stderr.flush()   # os._exit does not flush stdio
    os._exit(0)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def _run(flag):
    return subprocess.run([sys.executable, '-c', DRIVER, flag],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))


def test_cluster_cull_matches_per_object_cull():
    off = _run('0')
    if off.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % off.stderr.strip().splitlines()[-1:])
    on = _run('1')
    assert off.returncode == 0 and on.returncode == 0, (
        'driver failed\noff:\n%s\non:\n%s' % (off.stderr, on.stderr))
    total_off, drawn_off = eval(off.stdout)
    total_on, drawn_on = eval(on.stdout)
    # Equivalence: cluster culling draws exactly the per-object-culled set.
    assert drawn_on == drawn_off, (
        'cluster cull drew a different instance set than per-object cull\n'
        'off=%r\non=%r' % (drawn_off, drawn_on))
    # Meaningful: some instances were off-screen and culled by both paths.
    assert 0 < len(drawn_off) < total_off, (
        'expected some instances culled (drawn %d of %d)'
        % (len(drawn_off), total_off))
