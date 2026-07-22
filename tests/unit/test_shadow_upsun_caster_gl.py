"""An up-sun caster must survive the directional cascade's near plane (GL regression).

A directional cascade fits its ortho volume to the *camera* frustum (the
receivers it can see). A caster sitting between the light and that frustum -- a
cella wall up-sun of a colonnade column -- falls in front of the near plane and
is clipped out of the depth pass, so the shadow it should throw onto the column
vanishes and the column pops to full sunlight as you walk.

This locks the fix: ``directional_cascade`` is given the caster-pool bounds and
pushes its near plane toward the light so up-sun casters stay in the shadow map.
The test drives a real GL pipeline and checks, for the cascade that actually
covers the receiver, that the point on the caster casting onto it is inside the
cascade WITH the shipped bounds and clipped by the near plane WITHOUT them --
proving both that the bug is real here and that the fix cures it.

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
os.environ['OPENGLCONTEXT_SHADOWS'] = '1'
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
os.environ['OPENGLCONTEXT_SHADOW_CASCADES'] = '3'   # tight near cascade, deterministic
try:
    import numpy as np
    import glfw
    from OpenGLContext.passes import shadowmath

    LIGHT = np.array([-0.62, -0.42, -0.28]); LIGHT /= np.linalg.norm(LIGHT)
    UP_SUN = 6.0
    RECEIVER = np.array([0.0, 0.2, 0.0])          # column base (a shadow receiver)
    CASTER_PT = RECEIVER - LIGHT * UP_SUN         # point on the wall that shadows it

    CAPTURED = []
    _dc = shadowmath.directional_cascade
    def _dc_wrap(light_dir, corners_world, texel_snap=0, caster_bounds=None):
        view, proj = _dc(light_dir, corners_world, texel_snap=texel_snap,
                         caster_bounds=caster_bounds)
        CAPTURED.append((np.asarray(corners_world, dtype='d'),
                         np.asarray(view, dtype='d'), np.asarray(proj, dtype='d'),
                         np.asarray(light_dir, dtype='d'), caster_bounds is not None))
        return view, proj
    shadowmath.directional_cascade = _dc_wrap

    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes

    floor = basenodes.Shape(
        geometry=basenodes.Box(size=(20, 0.2, 20)),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(0.8, 0.8, 0.8))))
    column = basenodes.Shape(
        geometry=basenodes.Box(size=(0.6, 4, 0.6)),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(0.7, 0.7, 0.7))))
    # A tall wall centred on the up-sun caster point.
    wall = basenodes.Shape(
        geometry=basenodes.Box(size=(0.4, 5, 5)),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(0.6, 0.6, 0.6))))

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[
                basenodes.Transform(translation=(0, 0, 0), children=[floor]),
                basenodes.Transform(translation=(0, 2, 0), children=[column]),
                basenodes.Transform(translation=tuple(float(x) for x in CASTER_PT),
                                    children=[wall]),
                basenodes.DirectionalLight(direction=tuple(float(x) for x in LIGHT),
                                           intensity=1.0, castShadows=True),
            ])

    ctx = C(); ctx.deferRedraw = True
    try:
        plat = ctx.getViewPlatform()
        plat.setPosition((0.0, 2.0, 2.0))          # close, so the column is a tight near cascade
    except Exception:
        pass
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    for i in range(4):
        glfw.poll_events()
        ctx.OnDraw(force=1)

    if not CAPTURED:
        sys.stderr.write('NOGL no directional cascades captured\n')
        os._exit(3)

    def ndc(view, proj, pt):
        clip = np.append(pt, 1.0) @ view @ proj
        return clip[:3] / clip[3]

    def inside(c):
        return bool(np.all(np.abs(c) <= 1.0))

    cured = False   # a cascade covers the receiver, keeps the caster WITH bounds,
                    # and would clip it (by the near plane) WITHOUT bounds
    for corners, view, proj, light, had_bounds in CAPTURED:
        if not had_bounds:
            continue
        if not inside(ndc(view, proj, RECEIVER)):
            continue                                   # receiver not in this cascade
        if not inside(ndc(view, proj, CASTER_PT)):
            continue                                   # fix didn't cover the caster here
        v0, p0 = _dc(light, corners, texel_snap=0)     # same cascade, no caster bounds
        c0 = ndc(v0, p0, CASTER_PT)
        if abs(c0[0]) <= 1.0 and abs(c0[1]) <= 1.0 and c0[2] < -1.0:
            cured = True                               # in XY, clipped by near -> exactly the bug
            break

    sys.stderr.write('cured=%r ncascades=%d\n' % (cured, len(CAPTURED)))
    os._exit(0 if cured else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def test_up_sun_caster_survives_near_plane():
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'an up-sun caster was clipped out of the directional shadow cascade\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
