"""The shipped demo worlds instance automatically when loaded (GL).

Locks two loadable worlds that show scenegraph instancing with no manual GL:

  tests/wrls/instanced_lattice.wrl   -- a 216-atom NaCl crystal (DEF/USE-shared
      atom Shapes) rendered by the VRML97 core pass -> a couple of instanced draws.
  tests/wrls/instanced_lattice.gltf  -- 512 cubes via EXT_mesh_gpu_instancing,
      rendered by the PBR pass -> one instanced draw.

Each asserts the whole world drew with zero per-shape draws and >=1 instanced
draw (i.e. it actually collapsed). Skips when no usable GL context is available.
"""
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.paths import tests_root
HERE = str(tests_root(__file__))
WRL = os.path.join(HERE, 'wrls', 'instanced_lattice.wrl')
GLTF = os.path.join(HERE, 'wrls', 'instanced_lattice.gltf')

DRIVER = r'''
import os, sys
KIND, PATH = sys.argv[1], sys.argv[2]
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
if KIND == 'gltf':
    os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
try:
    import glfw
    from OpenGLContext.passes import instancing
    from OpenGLContext.scenegraph import pbrmesh

    C = {'single': 0, 'instanced': 0, 'instances': 0}
    _od = pbrmesh._MeshGPU.draw
    def _cs(self):
        C['single'] += 1
        return _od(self)
    pbrmesh._MeshGPU.draw = _cs
    _oi = instancing.draw_instanced_mesh
    def _ci(gpu, mvs, oids, material_indices=None, **named):
        C['instanced'] += 1
        C['instances'] += len(mvs)
        return _oi(gpu, mvs, oids, material_indices)
    instancing.draw_instanced_mesh = _ci

    from OpenGLContext import testingcontext
    from OpenGLContext.scenegraph.basenodes import sceneGraph
    Base = testingcontext.getInteractive()

    def load():
        if KIND == 'gltf':
            from OpenGLContext.loaders import gltf
            return sceneGraph(children=[gltf.load_gltf(PATH).group])
        from OpenGLContext.loaders.loader import Loader
        return Loader.load(PATH)

    class V(Base):
        def OnInit(self):
            self.sg = load()

    v = V(); v.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    for i in range(4):
        glfw.poll_events()
        C['single'] = C['instanced'] = C['instances'] = 0
        v.OnDraw(force=1)

    ok = (C['single'] == 0 and C['instanced'] >= 1 and C['instances'] > 50)
    sys.stderr.write('KIND=%s single=%d instanced=%d instances=%d\n'
                     % (KIND, C['single'], C['instanced'], C['instances']))
    os._exit(0 if ok else 2)
except SystemExit:
    raise
except BaseException as e:
    import traceback; traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
'''


@pytest.mark.parametrize('kind,path', [('wrl', WRL), ('gltf', GLTF)])
def test_demo_world_instances_on_load(kind, path):
    proc = subprocess.run([sys.executable, '-c', DRIVER, kind, path],
                          capture_output=True, text=True, timeout=120,
                          env=dict(os.environ))
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        '%s world did not instance on load (expected 0 per-shape draws, >=1 '
        'instanced draw)\nstdout:\n%s\nstderr:\n%s' % (kind, proc.stdout, proc.stderr))
