"""Performance harness: instanced vs per-shape draw of a shared-geometry field.

Invoked as a subprocess:

    _instancing_perf_harness.py <on|off> <shapes> <frames>

Renders a grid of ``shapes`` cubes that all SHARE one PBRMesh geometry node and
one material -- the case instancing targets. With instancing on, the whole grid
is one glDrawElementsInstanced; off, it is one draw per cube. Emits a JSON line:

    {"instancing": "on", "shapes": N, "single_draws": S, "instanced_draws": I,
     "instances": K, "median_ms": ..., "mean_ms": ..., "fps": ...}
"""
import json
import os
import sys
import time

os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
os.environ.setdefault('OPENGLCONTEXT_DISABLE_FPS_DISPLAY', '1')
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'

MODE = sys.argv[1] if len(sys.argv) > 1 else 'on'
SHAPES = int(sys.argv[2]) if len(sys.argv) > 2 else 400
FRAMES = int(sys.argv[3]) if len(sys.argv) > 3 else 120
os.environ['OPENGLCONTEXT_INSTANCING'] = '1' if MODE == 'on' else '0'
os.environ['OPENGLCONTEXT_INSTANCE_MIN'] = '4'


def _cube():
    import numpy as np
    faces = [((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
             ((0, 0, -1), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
             ((1, 0, 0), [(1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1)]),
             ((-1, 0, 0), [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)]),
             ((0, 1, 0), [(-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1)]),
             ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)])]
    pos, nrm, idx = [], [], []
    for n, verts in faces:
        base = len(pos)
        for vx in verts:
            pos.append([c * 0.3 for c in vx]); nrm.append(list(n))
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return (np.array(pos, 'f'), np.array(nrm, 'f'), np.array(idx, np.uint32))


def main():
    import glfw
    from OpenGLContext.passes import instancing
    from OpenGLContext.scenegraph import pbrmesh
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

    counts = {'single': 0, 'instanced': 0, 'instances': 0}
    _od = pbrmesh._MeshGPU.draw
    def _cd(self):
        counts['single'] += 1
        return _od(self)
    pbrmesh._MeshGPU.draw = _cd
    _oi = instancing.draw_instanced_mesh
    def _ci(gpu, mvs, oids, material_indices=None):
        counts['instanced'] += 1
        counts['instances'] += len(mvs)
        return _oi(gpu, mvs, oids, material_indices)
    instancing.draw_instanced_mesh = _ci

    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes
    import numpy as np

    cube = _cube()
    geom = PBRMesh(positions=cube[0], normals=cube[1], indices=cube[2])
    mat = PBRMaterial(baseColor=(0.4, 0.5, 0.8), metallic=0.0, roughness=0.5)
    cols = int(np.ceil(np.sqrt(SHAPES)))
    timings = []

    class C(Base):
        def OnInit(self):
            kids = []
            for i in range(SHAPES):
                gx, gy = (i % cols) - cols / 2.0, (i // cols) - cols / 2.0
                kids.append(basenodes.Transform(
                    translation=(gx * 0.9, gy * 0.9, -cols * 0.6),
                    children=[basenodes.Shape(
                        geometry=geom,
                        appearance=basenodes.Appearance(material=mat))]))
            self.sg = basenodes.sceneGraph(children=[
                basenodes.Transform(children=kids),
                basenodes.DirectionalLight(direction=(-.3, -.4, -1.), intensity=1.4)])

    inst = C(); inst.deferRedraw = True
    try:
        glfw.swap_interval(0)   # disable vsync so timing reflects real work
    except Exception:
        pass
    from OpenGL.GL import glFinish
    for i in range(FRAMES):
        glfw.poll_events()
        counts['single'] = 0; counts['instanced'] = 0; counts['instances'] = 0
        t0 = time.perf_counter()
        inst.OnDraw(force=1)
        glFinish()
        dt = (time.perf_counter() - t0) * 1000.0
        if i >= 10:  # warm-up
            timings.append(dt)

    ts = sorted(timings)
    median = ts[len(ts) // 2] if ts else 0.0
    mean = sum(ts) / len(ts) if ts else 0.0
    print(json.dumps({
        'instancing': MODE, 'shapes': SHAPES,
        'single_draws': counts['single'], 'instanced_draws': counts['instanced'],
        'instances': counts['instances'],
        'median_ms': round(median, 4), 'mean_ms': round(mean, 4),
        'fps': round(1000.0 / mean, 1) if mean else 0.0}))
    sys.stdout.flush()   # os._exit skips buffer flushing
    os._exit(0)


try:
    main()
except SystemExit:
    raise
except BaseException as e:
    import traceback
    traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (e,))
    os._exit(3)
