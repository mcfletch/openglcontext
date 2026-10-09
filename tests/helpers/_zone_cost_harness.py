"""What zones cost a fill-bound frame (invoked as a subprocess).

A floor fills the whole window, lit by the full environment probe and a
shadow-casting sun, and four zones cross it, so every one of its fragments
weighs four zones. Each mode named gets a window of its own, and the windows
are drawn in turn, a frame of each, so that whatever else the GPU and the CPU
are doing falls on every mode alike. The median frame time of each is printed
as one JSON line.

Modes:

``plain``   no zones.
``zones``   four zones scaling the scene's environment, which fold into one
            sample of the scene's probe.
``probes``  four zones each lit by an image-based light of its own, so every
            fragment samples four probe layers of the arrays.

Usage:  python tests/helpers/_zone_cost_harness.py FRAMES MODE [MODE ...]

Exits 3 where no GL context can be made, and 1 with a traceback for any other
failure.
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
# A frame time measured against the display's refresh would measure the display.
os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'

import numpy as np
from OpenGL.GL import glFinish

from OpenGLContext import testingcontext
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Box, DirectionalLight, Shape, Transform, Zone,
    ZoneEnvironment, sceneGraph,
)
from OpenGLContext.scenegraph.imagebasedlight import ImageBasedLight
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.testing.glcontext import gl_available
from OpenGLContext.testing.plugin import NO_CONTEXT_STATUS

try:
    import glfw
except ImportError:                 # the harness drives GLFW's event loop itself
    glfw = None

#: Frames drawn before any is timed, so the probe and the shaders are built.
WARMUP = 15


def harness(mode):
    """A context drawing the floor in ``mode``, and the list its frames end on."""
    if mode not in ('plain', 'zones', 'probes'):
        raise ValueError('no zone cost mode %r' % (mode,))
    Base = testingcontext.getInteractive()
    drawn = []

    def image_light(index):
        """A small image-based light of one colour, the zone's own probe."""
        colour = [(1.2, 0.3, 0.3), (0.3, 1.2, 0.3), (0.3, 0.3, 1.2), (1.0, 1.0, 0.3)][index]
        return ImageBasedLight(
            specular=[[np.full((8, 8, 3), colour, 'f4')] * 6],
            irradianceCoefficients=[tuple(3.0 * c for c in colour)] + [(0.0, 0.0, 0.0)] * 8)

    class Harness(Base):
        def SwapBuffers(self):
            """Stop the clock before the swap, with the GPU caught up."""
            glFinish()
            drawn.append(time.perf_counter())
            return super(Harness, self).SwapBuffers()

        def OnInit(self):
            children = [
                Shape(geometry=Box(size=(400.0, 0.2, 400.0)),
                      appearance=Appearance(material=PhysicalMaterial(
                          baseColor=(0.7, 0.7, 0.7), metallic=0.3, roughness=0.4))),
                DirectionalLight(direction=(-0.3, -1.0, -0.2), intensity=2.0,
                                 shadows=True),
            ]
            if mode in ('zones', 'probes'):
                for index, x in enumerate((-3.0, -1.0, 1.0, 3.0)):
                    setting = (ZoneEnvironment(light=image_light(index)) if mode == 'probes'
                               else ZoneEnvironment(intensity=0.3))
                    children.append(Transform(translation=(x, 0.0, 0.0), children=[
                        Zone(size=(3.0, 4.0, 3.0), blend=1.0, settings=[setting])]))
            self.sg = sceneGraph(children=children)
            self.platform.setPosition((0.0, 3.0, 0.0))
            self.platform.setOrientation((1.0, 0.0, 0.0, -1.5))

    # Large enough that the frame is the fragments' cost.
    context = Harness(size=(1600, 1000))
    context.deferRedraw = True
    return context, drawn


def main() -> None:
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    modes = sys.argv[2:] or ['zones']
    contexts = [harness(mode) for mode in modes]
    timings = {mode: [] for mode in modes}
    for frame in range(frames + WARMUP):
        for mode, (context, drawn) in zip(modes, contexts):
            glfw.poll_events()
            del drawn[:]
            start = time.perf_counter()
            context.OnDraw(force=1)
            if drawn and frame >= WARMUP:
                timings[mode].append((drawn[-1] - start) * 1000.0)
    for mode in modes:
        ordered = sorted(timings[mode])
        median = ordered[len(ordered) // 2] if ordered else 0.0
        print(json.dumps({'mode': mode, 'frames': len(ordered),
                          'median_ms': round(median, 4)}))
    sys.stdout.flush()              # os._exit skips buffer flushing
    os._exit(0)


if __name__ == '__main__':
    if glfw is None or not gl_available():
        sys.stderr.write('NOGL no GLFW window with a GL context can be made here\n')
        os._exit(NO_CONTEXT_STATUS)
    main()
