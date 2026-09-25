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
# A frame time measured against the display's refresh would measure the display.
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'

import numpy as np
from OpenGL.GL import glFinish

from OpenGLContext import testingcontext
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.testing.glcontext import gl_available

try:
    import glfw
except ImportError:                 # the harness drives GLFW's event loop itself
    glfw = None


def _cube():
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
            pos.append([c * 0.3 for c in vx])
            nrm.append(list(n))
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return (np.array(pos, 'f'), np.array(nrm, 'f'), np.array(idx, np.uint32))


def main():
    Base = testingcontext.getInteractive()

    cube = _cube()
    geom = PBRMesh(positions=cube[0], normals=cube[1], indices=cube[2])
    mat = PBRMaterial(baseColor=(0.4, 0.5, 0.8), metallic=0.0, roughness=0.5)
    cols = int(np.ceil(np.sqrt(SHAPES)))
    timings = []
    drawn = []

    class C(Base):
        def SwapBuffers(self):
            """Stop the clock *before* the swap, with the GPU caught up.

            A buffer swap blocks until the compositor is ready for another
            frame, and a compositor may throttle it to the display whatever
            ``OPENGLCONTEXT_NO_VSYNC`` asked for.  Timing across it measures the wait
            and not the work: both modes then come out at the frame interval,
            and the ratio between them is driven to 1 -- which is the wrong
            answer for a measurement whose whole purpose is the ratio.
            """
            glFinish()
            drawn.append(time.perf_counter())
            return super(C, self).SwapBuffers()

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

    inst = C()
    inst.deferRedraw = True
    for i in range(FRAMES):
        glfw.poll_events()
        del drawn[:]
        t0 = time.perf_counter()
        inst.OnDraw(force=1)
        if not drawn:
            # Nothing was swapped, so nothing was drawn: a frame with no
            # visible change is not a measurement of drawing one.
            continue
        dt = (drawn[-1] - t0) * 1000.0
        if i >= 10:  # warm-up
            timings.append(dt)

    ts = sorted(timings)
    median = ts[len(ts) // 2] if ts else 0.0
    mean = sum(ts) / len(ts) if ts else 0.0
    # The last frame's counts: one draw per shape drawn singly, plus one per
    # instanced group.
    stats = inst.renderStats
    print(json.dumps({
        'instancing': MODE, 'shapes': SHAPES,
        'single_draws': stats.draws - stats.instanceGroups,
        'instanced_draws': stats.instanceGroups,
        'instances': stats.instances,
        'median_ms': round(median, 4), 'mean_ms': round(mean, 4),
        'fps': round(1000.0 / mean, 1) if mean else 0.0}))
    sys.stdout.flush()   # os._exit skips buffer flushing
    os._exit(0)


if __name__ == '__main__':
    # Exit 3 is "this machine cannot render", which the test skips on. Any
    # other failure is the harness's, and ends with its traceback.
    if glfw is None or not gl_available():
        sys.stderr.write('NOGL no GLFW window with a GL context can be made here\n')
        os._exit(3)
    main()
