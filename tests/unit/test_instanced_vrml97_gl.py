"""Stage 5 end-to-end: instancing through the VRML97 lit shader (GL, core profile).

Runs the DEFAULT core renderer (not the PBR pass), so geometry draws through the
VRML97 lighting program. N shapes share one mesh + one VRML97 Material and are
placed left-to-right; the pass must collapse them into one instanced draw where
each instance uses its own model matrix and keeps a distinct pick id. Reads the
MRT id attachment directly and checks N distinct ids at increasing x. Skips when
no usable GL context can be created.
"""
import os
import subprocess
import sys

import pytest

DRIVER = r'''
import os, sys
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ.pop('OPENGLCONTEXT_RENDERER', None)   # default VRML97 core pass, not PBR
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
os.environ['OPENGLCONTEXT_INSTANCE_MIN'] = '3'
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
N = 5
try:
    import glfw, numpy as np
    from OpenGL.GL import (
        glBindFramebuffer, glReadBuffer, glReadPixels, GL_READ_FRAMEBUFFER,
        GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1, GL_RGBA, GL_UNSIGNED_BYTE,
    )
    from OpenGLContext.passes import instancing, selection
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh

    STATE = {'calls': 0, 'ids': None}
    _od = instancing.draw_instanced_mesh
    def _cd(gpu, mvs, oids, material_indices=None):
        STATE['calls'] += 1
        return _od(gpu, mvs, oids, material_indices)
    instancing.draw_instanced_mesh = _cd

    _os = selection.SelectionMixin.submitAsyncPicks
    def _scan(self, mode, events, id_map):
        buf = self._getSelectionBuffer()
        glBindFramebuffer(GL_READ_FRAMEBUFFER, buf.fbo)
        glReadBuffer(GL_COLOR_ATTACHMENT1)
        w, h = buf.width, buf.height
        ids = (np.frombuffer(bytes(glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE)),
                             dtype='u1').reshape(h, w, 4).view('<u4').reshape(h, w))
        cents = {}
        for oid in np.unique(ids):
            if oid == 0 or oid >= (1 << 24):
                continue
            cents[int(oid)] = float(np.nonzero(ids == oid)[1].mean())
        STATE['ids'] = cents
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
    material = basenodes.Material(diffuseColor=(0, 1, 1))   # VRML97 material
    xs = [-3.0, -1.5, 0.0, 1.5, 3.0]

    def inst(x):
        return basenodes.Transform(translation=(x, 0, 0), children=[
            basenodes.Shape(geometry=quad,
                            appearance=basenodes.Appearance(material=material))])

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[inst(x) for x in xs])
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

    cents = STATE['ids'] or {}
    ordered = sorted(cents.items(), key=lambda kv: kv[1])
    increasing = all(ordered[i][1] < ordered[i + 1][1] for i in range(len(ordered) - 1))
    ok = (STATE['calls'] == 1 and len(cents) == N and increasing)
    sys.stderr.write('CALLS=%d N_IDS=%d INCREASING=%r\n' % (STATE['calls'], len(cents), increasing))
    os._exit(0 if ok else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def test_stage5_vrml97_shader_instancing():
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'Stage 5 VRML97 instancing failed (expected one instanced draw of 5 shapes '
        'with 5 distinct, left-to-right object ids)\nstdout:\n%s\nstderr:\n%s'
        % (proc.stdout, proc.stderr))
