"""Stage 3 end-to-end: opportunistic collapse of distinct-node, identical-content
geometry into one instanced draw (GL, PBR core).

Each instance gets its OWN PBRMesh node (not a shared one) with identical vertex
arrays, plus its own material colour. With content-collapse on (default), they
must still batch into a single instanced draw, each rendering its own colour and
keeping a distinct pick id. Skips when no usable GL context can be created.
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
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
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
            ys, xs = np.nonzero(ids == oid)
            byid[int(oid)] = (float(xs.mean()),
                              tuple(int(np.median(col[ys, xs, c])) for c in range(3)))
        STATE['byid'] = byid
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0)
        return _os(self, mode, events, id_map)
    selection.SelectionMixin.submitAsyncPicks = _scan

    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.events.mouseevents import MouseButtonEvent

    POS = [(-.35, -.35, 0), (.35, -.35, 0), (.35, .35, 0), (-.35, .35, 0)]
    IDX = [0, 1, 2, 0, 2, 3]
    xs = [-2.4, -0.8, 0.8, 2.4]

    def instance(x, color):
        # A DISTINCT mesh node per instance, but identical vertex content.
        m = PBRMesh(positions=POS, normals=[(0, 0, 1)] * 4, indices=IDX)
        return basenodes.Transform(translation=(x, 0, 0), children=[
            basenodes.Shape(geometry=m,
                appearance=basenodes.Appearance(
                    material=PBRMaterial(unlit=True, baseColor=color)))])

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[
                instance(x, c) for x, c in zip(xs, COLORS)])
            self.contextDefinition.pickAsync = True
            self.addEventHandler('mousebutton', button=0, state=1, function=lambda e: None)

    ctx = C(); ctx.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    w, h = ctx.getViewPort()
    for i in range(20):
        glfw.poll_events()
        STATE['calls'] = 0
        if 3 <= i <= 5:
            ev = MouseButtonEvent(); ev.button = 0; ev.state = 1
            ev.modifiers = (0, 0, 0); ev.pickPoint = (w // 2, h // 2)
            ctx.addPickEvent(ev); ctx.triggerPick()
        ctx.OnDraw(force=1)

    byid = STATE['byid'] or {}
    ordered = sorted(byid.values(), key=lambda v: v[0])
    got = [rgb for _x, rgb in ordered]
    exp = [tuple(255 * c for c in col) for col in COLORS]
    near = lambda a, b: all(abs(x - y) <= 40 for x, y in zip(a, b))
    ok = (STATE['calls'] == 1 and len(byid) == len(COLORS)
          and all(near(g, e) for g, e in zip(got, exp)))
    sys.stderr.write('CALLS=%d N_IDS=%d COLORS=%r\n' % (STATE['calls'], len(byid), got))
    os._exit(0 if ok else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def test_stage3_distinct_nodes_collapse():
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'Stage 3 collapse failed (expected distinct identical-content nodes to '
        'batch into one instanced draw)\nstdout:\n%s\nstderr:\n%s'
        % (proc.stdout, proc.stderr))
