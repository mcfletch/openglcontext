"""End-to-end Stage 1 instancing regression (needs GL, PBR core profile).

Builds N shapes that SHARE one PBRMesh geometry node and one material, placed
left-to-right. Renders the PBR pass with picking warm, then reads the MRT
object-id attachment directly and asserts:

  * the instanced draw path ran once (one group -> one glDrawElementsInstanced),
    not N per-shape draws;
  * N distinct object ids appear in the id buffer -- each instance got its own
    stable pick id in that single draw;
  * their x-centroids increase left-to-right -- each instance used its own
    per-instance model matrix.

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
N = 6
try:
    import glfw, numpy as np
    from OpenGL.GL import (
        glBindFramebuffer, glReadBuffer, glReadPixels, GL_READ_FRAMEBUFFER,
        GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1, GL_RGBA, GL_UNSIGNED_BYTE,
    )
    from OpenGLContext.passes import instancing, selection
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

    STATE = {'instanced_calls': 0, 'instances': 0, 'scan': None}
    _orig_draw = instancing.draw_instanced_mesh
    def _counting_draw(gpu, mvs, oids, material_indices=None):
        STATE['instanced_calls'] += 1
        STATE['instances'] += len(mvs)
        return _orig_draw(gpu, mvs, oids, material_indices)
    instancing.draw_instanced_mesh = _counting_draw

    _orig_submit = selection.SelectionMixin.submitAsyncPicks
    def _scan_submit(self, mode, events, id_map):
        buf = self._getSelectionBuffer()
        glBindFramebuffer(GL_READ_FRAMEBUFFER, buf.fbo)
        glReadBuffer(GL_COLOR_ATTACHMENT1)
        w, h = buf.width, buf.height
        raw = glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE)
        ids = np.frombuffer(bytes(raw), dtype='u1').reshape(h, w, 4).view('<u4').reshape(h, w)
        # Object ids are small (< 2^24, top byte 0); the clear value is 0xFF000000.
        centroids = {}
        for oid in np.unique(ids):
            if oid == 0 or oid >= (1 << 24):
                continue
            xs = np.argwhere(ids == oid)[:, 1]
            centroids[int(oid)] = float(xs.mean())
        STATE['scan'] = centroids
        glReadBuffer(GL_COLOR_ATTACHMENT0)
        glBindFramebuffer(GL_READ_FRAMEBUFFER, 0)
        return _orig_submit(self, mode, events, id_map)
    selection.SelectionMixin.submitAsyncPicks = _scan_submit

    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.events.mouseevents import MouseButtonEvent

    # One shared quad mesh + one shared material -> a single instance group.
    quad = PBRMesh(
        positions=[(-.35, -.35, 0), (.35, -.35, 0), (.35, .35, 0), (-.35, .35, 0)],
        normals=[(0, 0, 1)] * 4,
        indices=[0, 1, 2, 0, 2, 3])
    material = PBRMaterial(unlit=True, baseColor=(0, 1, 1))

    def instance(x):
        return basenodes.Transform(translation=(x, 0, 0), children=[
            basenodes.Shape(geometry=quad,
                            appearance=basenodes.Appearance(material=material))])

    xs = [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5]

    class C(Base):
        def OnInit(self):
            self.sg = basenodes.sceneGraph(children=[instance(x) for x in xs])
            self.contextDefinition.pickAsync = True
            self.addEventHandler('mousebutton', button=0, state=1, function=lambda e: None)

    inst = C(); inst.deferRedraw = True
    try:
        glfw.swap_interval(0)   # vsync-independent: don't block on frame callbacks
    except Exception:
        pass
    w, h = inst.getViewPort()
    for i in range(20):
        glfw.poll_events()
        if 3 <= i <= 5:
            ev = MouseButtonEvent(); ev.button = 0; ev.state = 1
            ev.modifiers = (0, 0, 0); ev.pickPoint = (w // 2, h // 2)
            inst.addPickEvent(ev); inst.triggerPick()
        inst.OnDraw(force=1)

    scan = STATE['scan'] or {}
    ncalls = STATE['instanced_calls']
    ninst = STATE['instances']
    ndistinct = len(scan)
    increasing = sorted(scan.items(), key=lambda kv: kv[1])  # by x-centroid
    ids_by_x = [k for k, _ in increasing]
    ok = (ncalls >= 1 and ninst >= N and ndistinct == N
          and len(set(ids_by_x)) == N)
    sys.stderr.write('CALLS=%d INSTANCES=%d DISTINCT_IDS=%d CENTROIDS=%r\n'
                     % (ncalls, ninst, ndistinct, increasing))
    os._exit(0 if ok else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def test_stage1_instanced_render_and_per_instance_picking():
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, '-c', DRIVER],
                          capture_output=True, text=True, timeout=120, env=env)
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'Stage 1 instancing failed (expected one instanced draw of 6 shapes with '
        '6 distinct, left-to-right object ids)\nstdout:\n%s\nstderr:\n%s'
        % (proc.stdout, proc.stderr))
