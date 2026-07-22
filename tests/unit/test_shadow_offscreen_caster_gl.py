"""A caster outside the camera frustum must still cast shadows (GL regression).

Walking forward in a scene, geometry behind the camera leaves the view frustum.
Shadow casters must NOT be culled by the CAMERA frustum -- an object behind the
camera can still cast a shadow onto geometry you can see (the parthenon columns
behind you shadowing the floor in front). The shadow depth pass was fed the
camera-frustum-culled render set, so those casters vanished from the shadow maps
and their shadows popped out of existence.

This locks the fix: a caster placed behind the camera is ABSENT from the
camera-visible set the colour pass draws, but PRESENT in the shadow caster pool
(what the depth pass considers, before per-light frustum culling).

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
try:
    import glfw
    from OpenGLContext.passes.shadowmixin import ShadowMapMixin

    SEEN = {'visible': set(), 'pool': set()}

    # The set handed to the shadow pass = the camera-visible render set.
    _rsm = ShadowMapMixin.renderShadowMaps
    def _rsm_wrap(self, toRender):
        SEEN['visible'].update(id(r[4][-1]) for r in toRender)
        return _rsm(self, toRender)
    ShadowMapMixin.renderShadowMaps = _rsm_wrap

    # The pool _cullOccluders receives = every candidate caster (pre light-cull).
    _cull = ShadowMapMixin._cullOccluders
    def _cull_wrap(self, toRender, light_view, light_proj):
        SEEN['pool'].update(id(r[4][-1]) for r in toRender)
        return _cull(self, toRender, light_view, light_proj)
    ShadowMapMixin._cullOccluders = _cull_wrap

    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes

    # Camera default looks down -Z from +Z. Visible content sits near the origin;
    # the caster is far behind the camera (large +Z), so it is camera-frustum
    # culled but must still be a shadow caster.
    receiver = basenodes.Shape(
        geometry=basenodes.Box(size=(20, 0.2, 20)),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(0.8, 0.8, 0.8))))
    caster = basenodes.Shape(
        geometry=basenodes.Box(size=(2, 2, 2)),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(0.7, 0.2, 0.2))))
    CASTER_ID = id(caster)
    RECEIVER_ID = id(receiver)

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[
                basenodes.Transform(translation=(0, -1, 0), children=[receiver]),
                basenodes.Transform(translation=(0, 1, 40), children=[caster]),  # behind camera
                basenodes.DirectionalLight(direction=(0.2, -1, 0.1), intensity=1.0,
                                           castShadows=True),
            ])

    ctx = C(); ctx.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    for i in range(4):
        glfw.poll_events()
        ctx.OnDraw(force=1)

    caster_visible = CASTER_ID in SEEN['visible']
    caster_in_pool = CASTER_ID in SEEN['pool']
    receiver_in_pool = RECEIVER_ID in SEEN['pool']
    sys.stderr.write('caster_visible=%r caster_in_pool=%r receiver_in_pool=%r\n'
                     % (caster_visible, caster_in_pool, receiver_in_pool))
    # Precondition: the caster really is behind the camera (not in the visible set).
    # Fix: it is nonetheless in the shadow caster pool.
    ok = (receiver_in_pool and (not caster_visible) and caster_in_pool)
    os._exit(0 if ok else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def test_offscreen_caster_still_in_shadow_pool():
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'a caster behind the camera was dropped from the shadow pass\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
