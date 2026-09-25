"""What zones cost a fill-bound frame (invoked as a subprocess).

A floor fills the whole window, lit by the full environment probe and a
shadow-casting sun, and four zones cross it, so every one of its fragments
weighs four zones. The same frame is drawn with and without the zones, and the
median frame time is printed as one JSON line.

Usage:  python tests/helpers/_zone_cost_harness.py FRAMES [zones|plain]

Exits 3 where no GL context can be made.
"""
import json
import os
import sys
import time

os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
os.environ['OPENGLCONTEXT_IBL'] = 'full'
os.environ.setdefault('OPENGLCONTEXT_DISABLE_FPS_DISPLAY', '1')
os.environ['OPENGLCONTEXT_SHADOWS'] = '1'
os.environ['OPENGLCONTEXT_SHADOW_CASCADES'] = '1'

#: Frames drawn before any is timed, so the probe and the shaders are built.
WARMUP = 15


def main() -> None:
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    mode = sys.argv[2] if len(sys.argv) > 2 else 'zones'

    import glfw
    from OpenGL.GL import glFinish
    from OpenGLContext import testingcontext
    from OpenGLContext.scenegraph.basenodes import (
        Appearance, Box, DirectionalLight, Shape, Transform, Zone,
        ZoneEnvironment, sceneGraph,
    )
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

    Base = testingcontext.getInteractive()
    drawn = []

    class Harness(Base):
        def SwapBuffers(self):
            """Stop the clock before the swap, with the GPU caught up."""
            glFinish()
            drawn.append(time.perf_counter())
            return super(Harness, self).SwapBuffers()

        def OnInit(self):
            children = [
                Shape(geometry=Box(size=(400.0, 0.2, 400.0)),
                      appearance=Appearance(material=PBRMaterial(
                          baseColor=(0.7, 0.7, 0.7), metallic=0.3, roughness=0.4))),
                DirectionalLight(direction=(-0.3, -1.0, -0.2), intensity=2.0,
                                 castShadows=True),
            ]
            if mode == 'zones':
                for x in (-3.0, -1.0, 1.0, 3.0):
                    children.append(Transform(translation=(x, 0.0, 0.0), children=[
                        Zone(size=(3.0, 4.0, 3.0), blend=1.0,
                             settings=[ZoneEnvironment(intensity=0.3)])]))
            self.sg = sceneGraph(children=children)
            self.platform.setPosition((0.0, 3.0, 0.0))
            self.platform.setOrientation((1.0, 0.0, 0.0, -1.5))

    # Large enough that the frame is the fragments' cost.
    context = Harness(size=(1600, 1000))
    context.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    timings = []
    for frame in range(frames + WARMUP):
        glfw.poll_events()
        del drawn[:]
        start = time.perf_counter()
        context.OnDraw(force=1)
        if drawn and frame >= WARMUP:
            timings.append((drawn[-1] - start) * 1000.0)
    ordered = sorted(timings)
    median = ordered[len(ordered) // 2] if ordered else 0.0
    print(json.dumps({'mode': mode, 'frames': len(ordered),
                      'median_ms': round(median, 4)}))
    sys.stdout.flush()              # os._exit skips buffer flushing
    os._exit(0)


try:
    main()
except SystemExit:
    raise
except BaseException as error:
    import traceback
    traceback.print_exc()
    sys.stderr.write('NOGL %r\n' % (error,))
    os._exit(3)
