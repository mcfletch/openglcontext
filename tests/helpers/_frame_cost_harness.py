"""What a frame costs per object, measured on a scene of a stated size.

Invoked as a subprocess::

    _frame_cost_harness.py <objects> <frames> [still|moving]

Builds ``objects`` shadow-casting level-of-detail chains, renders ``frames``
frames of them, and emits one JSON line::

    {"objects": N, "median_ms": ..., "mean_ms": ...,
     "world_matrices": ..., "path_walks": ..., "caster_derivations": ...,
     "level_choices": ...}

The four counts are per frame, and they are what the timing is a consequence
of: how many times a path was asked where it is, how many times one was walked
to the node at its end, how many casters had their world geometry worked out,
and how many times the scene's levels were chosen. A machine's speed moves the
milliseconds; only a change in the engine moves those.

``moving`` walks the camera a little every frame, which is the case in which
nothing a frame worked out last time can be reused. ``still`` leaves it where
it is, which is the case a shortcut can answer.
"""
import json
import os
import sys
import time

os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
os.environ.setdefault('OPENGLCONTEXT_DISABLE_FPS_DISPLAY', '1')
os.environ['OPENGLCONTEXT_SHADOWS'] = '1'
os.environ['OPENGLCONTEXT_SHADOW_CASCADES'] = '1'

OBJECTS = int(sys.argv[1]) if len(sys.argv) > 1 else 200
FRAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 90
CAMERA = sys.argv[3] if len(sys.argv) > 3 else 'still'

#: Frames rendered before the clock is read, so a compiled shader, a warmed
#: driver and a settled cascade count are not what is being measured.
WARMUP = 20


def _tetra(scale):
    """A handful of triangles: the scene is about object count, not geometry."""
    import numpy as np
    corners = [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]
    faces = [(0, 1, 2), (0, 2, 3), (0, 3, 1), (1, 3, 2)]
    pos, nrm, idx = [], [], []
    for face in faces:
        base = len(pos)
        points = [np.array(corners[c], 'f') * scale for c in face]
        normal = np.cross(points[1] - points[0], points[2] - points[0])
        normal = normal / (np.linalg.norm(normal) or 1.0)
        for point in points:
            pos.append(point)
            nrm.append(normal)
        idx += [base, base + 1, base + 2]
    return np.array(pos, 'f'), np.array(nrm, 'f'), np.array(idx, np.uint32)


def main():
    import glfw
    import numpy as np

    from OpenGLContext.scenegraph import lod as lod_module
    from OpenGLContext.passes import shadowmixin

    counts = {'matrices': 0, 'walks': 0, 'derivations': 0, 'choices': 0}

    from vrml.vrml97 import nodepath as vrml_nodepath
    _matrix = vrml_nodepath._NodePath.transformMatrix

    def counted_matrix(self, *args, **named):
        counts['matrices'] += 1
        return _matrix(self, *args, **named)

    vrml_nodepath._NodePath.transformMatrix = counted_matrix

    from vrml.nodepath import NodePath
    _walk = NodePath.__getitem__

    def counted_walk(self, index):
        counts['walks'] += 1
        return _walk(self, index)

    NodePath.__getitem__ = counted_walk

    _derive = shadowmixin.ShadowMapMixin._casterGeometryBatch.__func__

    def counted_derive(cls, records):
        counts['derivations'] += len(records)
        return _derive(cls, records)

    shadowmixin.ShadowMapMixin._casterGeometryBatch = classmethod(counted_derive)

    _scales = lod_module.uniform_scales

    def counted_scales(modelviews):
        counts['choices'] += 1
        return _scales(modelviews)

    lod_module.uniform_scales = counted_scales

    from OpenGLContext import testingcontext
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh

    material = PBRMaterial(baseColor=(0.6, 0.55, 0.5), metallic=0.0,
                           roughness=0.6)
    # One chain of levels, shared by every object: what is being measured is
    # what a frame costs per *object*, and geometry shared between them is how
    # a real world of repeated content is built.
    levels = [basenodes.Shape(
        geometry=PBRMesh(positions=p, normals=n, indices=i),
        appearance=basenodes.Appearance(material=material))
        for p, n, i in (_tetra(0.30), _tetra(0.29), _tetra(0.28))]

    Base = testingcontext.getInteractive()
    drawn = []
    columns = int(np.ceil(np.sqrt(OBJECTS)))

    class Harness(Base):
        def SwapBuffers(self):
            """Stop the clock before the swap, with the GPU caught up.

            A swap blocks until the compositor wants another frame, so timing
            across it measures the wait rather than the work.
            """
            from OpenGL.GL import glFinish
            glFinish()
            drawn.append(time.perf_counter())
            return super(Harness, self).SwapBuffers()

        def OnInit(self):
            kids = []
            for index in range(OBJECTS):
                across = (index % columns) - columns / 2.0
                down = (index // columns) - columns / 2.0
                kids.append(basenodes.Transform(
                    translation=(across * 0.9, down * 0.9, -columns * 0.7),
                    children=[lod_module.ScreenCoverageLOD(
                        level=list(levels), radius=0.5,
                        screenCoverage=[0.02, 0.005, 0.0])]))
            self.sg = basenodes.sceneGraph(children=[
                basenodes.Transform(children=kids),
                basenodes.DirectionalLight(direction=(-.3, -.4, -1.),
                                           intensity=1.4)])

    context = Harness()
    context.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass

    platform = context.getViewPlatform()
    timings = []
    measured = 0
    for frame in range(FRAMES):
        glfw.poll_events()
        if CAMERA == 'moving':
            platform.setPosition((0.0, 0.0, frame * 0.01))
        del drawn[:]
        if frame == WARMUP:
            counts.update(matrices=0, walks=0, derivations=0, choices=0)
            measured = 0
        start = time.perf_counter()
        context.OnDraw(force=1)
        if not drawn:
            continue                # nothing swapped, so nothing was drawn
        if frame >= WARMUP:
            timings.append((drawn[-1] - start) * 1000.0)
            measured += 1

    ordered = sorted(timings)
    median = ordered[len(ordered) // 2] if ordered else 0.0
    mean = sum(ordered) / len(ordered) if ordered else 0.0
    per = float(max(measured, 1))
    print(json.dumps({
        'objects': OBJECTS, 'camera': CAMERA, 'frames': measured,
        'median_ms': round(median, 4), 'mean_ms': round(mean, 4),
        'world_matrices': round(counts['matrices'] / per, 2),
        'path_walks': round(counts['walks'] / per, 2),
        'caster_derivations': round(counts['derivations'] / per, 2),
        'level_choices': round(counts['choices'] / per, 3),
    }))
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
