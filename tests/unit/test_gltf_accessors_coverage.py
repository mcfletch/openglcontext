"""Coverage tests for glTF accessor decoding edge paths.

Exercise the normalized-integer dequantization helpers, the ``_read_normalized`` /
``_coerce_normalized`` component policies, and the implicit all-zero base of a
sparse accessor with no bufferView -- all pure numpy, no GL, no network.
"""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")
from pygltflib import (  # noqa: E402
    Accessor, BufferView, Buffer, Sparse, AccessorSparseIndices,
    AccessorSparseValues,
)

from OpenGLContext.loaders.gltf import accessors as ga  # noqa: E402


class _R:
    """A resolver stand-in exposing only the decoded-buffer cache the accessor
    reader consults (buffer index -> raw bytes)."""

    def __init__(self, data):
        self._buffers = {0: data}


def _single_accessor_g(arr, component_type, acc_type, normalized=False):
    """A GLTF2 with one accessor/bufferView/buffer over ``arr``'s bytes."""
    g = pygltflib.GLTF2()
    g.accessors = [Accessor(bufferView=0, componentType=component_type,
                            count=len(arr), type=acc_type, normalized=normalized)]
    g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=arr.nbytes)]
    g.buffers = [Buffer(byteLength=arr.nbytes)]
    return g, _R(arr.tobytes())


class TestNormalizeArray:
    def test_signed_array_divides_and_clamps(self):
        arr = np.array([[127, -128], [0, 63]], dtype=np.int8)
        out = ga._normalize_array(arr)
        assert out.dtype == np.float32
        assert np.isclose(out[0, 0], 1.0)
        assert np.isclose(out[0, 1], -1.0)      # -128 clamped to -1, not -128/127
        assert np.isclose(out[1, 0], 0.0)

    def test_unsigned_array_maps_zero_to_one(self):
        arr = np.array([[255, 0]], dtype=np.uint8)
        out = ga._normalize_array(arr)
        assert np.isclose(out[0, 0], 1.0) and np.isclose(out[0, 1], 0.0)

    def test_explicit_dtype_sets_divisor(self):
        # A float array normalized by an int16 range: 32767 -> 1.0.
        arr = np.array([[32767.0]], dtype=np.float32)
        out = ga._normalize_array(arr, np.int16)
        assert np.isclose(out[0, 0], 1.0)


class TestReadNormalized:
    def test_normalized_integer_accessor_dequantized(self):
        arr = np.array([[255, 0, 128]], dtype=np.uint8)
        g, r = _single_accessor_g(arr, 5121, 'VEC3', normalized=True)
        out = ga._read_normalized(g, 0, r)
        assert np.isclose(out[0, 0], 1.0) and np.isclose(out[0, 1], 0.0)

    def test_plain_integer_accessor_passed_through_as_float(self):
        arr = np.array([[7, 3, 1]], dtype=np.uint8)
        g, r = _single_accessor_g(arr, 5121, 'VEC3', normalized=False)
        out = ga._read_normalized(g, 0, r)
        assert out.dtype == np.float32
        assert out.tolist() == [[7.0, 3.0, 1.0]]

    def test_float_accessor_passed_through(self):
        arr = np.array([[0.5, 0.25, 0.75]], dtype=np.float32)
        g, r = _single_accessor_g(arr, 5126, 'VEC3')
        out = ga._read_normalized(g, 0, r)
        assert np.allclose(out, arr)


class TestCoerceNormalized:
    def test_float_accessor_passthrough(self):
        acc = Accessor(componentType=5126, type='VEC3', count=1)
        out = ga._coerce_normalized(acc, np.array([[1.0, 2.0, 3.0]], dtype=np.float64))
        assert out.dtype == np.float32 and out.tolist() == [[1.0, 2.0, 3.0]]

    def test_normalized_integer_divides_by_declared_range(self):
        acc = Accessor(componentType=5121, type='VEC2', count=1, normalized=True)
        out = ga._coerce_normalized(acc, np.array([[255, 0]], dtype=np.uint8))
        assert np.isclose(out[0, 0], 1.0) and np.isclose(out[0, 1], 0.0)

    def test_plain_integer_passed_through(self):
        acc = Accessor(componentType=5123, type='SCALAR', count=1, normalized=False)
        out = ga._coerce_normalized(acc, np.array([[5]], dtype=np.uint16))
        assert out.dtype == np.float32 and out[0, 0] == 5.0


class TestSparseImplicitZeroBase:
    def test_no_bufferview_base_is_zero_then_scattered(self):
        # A sparse accessor with no bufferView has an implicit all-zero base
        # (accessors._accessor_base returns zeros); the sparse pairs overwrite it.
        sidx = np.array([2], dtype=np.uint16)
        svals = np.array([[9, 8, 7]], dtype=np.float32)
        blob = sidx.tobytes() + svals.tobytes()
        g = pygltflib.GLTF2()
        sparse = Sparse(
            count=1,
            indices=AccessorSparseIndices(bufferView=0, byteOffset=0, componentType=5123),
            values=AccessorSparseValues(bufferView=1, byteOffset=0))
        g.accessors = [Accessor(bufferView=None, componentType=5126, count=4,
                                type='VEC3', sparse=sparse)]
        g.bufferViews = [
            BufferView(buffer=0, byteOffset=0, byteLength=sidx.nbytes),
            BufferView(buffer=0, byteOffset=sidx.nbytes, byteLength=svals.nbytes),
        ]
        g.buffers = [Buffer(byteLength=len(blob))]
        out = ga._read_accessor(g, 0, _R(blob))
        assert out.shape == (4, 3)
        assert out[0].tolist() == [0, 0, 0]      # implicit zero base
        assert out[2].tolist() == [9, 8, 7]      # sparse override


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
