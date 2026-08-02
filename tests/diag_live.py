"""Live per-frame cost monitor for the oglc-gltf viewer.

Runs the real viewer and prints a rolling breakdown every ~40 rendered frames, so
you can walk / look around normally and read off where the frame time actually
goes on THIS display, under YOUR input pattern:

    render   -- FlatPass.Render (scene: shadows + color), GPU-inclusive (glFinish)
    present  -- SwapBuffers (compositor / vsync)
    cadence  -- real wall time between frames (this is your true fps)
    pick     -- fraction of frames the selection/pick pass was active
    physics  -- whether walk/physics is on
    cascades -- effective directional-shadow cascade count this frame

Usage (Ctrl-C to stop):

    python tests/diag_live.py /workspaces/OpenGL-dev/parthenon/parthenon.glb
    python tests/diag_live.py <model> --size 1280x960

Everything after the model path is passed through to the viewer.
"""
import os, sys, time, statistics

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')

from OpenGL.GL import glFinish
from OpenGLContext.passes import _flat as F, shadowmixin as SM
from OpenGLContext.bin import view

win = {'render': [], 'present': [], 'cadence': [], 'pick': 0, 'frames': 0,
       'casc': 0, 'last': None, 'r': 0.0}

o_render = F.FlatPass.Render
def render(self, context, mode):
    t = time.perf_counter()
    r = o_render(self, context, mode)
    glFinish()
    win['r'] = time.perf_counter() - t
    if getattr(self, '_pick_warm_frames', 0) > 0:
        win['pick'] += 1
    return r
F.FlatPass.Render = render

o_ec = SM.ShadowMapMixin._effectiveCascades
def ec(self):
    win['casc'] = o_ec(self)
    return win['casc']
SM.ShadowMapMixin._effectiveCascades = ec

Ctx = view.TestContext
o_swap = Ctx.SwapBuffers
def SwapBuffers(self, *a, **k):
    t = time.perf_counter()
    r = o_swap(self, *a, **k)
    dt = time.perf_counter() - t
    now = time.perf_counter()
    if win['r'] > 0:
        win['render'].append(win['r'])
        win['present'].append(dt)
        if win['last'] is not None:
            win['cadence'].append(now - win['last'])
        win['frames'] += 1
        if win['frames'] >= 40:
            _flush(self)
    win['last'] = now
    win['r'] = 0.0
    return r
Ctx.SwapBuffers = SwapBuffers

def _flush(ctx):
    def m(x):
        return statistics.median(x) * 1e3 if x else 0.0
    phys = getattr(ctx, '_physics_on', False)
    cad = m(win['cadence'])
    sys.stderr.write(
        "cadence %5.1fms (%4.1f fps) | render %5.1f | present %4.1f | "
        "pick %2d%% | physics %s | cascades %d\n" % (
            cad, (1000.0 / cad) if cad else 0.0, m(win['render']), m(win['present']),
            int(100 * win['pick'] / max(1, win['frames'])),
            'ON ' if phys else 'off', win['casc']))
    sys.stderr.flush()
    win['render'].clear(); win['present'].clear(); win['cadence'].clear()
    win['pick'] = 0; win['frames'] = 0

model = sys.argv[1] if len(sys.argv) > 1 else '/workspaces/OpenGL-dev/parthenon/parthenon.glb'
sys.argv = ['oglc-gltf', model] + sys.argv[2:]
view.main()
