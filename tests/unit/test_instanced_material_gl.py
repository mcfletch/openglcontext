"""Stage 2 end-to-end: per-instance material factors in one instanced draw (GL).

Builds N shapes that SHARE one PBRMesh geometry and one (empty) texture set but
carry DIFFERENT unlit materials (distinct baseColor each). Renders the PBR pass
with picking warm, reads both the colour and object-id MRT attachments, and
asserts:

  * one instanced draw covers the whole field (material-array path), not N draws;
  * each instance renders with ITS OWN baseColor (per-instance material index into
    the material array), left-to-right;
  * each instance keeps a distinct object id (still pickable).

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
os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
os.environ['OPENGLCONTEXT_INSTANCE_MIN'] = '3'
# baseColor per instance -> expected sRGB8 (unlit emits linearToSRGB(baseColor);
# 0 and 1 are fixed points of the sRGB curve, so primaries map cleanly).
COLORS = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)]
try:
    import glfw, numpy as np
    from OpenGL.GL import (
        glBindFramebuffer, glReadBuffer, glReadPixels, GL_READ_FRAMEBUFFER,
        GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1, GL_RGBA, GL_UNSIGNED_BYTE,
    )
    from OpenGLContext.passes import instancing, selection
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

    STATE = {'calls': 0, 'byid': None}
    _od = instancing.draw_instanced_mesh
    def _cd(gpu, mvs, oids, material_indices=None):
        STATE['calls'] += 1
        return _od(gpu, mvs, oids, material_indices)
    instancing.draw_instanced_mesh = _cd

    _os = selection.SelectionMixin.submitAsyncPicks
    def _scan(self, mode, events, id_map):
        buf = self._getSelectionBuffer()
        glBindFramebuffer(GL_READ_FRAMEBUFFER, buf.fbo)
        w, h = buf.width, buf.height
        glReadBuffer(GL_COLOR_ATTACHMENT1)
        ids = (np.frombuffer(bytes(glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE)),
                             dtype='u1').reshape(h, w, 4).view('<u4').reshape(h, w))
        glReadBuffer(GL_COLOR_ATTACHMENT0)
        col = np.frombuffer(bytes(glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE)),
                            dtype='u1').reshape(h, w, 4)
        byid = {}
        for oid in np.unique(ids):
            if oid == 0 or oid >= (1 << 24):
                continue
            mask = ids == oid
            ys, xs = np.nonzero(mask)
            # dominant colour of this instance (median of its pixels)
            rgb = tuple(int(np.median(col[ys, xs, c])) for c in range(3))
            byid[int(oid)] = (float(xs.mean()), rgb)
        STATE['byid'] = byid
        glReadBuffer(GL_COLOR_ATTACHMENT0)
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0)
        return _os(self, mode, events, id_map)
    selection.SelectionMixin.submitAsyncPicks = _scan

    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.events.mouseevents import MouseButtonEvent

    quad = PBRMesh(
        positions=[(-.35, -.35, 0), (.35, -.35, 0), (.35, .35, 0), (-.35, .35, 0)],
        normals=[(0, 0, 1)] * 4, indices=[0, 1, 2, 0, 2, 3])
    xs = [-2.4, -0.8, 0.8, 2.4]

    def inst(x, color):
        return basenodes.Transform(translation=(x, 0, 0), children=[
            basenodes.Shape(geometry=quad,   # shared geometry, DIFFERENT material
                appearance=basenodes.Appearance(
                    material=PBRMaterial(unlit=True, baseColor=color)))])

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[
                inst(x, c) for x, c in zip(xs, COLORS)])
            self.contextDefinition.pickAsync = True
            self.addEventHandler('mousebutton', button=0, state=1, function=lambda e: None)

    ctx = C(); ctx.deferRedraw = True
    try:
        glfw.swap_interval(0)   # vsync-independent: don't block on frame callbacks
    except Exception:
        pass
    w, h = ctx.getViewPort()
    for i in range(20):
        glfw.poll_events()
        STATE['calls'] = 0   # count instanced draws for THIS frame (expect one)
        if 3 <= i <= 5:
            ev = MouseButtonEvent(); ev.button = 0; ev.state = 1
            ev.modifiers = (0, 0, 0); ev.pickPoint = (w // 2, h // 2)
            ctx.addPickEvent(ev); ctx.triggerPick()
        ctx.OnDraw(force=1)

    byid = STATE['byid'] or {}
    ordered = sorted(byid.values(), key=lambda v: v[0])   # left-to-right
    got_colors = [rgb for _x, rgb in ordered]
    exp = [tuple(255 * c for c in col) for col in COLORS]

    def near(a, b, tol=40):
        return all(abs(x - y) <= tol for x, y in zip(a, b))

    ok = (STATE['calls'] == 1 and len(byid) == len(COLORS)
          and all(near(g, e) for g, e in zip(got_colors, exp)))
    sys.stderr.write('CALLS=%d N_IDS=%d COLORS=%r EXP=%r\n'
                     % (STATE['calls'], len(byid), got_colors, exp))
    os._exit(0 if ok else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def test_stage2_per_instance_material_factors():
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'Stage 2 per-instance materials failed (expected one instanced draw with '
        'four distinctly-coloured, individually-pickable instances)\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
