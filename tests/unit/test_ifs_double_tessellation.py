"""Regression: IndexedPolygonsCompiler tessellates once, not twice (no GL).

`IndexedPolygonsCompiler.compile` ran the full (self-documented-as-expensive)
tessellation, discarded the result, then immediately recomputed it with
`sources`. `tessellate()` is side-effect-free, so the first call was pure wasted
CPU that doubled the compile cost of every qualifying IFS. This pins the call
count so the redundant pass can't silently return.
"""
from OpenGLContext.scenegraph import indexedfaceset
from OpenGLContext.scenegraph.indexedfaceset import IndexedPolygonsCompiler
from OpenGLContext.scenegraph import basenodes


def _quad_ifs():
    # Two triangles with explicit per-vertex normals so IndexedPolygonsCompiler
    # is the applicable compiler (weight 1.05).
    return basenodes.IndexedFaceSet(
        coord=basenodes.Coordinate(point=[
            (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]),
        coordIndex=[0, 1, 2, -1, 0, 2, 3, -1],
        normal=basenodes.Normal(vector=[(0, 0, 1)] * 4),
        normalIndex=[0, 1, 2, -1, 0, 2, 3, -1],
        normalPerVertex=True,
    )


def test_compiler_applies_to_per_vertex_normal_ifs():
    # Guards the premise: this IFS really routes to IndexedPolygonsCompiler.
    assert IndexedPolygonsCompiler.weight(_quad_ifs()) == 1.05


def test_tessellate_called_once():
    ifs = _quad_ifs()
    compiler = IndexedPolygonsCompiler(ifs)

    calls = {'n': 0}
    original = compiler.tessellate

    def counting(*args, **named):
        calls['n'] += 1
        return original(*args, **named)

    compiler.tessellate = counting
    compiler.compile(mode=None)
    assert calls['n'] == 1, (
        "tessellate() should run exactly once; %d calls means the discarded "
        "first tessellation is still there" % calls['n'])
