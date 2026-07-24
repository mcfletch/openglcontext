"""Coverage tests for glTF primitive decoding edge paths.

Triangulation guards (degenerate strips, unknown modes), the no-POSITION and
unknown-mode primitive skips, morph-target vertex-count mismatch, and the
tangent estimator's too-few-vertices guard. Pure numpy plus a couple of synthetic
GLBs assembled through the public loader.
"""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")
from pygltflib import (  # noqa: E402
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
    Buffer, Material, PbrMetallicRoughness,
)

from OpenGLContext.loaders import gltf  # noqa: E402
from OpenGLContext.loaders.gltf import meshes as gm  # noqa: E402
from OpenGLContext.loaders.gltf.meshes import PrimitiveMode  # noqa: E402


def _find_shape(node):
    for child in getattr(node, 'children', []) or []:
        if getattr(child, 'geometry', None) is not None:
            return child
        found = _find_shape(child)
        if found is not None:
            return found
    return None


class TestTriangulateIndices:
    def test_short_strip_yields_no_triangles(self):
        # A TRIANGLE_STRIP of two vertices can't form a triangle -> dropped.
        idx, mode = gm._triangulate_indices(
            PrimitiveMode.TRIANGLE_STRIP, np.array([0, 1], np.uint32), 2)
        assert idx is None and mode == PrimitiveMode.TRIANGLES

    def test_unknown_mode_returns_none_pair(self):
        # A mode outside the enum (7) is unrecognised -> (None, None).
        idx, mode = gm._triangulate_indices(7, None, 3)
        assert idx is None and mode is None


class TestPrimitiveShapeGuards:
    def test_primitive_without_position_is_skipped(self):
        g = GLTF2()
        prim = Primitive(attributes=Attributes())      # no POSITION
        shape, bounds = gm._primitive_shape(g, prim, None, {}, {})
        assert shape is None and bounds is None

    def test_unknown_mode_primitive_skipped_with_warning(self, caplog):
        # mode 99 survives read (positions decode) but triangulation returns
        # draw_mode None, so the primitive is dropped with a warning.
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        blob = pos.tobytes()
        g = GLTF2()
        g.scene = 0
        g.scenes = [Scene(nodes=[0])]
        g.nodes = [Node(mesh=0)]
        g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness())]
        g.meshes = [Mesh(primitives=[Primitive(
            attributes=Attributes(POSITION=0), material=0, mode=99)])]
        g.accessors = [Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                                max=pos.max(0).tolist(), min=pos.min(0).tolist())]
        g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes)]
        g.buffers = [Buffer(byteLength=len(blob))]
        g.set_binary_blob(blob)
        with caplog.at_level('WARNING'):
            scene = gltf.load_gltf(b"".join(g.save_to_bytes()))
        assert _find_shape(scene.group) is None
        assert any('unknown mode' in r.getMessage() for r in caplog.records)


class TestMorphTargetMismatch:
    def test_wrong_length_target_dropped_with_warning(self, caplog):
        pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        # a POSITION-delta target with 2 entries against a 3-vertex base
        bad = np.array([[0, 0, 1], [0, 0, 1]], dtype=np.float32)
        blob = pos.tobytes() + bad.tobytes()
        g = GLTF2()
        g.scene = 0
        g.scenes = [Scene(nodes=[0])]
        g.nodes = [Node(mesh=0)]
        g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness())]
        prim = Primitive(attributes=Attributes(POSITION=0), material=0,
                         targets=[{'POSITION': 1}])
        g.meshes = [Mesh(primitives=[prim])]
        g.accessors = [
            Accessor(bufferView=0, componentType=5126, count=3, type='VEC3',
                     max=pos.max(0).tolist(), min=pos.min(0).tolist()),
            Accessor(bufferView=1, componentType=5126, count=2, type='VEC3'),
        ]
        g.bufferViews = [
            BufferView(buffer=0, byteOffset=0, byteLength=pos.nbytes),
            BufferView(buffer=0, byteOffset=pos.nbytes, byteLength=bad.nbytes),
        ]
        g.buffers = [Buffer(byteLength=len(blob))]
        g.set_binary_blob(blob)
        with caplog.at_level('WARNING'):
            scene = gltf.load_gltf(b"".join(g.save_to_bytes()))
        mesh = _find_shape(scene.group).geometry
        # The mismatched target is ignored; the entry ends up empty (no deltas).
        assert mesh.morph_targets == [{}]
        assert any('morph target' in r.getMessage() for r in caplog.records)


class TestEstimateTangentsGuard:
    def test_two_vertices_yield_zero_tangents(self):
        # Fewer than three non-indexed vertices form no triangle -> all-zero vec4.
        pos = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
        nrm = np.array([[0, 0, 1], [0, 0, 1]], dtype=np.float32)
        uv = np.array([[0, 0], [1, 0]], dtype=np.float32)
        t = gm._estimate_tangents(pos, nrm, uv, None)
        assert t.shape == (2, 4)
        assert np.allclose(t, 0.0)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
