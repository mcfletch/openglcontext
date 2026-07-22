"""Performance harness for the PBR pass (invoked as a subprocess).

Renders an *animated* scene of many PBRMesh primitives for a fixed number of
frames and reports per-frame timing as JSON on stdout. Because the scene
animates (a root Transform spins every frame), every frame walks the whole
render set and submits every primitive -- so this measures *sustained*
per-frame cost, not just first-frame setup.

Two draw paths are compared so the cache benefit is visible:

    cached   -- production path: the VAO is built once and reused (PBRMesh).
    uncached -- the pre-cache path: the VAO is rebuilt and the attribute
                pointers re-specified every frame (``_draw_uncached`` below).

Usage:
    python tests/_pbr_perf_harness.py {cached|uncached} [SHAPES] [FRAMES]

Output (stdout, last line):
    {"mode": "...", "shapes": N, "frames": F, "vao_allocations": A,
     "median_ms": ..., "mean_ms": ..., "fps": ...}
"""
import json
import os
import sys
import time


def _cube(half=0.5):
    """Return (positions, normals, texcoords, indices) for a unit cube."""
    import numpy as np
    # 6 faces x 4 verts, with per-face normals
    faces = [
        ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
        ((0, 0, -1), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
        ((1, 0, 0), [(1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1)]),
        ((-1, 0, 0), [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)]),
        ((0, 1, 0), [(-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1)]),
        ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]),
    ]
    pos, nrm, uv, idx = [], [], [], []
    for n, verts in faces:
        base = len(pos)
        for vx in verts:
            pos.append([c * half for c in vx])
            nrm.append(list(n))
        uv += [(0, 0), (1, 0), (1, 1), (0, 1)]
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return (np.array(pos, 'f'), np.array(nrm, 'f'),
            np.array(uv, 'f'), np.array(idx, np.uint32))


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else 'cached'
    shapes = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    frames = int(sys.argv[3]) if len(sys.argv) > 3 else 120

    os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
    os.environ.setdefault('OPENGLCONTEXT_SHADOWS', '0')
    os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    # This harness measures the per-shape VAO cache, so keep the per-shape draw
    # path: instancing would collapse the identical cubes into one instanced draw
    # (its own win, benchmarked in test_instancing_performance) and bypass the
    # per-mesh VAO allocation this test counts.
    os.environ['OPENGLCONTEXT_INSTANCING'] = '0'

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    import numpy as np
    from OpenGL.GL import glFinish
    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from OpenGLContext.scenegraph.basenodes import (
        sceneGraph, Transform, Shape, Appearance, DirectionalLight,
    )
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    from OpenGLContext.scenegraph import pbrmesh as pbrmesh_mod

    # Count VAO allocations so we can prove "built once" vs "rebuilt per frame".
    alloc = {'count': 0}
    _orig_gen = pbrmesh_mod.glGenVertexArrays

    def _counting_gen(n, *a, **k):
        alloc['count'] += n
        return _orig_gen(n, *a, **k)

    pbrmesh_mod.glGenVertexArrays = _counting_gen

    def _draw_uncached(self):
        # The pre-cache baseline: rebuild the VAO and re-specify the attribute
        # pointers every call. Lives here (not on the shipped node) so the
        # production _MeshGPU carries only the cached fast path.
        from OpenGL.GL import glBindVertexArray, glDeleteVertexArrays
        # Go through the module symbol so the per-frame rebuilds are counted (a
        # local `from OpenGL.GL import glGenVertexArrays` would bypass the wrapper
        # installed above, undercounting the uncached baseline to just the initial
        # per-mesh builds).
        vao = pbrmesh_mod.glGenVertexArrays(1)
        glBindVertexArray(vao)
        try:
            self._bind_attributes()
            if self.idx_vbo is not None:
                self.idx_vbo.bind()
            self._draw_elements()
        finally:
            if self.idx_vbo is not None:
                self.idx_vbo.unbind()
            for buf, loc, size in self.attr_layout:
                buf.unbind()
            glBindVertexArray(0)
            glDeleteVertexArrays(1, [vao])

    if mode == 'uncached':
        pbrmesh_mod._MeshGPU.draw = _draw_uncached

    cube = _cube()

    def scene():
        # A grid of independently-coloured cubes under one spinning root, so the
        # whole set is re-submitted each frame while geometry stays static.
        cols = int(np.ceil(np.sqrt(shapes)))
        kids = []
        for i in range(shapes):
            gx, gy = (i % cols) - cols / 2.0, (i // cols) - cols / 2.0
            mesh = pbrmesh_mod.PBRMesh(
                positions=cube[0], normals=cube[1],
                texcoords=cube[2], indices=cube[3])
            mat = PBRMaterial(
                baseColor=(0.3 + 0.7 * (i % 5) / 4.0, 0.4, 0.7),
                metallic=(i % 2), roughness=0.3 + 0.5 * (i % 3) / 2.0)
            kids.append(Transform(
                translation=(gx * 1.4, gy * 1.4, 0),
                children=[Shape(geometry=mesh, appearance=Appearance(material=mat))]))
        root = Transform(children=kids)
        return root, sceneGraph(children=[
            root,
            DirectionalLight(direction=(-0.3, -0.4, -1.0), color=(1, 1, 1), intensity=1.4),
        ])

    timings = []

    def emit():
        ts = sorted(timings)
        if ts:
            median = ts[len(ts) // 2]
            mean = sum(ts) / len(ts)
            fps = 1000.0 / mean if mean else 0.0
        else:
            median = mean = fps = 0.0
        print(json.dumps({
            'mode': mode, 'shapes': shapes, 'frames': frames,
            'rendered': len(ts), 'vao_allocations': alloc['count'],
            'median_ms': round(median, 4), 'mean_ms': round(mean, 4),
            'fps': round(fps, 1),
        }), flush=True)

    class PerfContext(BaseContext):
        def OnInit(self):
            try:
                import glfw
                glfw.swap_interval(0)  # disable vsync so timing reflects raw cost
            except Exception:
                pass
            self._root, self.sg = scene()
            cols = int(np.ceil(np.sqrt(shapes)))
            self.platform.setPosition((0, 0, cols * 1.7 + 4))
            self._frame = 0

        def OnIdle(self, *a):
            self.triggerRedraw(1)
            return 1

        def OnQuit(self, *a, **k):
            emit()  # base OnQuit calls os._exit(0), so report before it does
            return BaseContext.OnQuit(self, *a, **k)

        def OnDraw(self, *a, **k):
            # Spin the root so every frame walks and re-submits the whole set.
            self._root.rotation = (0, 1, 0, (self._frame * 0.05) % (2 * np.pi))
            t0 = time.perf_counter()
            result = BaseContext.OnDraw(self, *a, **k)
            # CPU-side submission cost: VAO churn + attribute-pointer specification
            # are synchronous driver calls, so this isolates the work the cache
            # removes without GPU fill (which dominates on a software rasteriser)
            # swamping the signal. Set HARNESS_GLFINISH=1 for whole-frame timing.
            if os.environ.get('HARNESS_GLFINISH') == '1':
                glFinish()
            if self._frame > 10:  # skip warmup frames (shader/buffer upload)
                timings.append((time.perf_counter() - t0) * 1000.0)
            self._frame += 1
            return result

    # Drive exactly `frames` redraws via auto-exit (counts OnDraw calls).
    os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = str(frames + 2)

    PerfContext.ContextMainLoop()
    # Unreached: base OnQuit (auto-exit) calls os._exit(0); emit() runs there.
    emit()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
