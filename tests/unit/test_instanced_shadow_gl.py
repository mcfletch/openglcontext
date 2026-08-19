"""The shadow depth pass instances too (GL, PBR core).

Regression for the fix to a 30fps stall: with shadows on, an instanced scene must
not re-draw every caster per-shape into each shadow map. Loads the instanced glTF
lattice with a shadow-casting light and asserts NO per-shape draws happen -- both
the colour pass and the shadow depth pass go through the instanced path. Skips
when no usable GL context is available.
"""
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.paths import tests_root
GLTF = os.path.join(str(tests_root(__file__)), 'wrls', 'instanced_lattice.gltf')

DRIVER = r'''
import os, sys
PATH = sys.argv[1]
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '1'   # shadow pass active
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
try:
    import glfw
    from OpenGLContext.passes import instancing
    from OpenGLContext.scenegraph import pbrmesh

    C = {'single': 0, 'instanced': 0}
    _od = pbrmesh._MeshGPU.draw
    def _cs(self):
        C['single'] += 1
        return _od(self)
    pbrmesh._MeshGPU.draw = _cs
    _oi = instancing.draw_instanced_mesh
    def _ci(gpu, mvs, oids, material_indices=None, **named):
        C['instanced'] += 1
        return _oi(gpu, mvs, oids, material_indices)
    instancing.draw_instanced_mesh = _ci

    from OpenGLContext import testingcontext
    from OpenGLContext.loaders import gltf
    from OpenGLContext.scenegraph.basenodes import sceneGraph, DirectionalLight
    Base = testingcontext.getInteractive()

    class V(Base):
        def OnInit(self):
            self.sg = sceneGraph(children=[
                gltf.load_gltf(PATH).group,
                DirectionalLight(direction=(-0.3, -0.4, -1.0), intensity=1.2)])

    v = V(); v.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    for i in range(5):
        glfw.poll_events()
        C['single'] = C['instanced'] = 0
        v.OnDraw(force=1)

    # Colour pass + at least one shadow-map pass, all instanced; no per-shape draw.
    ok = (C['single'] == 0 and C['instanced'] >= 2)
    sys.stderr.write('single=%d instanced=%d\n' % (C['single'], C['instanced']))
    os._exit(0 if ok else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


def test_shadow_pass_is_instanced():
    proc = subprocess.run([sys.executable, '-c', DRIVER, GLTF],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'shadow pass did not instance (expected 0 per-shape draws with shadows on)\n'
        'stdout:\n%s\nstderr:\n%s' % (proc.stdout, proc.stderr))
