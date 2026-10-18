"""Meshopt-compressed buffer views (KHR_meshopt_compression, EXT_meshopt_compression).

The codec vectors marked "meshoptimizer" are the encoded streams and decoded
values from meshoptimizer's own test suite (demo/tests.cpp, MIT licence,
Copyright (c) 2016-2026 Arseny Kapoulkine); they are data, used here to hold
this decoder to the reference one. The filter cases are encoded by hand from
the specification's Appendix B. The glTF documents are built in the test, with
a minimal encoder below that stores every delta as a full byte.
"""
import struct

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.gltf import load_gltf, load_gltf_url
from OpenGLContext.loaders.gltf import meshopt
from OpenGLContext.loaders.gltf.writer import _pack_glb
from OpenGLContext.testing.network import unreachable


# --------------------------------------------------------------------------- #
# meshoptimizer's vectors
# --------------------------------------------------------------------------- #
#: struct PV { uint16 px, py, pz; uint8 nu, nv; uint16 tx, ty; } x 4
PV_VERTICES = np.array([
    (0, 0, 0, 0, 0, 0, 0),
    (300, 0, 0, 0, 0, 500, 0),
    (0, 300, 0, 0, 0, 0, 500),
    (300, 300, 0, 0, 0, 500, 500),
], dtype=[('px', '<u2'), ('py', '<u2'), ('pz', '<u2'), ('nu', 'u1'), ('nv', 'u1'),
          ('tx', '<u2'), ('ty', '<u2')])
PV_BYTES = PV_VERTICES.view(np.uint8).reshape(4, 12)

VERTEX_V0 = bytes([
    0xa0, 0x01, 0x3f, 0x00, 0x00, 0x00, 0x58, 0x57, 0x58, 0x01, 0x26, 0x00, 0x00, 0x00, 0x01, 0x0c,
    0x00, 0x00, 0x00, 0x58, 0x01, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x3f, 0x00,
    0x00, 0x00, 0x17, 0x18, 0x17, 0x01, 0x26, 0x00, 0x00, 0x00, 0x01, 0x0c, 0x00, 0x00, 0x00, 0x17,
    0x01, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00])

VERTEX_V1 = bytes([
    0xa1, 0xee, 0xaa, 0xee, 0x00, 0x4b, 0x4b, 0x4b, 0x00, 0x00, 0x4b, 0x00, 0x00, 0x7d, 0x7d, 0x7d,
    0x00, 0x00, 0x7d, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x62, 0x00, 0x62])

#: Every version 1 feature: control modes, 2-byte and XOR channels, literals.
VERTEX_V1_CUSTOM = bytes([
    0xa1, 0xd4, 0x94, 0xd4, 0x01, 0x0e, 0x00, 0x58, 0x57, 0x58, 0x02, 0x02, 0x12, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x58, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x02, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x0e, 0x00, 0x7d, 0x7d, 0x7d, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x7d, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x62])

VERTEX_V0_MORE = bytes([
    0xa0, 0x00, 0x01, 0x2a, 0xaa, 0xaa, 0xaa, 0x02, 0x04, 0x44, 0x44, 0x44, 0x44, 0x44, 0x44, 0x44,
    0x03, 0x00, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10,
    0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00])
VERTEX_V0_MORE_DECODED = [
    0, 0, 0, 0, 0, 1, 2, 8, 0, 2, 4, 16, 0, 3, 6, 24,
    0, 4, 8, 32, 0, 5, 10, 40, 0, 6, 12, 48, 0, 7, 14, 56,
    0, 8, 16, 64, 0, 9, 18, 72, 0, 10, 20, 80, 0, 11, 22, 88,
    0, 12, 24, 96, 0, 13, 26, 104, 0, 14, 28, 112, 0, 15, 30, 120]

VERTEX_V1_DELTAS = bytes([
    0xa1, 0x99, 0x99, 0x01, 0x2a, 0xaa, 0xaa, 0xaa, 0x02, 0x04, 0x44, 0x44, 0x44, 0x43, 0x33, 0x33,
    0x33, 0x02, 0x06, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x66, 0x02, 0x08, 0x88, 0x88, 0x88, 0x87,
    0x77, 0x77, 0x77, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0xf8, 0x00, 0xf8, 0x00, 0xf0, 0x00, 0xf0, 0x00, 0x01, 0x01])
VERTEX_V1_DELTAS_DECODED = [
    248, 248, 240, 240, 249, 250, 243, 244, 250, 252, 246, 248, 251, 254, 249, 252,
    252, 256, 252, 256, 253, 258, 255, 260, 254, 260, 258, 264, 255, 262, 261, 268,
    256, 264, 264, 272, 257, 262, 267, 268, 258, 260, 270, 264, 259, 258, 273, 260,
    260, 256, 276, 256, 261, 254, 279, 252, 262, 252, 282, 248, 263, 250, 285, 244]

VERTEX_SENTINELS = bytes([
    0xa1, 0xa9, 0x01, 0xfc, 0x3c, 0xcc, 0xcc, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
VERTEX_SENTINELS_DECODED = [
    0xff, 0, 0, 0, 0xfe, 0, 0, 0, 0xfd, 0, 0, 0, 0xfd, 0, 0, 0,
    0xfd, 0, 0, 0, 0xfc, 0, 0, 0, 0xfb, 0, 0, 0, 0xfb, 0, 0, 0,
    0xfa, 0, 0, 0, 0xfa, 0, 0, 0, 0xf9, 0, 0, 0, 0xf9, 0, 0, 0,
    0xf8, 0, 0, 0]

INDEX_V0 = bytes([
    0xe0, 0xf0, 0x10, 0xfe, 0xff, 0xf0, 0x0c, 0xff, 0x02, 0x02, 0x02, 0x00, 0x76, 0x87, 0x56, 0x67,
    0x78, 0xa9, 0x86, 0x65, 0x89, 0x68, 0x98, 0x01, 0x69, 0x00, 0x00])
INDEX_V0_DECODED = [0, 1, 2, 2, 1, 3, 4, 6, 5, 7, 8, 9]

#: Restarts (0 1 2) and the last-adjacent codes of version 1.
INDEX_V1 = bytes([
    0xe1, 0xf0, 0x10, 0xfe, 0x1f, 0x3d, 0x00, 0x0a, 0x00, 0x76, 0x87, 0x56, 0x67, 0x78, 0xa9, 0x86,
    0x65, 0x89, 0x68, 0x98, 0x01, 0x69, 0x00, 0x00])
INDEX_V1_DECODED = [0, 1, 2, 2, 1, 3, 0, 1, 2, 2, 1, 5, 2, 1, 4]

INDEX_THREE_EDGES = bytes([
    0xe1, 0xf0, 0x20, 0x30, 0x40, 0x00, 0x76, 0x87, 0x56, 0x67, 0x78, 0xa9, 0x86, 0x65, 0x89, 0x68,
    0x98, 0x01, 0x69, 0x00, 0x00])
INDEX_THREE_EDGES_DECODED = [0, 1, 2, 1, 0, 3, 2, 1, 4, 0, 2, 5]

SEQUENCE_V1 = bytes([0xd1, 0x00, 0x04, 0xcd, 0x01, 0x04, 0x07, 0x98, 0x1f, 0x00, 0x00, 0x00, 0x00])
SEQUENCE_V1_DECODED = [0, 1, 51, 2, 49, 1000]

#: 0 1 2 0 2 3 against baseline 0: deltas 0 1 1 -2 2 1, zigzagged and shifted.
QUAD_SEQUENCE = bytes([0xd1, 0x00, 0x04, 0x04, 0x06, 0x08, 0x04, 0x00, 0x00, 0x00, 0x00])


class TestAttributes:
    @pytest.mark.parametrize('stream', [VERTEX_V0, VERTEX_V1, VERTEX_V1_CUSTOM],
                             ids=['v0', 'v1', 'v1-every-feature'])
    def test_reference_vertices(self, stream):
        decoded = meshopt.decode_attributes(stream, 4, 12)
        assert decoded.dtype == np.uint8
        assert np.array_equal(decoded, PV_BYTES)

    def test_version_0_with_every_group_width(self):
        decoded = meshopt.decode_attributes(VERTEX_V0_MORE, 16, 4)
        assert decoded.ravel().tolist() == VERTEX_V0_MORE_DECODED

    def test_version_1_two_byte_deltas(self):
        decoded = meshopt.decode_attributes(VERTEX_V1_DELTAS, 16, 8)
        assert decoded.view('<u2').ravel().tolist() == VERTEX_V1_DELTAS_DECODED

    def test_version_1_sentinels_in_a_partial_group(self):
        decoded = meshopt.decode_attributes(VERTEX_SENTINELS, 13, 4)
        assert decoded.ravel().tolist() == VERTEX_SENTINELS_DECODED

    def test_many_blocks(self):
        # 300 elements of 32 bytes is two blocks (256 + 44).
        values = (np.arange(300 * 8, dtype=np.uint32) * 2654435761).reshape(300, 8)
        stream = encode_attributes(values.view(np.uint8))
        assert np.array_equal(meshopt.decode_attributes(stream, 300, 32),
                              values.view(np.uint8))

    def test_spec_four_bit_sentinel_example(self):
        # Appendix A's example group, as a one-byte element stream of 16.
        group = bytes([0x17, 0x5f, 0xf0, 0xbc, 0x77, 0xa9, 0x21, 0x00, 0x34, 0xb5])
        header = bytes([0x02])       # group 0 uses mode 2: 4-bit deltas (v0)
        # Bytes 1-3 of each element: one header byte each, all-zero groups;
        # then the tail, padded to 32 bytes, ending in a zero baseline.
        stream = b'\xa0' + header + group + bytes(3) + bytes(32)
        decoded = meshopt.decode_attributes(stream, 16, 4)[:, 0].astype(np.int8)
        deltas = [-1, -4, -3, 26, -91, 0, -6, 6, -4, -4, 5, -5, 1, -1, 0, 0]
        assert decoded.tolist() == list(np.cumsum(deltas).astype(np.int8))

    @pytest.mark.parametrize('stream', [
        b'\x00' + VERTEX_V0[1:], b'\xa2' + VERTEX_V0[1:], VERTEX_V0[:-1],
        VERTEX_V0[:40], VERTEX_V0 + b'\x00', b''],
        ids=['header', 'version', 'short', 'truncated', 'extra', 'empty'])
    def test_malformed_streams_are_refused(self, stream):
        with pytest.raises(meshopt.MeshoptError):
            meshopt.decode_attributes(stream, 4, 12)

    def test_stride_must_be_a_multiple_of_four(self):
        with pytest.raises(meshopt.MeshoptError, match='multiple of 4'):
            meshopt.decode_attributes(VERTEX_V0, 4, 6)

    def test_undefined_channel_mode_is_refused(self):
        bad = VERTEX_V1[:-1] + b'\x03'
        with pytest.raises(meshopt.MeshoptError, match='channel mode'):
            meshopt.decode_attributes(bad, 4, 12)


class TestIndices:
    @pytest.mark.parametrize('stream, expected', [
        (INDEX_V0, INDEX_V0_DECODED), (INDEX_V1, INDEX_V1_DECODED),
        (INDEX_THREE_EDGES, INDEX_THREE_EDGES_DECODED)], ids=['v0', 'v1', 'edges'])
    def test_reference_triangles(self, stream, expected):
        assert meshopt.decode_triangles(stream, len(expected), 4).tolist() == expected
        short = meshopt.decode_triangles(stream, len(expected), 2)
        assert short.dtype == np.uint16 and short.tolist() == expected

    def test_reference_sequence(self):
        assert meshopt.decode_indices(SEQUENCE_V1, 6, 4).tolist() == SEQUENCE_V1_DECODED
        assert meshopt.decode_indices(SEQUENCE_V1, 6, 2).dtype == np.uint16

    def test_explicit_triangles(self):
        triangles = [70000, 3, 99, 5, 70000, 12]
        stream = encode_explicit_triangles(triangles)
        assert meshopt.decode_triangles(stream, 6, 4).tolist() == triangles
        assert meshopt.decode_triangles(stream, 6, 2).tolist() == [
            v & 0xFFFF for v in triangles]

    @pytest.mark.parametrize('decode, stream, count', [
        (meshopt.decode_triangles, INDEX_V1 + b'\x00', 15),
        (meshopt.decode_triangles, b'\xd1' + INDEX_V1[1:], 15),
        (meshopt.decode_triangles, INDEX_V1, 14),
        (meshopt.decode_indices, SEQUENCE_V1[:-1], 6),
        (meshopt.decode_indices, b'\xe1' + SEQUENCE_V1[1:], 6),
        (meshopt.decode_indices, SEQUENCE_V1, 5),
    ])
    def test_malformed_streams_are_refused(self, decode, stream, count):
        with pytest.raises(meshopt.MeshoptError):
            decode(stream, count, 4)

    def test_index_stride_must_be_two_or_four(self):
        with pytest.raises(meshopt.MeshoptError, match='2 or 4'):
            meshopt.decode_indices(SEQUENCE_V1, 6, 1)


class TestFilters:
    def test_none_passes_through(self):
        data = np.arange(8, dtype=np.uint8).reshape(2, 4)
        assert meshopt.apply_filter('NONE', data) is data

    def test_octahedral_unit_axes(self):
        # (x, y, one, w): +z, -z (folded), +x; K = 8 so one is 127.
        encoded = np.array([[0, 0, 127, 5], [127, 0, 127, -1]], np.int8)
        decoded = meshopt.apply_filter('OCTAHEDRAL', encoded.view(np.uint8)).view(np.int8)
        assert decoded[0].tolist() == [0, 0, 127, 5]
        assert decoded[1].tolist() == [127, 0, 0, -1]

    def test_octahedral_lower_hemisphere_sixteen_bit(self):
        one = (1 << 11) - 1                     # K = 12 in a 16-bit component
        encoded = np.array([[one // 2, one // 2 + 1, one, 7]], '<i2')
        decoded = meshopt.apply_filter('OCTAHEDRAL', encoded.view(np.uint8)).view('<i2')
        vector = decoded[0, :3] / 32767.0
        assert np.isclose(np.linalg.norm(vector), 1.0, atol=1e-4)
        assert decoded[0, 3] == 7

    def test_quaternion_identity_and_rotation(self):
        one = (1 << 15) - 1                       # K = 16, low two bits replaced
        identity = [0, 0, 0, (one & ~3) | 3]      # largest component w (index 3)
        half = int(round(0.5 * np.sqrt(2.0) * one))
        rotated = [half, 0, 0, (one & ~3) | 0]    # largest component x
        encoded = np.array([identity, rotated], '<i2')
        decoded = meshopt.apply_filter('QUATERNION', encoded.view(np.uint8)).view('<i2')
        assert decoded[0].tolist() == [0, 0, 0, 32767]
        q = decoded[1] / 32767.0
        assert np.allclose(q, [np.sqrt(0.75), 0.5, 0, 0], atol=1e-4)

    def test_exponential_is_exact(self):
        def word(exponent, mantissa):
            return ((exponent & 0xFF) << 24) | (mantissa & 0xFFFFFF)
        encoded = np.array([[word(0, 1), word(-1, 3), word(4, -5), word(-100, 1)]],
                           np.uint32)
        decoded = meshopt.apply_filter('EXPONENTIAL', encoded.view(np.uint8)).view('<f4')
        assert decoded.ravel().tolist() == [1.0, 1.5, -80.0, np.float32(2.0 ** -100)]

    def test_color_ycocg(self):
        # K = 8: luma 100, Co 20, Cg -10 -> R 130, G 90, B 90; alpha holds
        # 7 bits (64) under the marker bit, widened to 8 by repeating its low bit.
        encoded = np.array([[100, 20, (-10) & 0xFF, 0x80 | 0x40]], np.uint8)
        decoded = meshopt.apply_filter('COLOR', encoded)
        assert decoded[0].tolist() == [130, 90, 90, 128]

    def test_color_sixteen_bit_lower_precision(self):
        # K = 10: alpha holds 9 bits under bit 9; components scale by 65535/1023.
        encoded = np.array([[512, 0, 0, (1 << 9) | 511]], '<u2')
        decoded = meshopt.apply_filter('COLOR', encoded.view(np.uint8)).view('<u2')
        assert decoded[0].tolist() == [int(512 * 65535 / 1023 + 0.5)] * 3 + [65535]

    @pytest.mark.parametrize('name, stride', [
        ('OCTAHEDRAL', 12), ('QUATERNION', 4), ('COLOR', 16), ('EXPONENTIAL', 6),
        ('SHARPEN', 4)])
    def test_filter_needs_its_stride(self, name, stride):
        with pytest.raises(meshopt.MeshoptError):
            meshopt.apply_filter(name, np.zeros((2, stride), np.uint8))


class TestDecodeView:
    def test_view_length_must_match(self):
        extension = {'mode': 'ATTRIBUTES', 'count': 4, 'byteStride': 12}
        with pytest.raises(meshopt.MeshoptError, match='cannot fill'):
            meshopt.decode_view(extension, VERTEX_V0, 40)

    def test_filters_only_apply_to_attributes(self):
        extension = {'mode': 'TRIANGLES', 'count': 12, 'byteStride': 4,
                     'filter': 'OCTAHEDRAL'}
        with pytest.raises(meshopt.MeshoptError, match='applies to ATTRIBUTES'):
            meshopt.decode_view(extension, INDEX_V0, 48)

    @pytest.mark.parametrize('extension', [
        {'mode': 'VERTICES', 'count': 1, 'byteStride': 4},
        {'mode': 'ATTRIBUTES', 'count': -1, 'byteStride': 4},
        {'mode': 'ATTRIBUTES', 'count': 1.5, 'byteStride': 4},
    ])
    def test_invalid_extension_objects(self, extension):
        with pytest.raises(meshopt.MeshoptError):
            meshopt.decode_view(extension, VERTEX_V0)

    def test_sequence_view(self):
        extension = {'mode': 'INDICES', 'count': 6, 'byteStride': 4}
        decoded = meshopt.decode_view(extension, SEQUENCE_V1, 24)
        assert list(struct.unpack('<6I', decoded)) == SEQUENCE_V1_DECODED


# --------------------------------------------------------------------------- #
# A minimal encoder, for building documents
# --------------------------------------------------------------------------- #
def encode_attributes(elements):
    """Version 0 stream storing every delta as a full byte (header mode 3)."""
    elements = np.ascontiguousarray(elements, np.uint8)
    count, stride = elements.shape
    block = min((8192 // stride) & ~15, 256)
    previous = elements[0].copy()
    out = bytearray(b'\xa0')
    for start in range(0, count, block):
        chunk = elements[start:start + block]
        groups = (len(chunk) + 15) // 16
        padded = np.zeros((groups * 16, stride), np.uint8)
        padded[:len(chunk)] = chunk
        deltas = np.zeros_like(padded)
        deltas[:len(chunk)] = chunk - np.vstack([previous[None], chunk[:-1]])
        previous = chunk[-1].copy()
        zigzag = ((deltas << 1) ^ (0 - (deltas >> 7))).astype(np.uint8)
        for byte in range(stride):
            out += b'\xff' * ((groups + 3) // 4)
            out += zigzag[:, byte].tobytes()
    out += bytes(max(0, 32 - stride))
    out += elements[0].tobytes()
    return bytes(out)


def _varint(value):
    out = bytearray()
    while True:
        out.append((value & 0x7F) | (0x80 if value > 0x7F else 0))
        value >>= 7
        if not value:
            return bytes(out)


def encode_explicit_triangles(indices):
    """Version 1 triangles, each coded 0xff with all three indices explicit."""
    codes = bytearray()
    data = bytearray()
    last = 0
    for start in range(0, len(indices), 3):
        codes.append(0xFF)
        data.append(0xFF)
        for index in indices[start:start + 3]:
            delta = (index - last) & 0xFFFFFFFF
            signed = delta - (1 << 32) if delta >> 31 else delta
            data += _varint(((signed << 1) ^ (signed >> 31)) & 0xFFFFFFFF)
            last = index
    return bytes(b'\xe1' + codes + data + bytes(16))


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
QUAD = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], np.float32)
QUAD_INDICES = [0, 1, 2, 0, 2, 3]


def _mesh(scene):
    stack = [scene.group]
    while stack:
        node = stack.pop()
        if getattr(node, 'geometry', None) is not None:
            return node.geometry
        stack.extend(getattr(node, 'children', None) or [])
    raise AssertionError('no Shape in the loaded scene')


def _meshopt_quad(name='KHR_meshopt_compression', fallback=True, index_mode='TRIANGLES'):
    """A GLB of :func:`_meshopt_quad_document`."""
    return _pack_glb(*_meshopt_quad_document(name, fallback, index_mode))


def _meshopt_quad_document(name='KHR_meshopt_compression', fallback=True,
                           index_mode='TRIANGLES'):
    """A quad whose positions and indices are both meshopt views over buffer 0,
    with buffer 1 the uncompressed stand-in; the document and its binary chunk."""
    positions = encode_attributes(QUAD.view(np.uint8).reshape(4, 12))
    if index_mode == 'TRIANGLES':
        indices = encode_explicit_triangles(QUAD_INDICES)
    else:
        indices = QUAD_SEQUENCE
    compressed = positions + bytes(-len(positions) % 4) + indices
    stand_in = {'byteLength': 48 + 24}
    if fallback:
        stand_in['extensions'] = {name: {'fallback': True}}
    index_count = 6
    views = [
        {'buffer': 1, 'byteOffset': 0, 'byteLength': 48, 'byteStride': 12,
         'extensions': {name: {'buffer': 0, 'byteOffset': 0,
                               'byteLength': len(positions), 'byteStride': 12,
                               'mode': 'ATTRIBUTES', 'count': 4}}},
        {'buffer': 1, 'byteOffset': 48, 'byteLength': 24,
         'extensions': {name: {'buffer': 0,
                               'byteOffset': len(positions) + (-len(positions) % 4),
                               'byteLength': len(indices), 'byteStride': 4,
                               'mode': index_mode, 'count': index_count}}},
    ]
    doc = {
        'asset': {'version': '2.0'},
        'extensionsUsed': [name], 'extensionsRequired': [name],
        'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 4,
             'min': [0, 0, 0], 'max': [1, 1, 0]},
            {'bufferView': 1, 'componentType': 5125, 'type': 'SCALAR',
             'count': index_count}],
        'bufferViews': views,
        'buffers': [{'byteLength': len(compressed)}, stand_in],
    }
    return doc, compressed


class TestDocuments:
    @pytest.mark.parametrize('name', meshopt.EXTENSIONS)
    def test_compressed_positions_and_triangles(self, name):
        mesh = _mesh(load_gltf(_meshopt_quad(name)))
        assert np.array_equal(np.asarray(mesh.positions).reshape(-1, 3), QUAD)
        assert np.asarray(mesh.indices).ravel().tolist() == QUAD_INDICES

    def test_buffer_without_fallback_flag(self):
        mesh = _mesh(load_gltf(_meshopt_quad(fallback=False)))
        assert np.asarray(mesh.indices).ravel().tolist() == QUAD_INDICES

    def test_index_sequence_view(self):
        mesh = _mesh(load_gltf(_meshopt_quad(index_mode='INDICES')))
        assert np.asarray(mesh.indices).ravel().tolist() == QUAD_INDICES

    def test_a_view_two_accessors_read_is_decoded_once(self, monkeypatch):
        doc, compressed = _meshopt_quad_document()
        doc['accessors'].append(dict(doc['accessors'][0]))
        doc['meshes'][0]['primitives'][0]['attributes']['NORMAL'] = 2
        decoded = []
        real = meshopt.decode_view

        def counting(extension, data, length=None):
            decoded.append(extension['mode'])
            return real(extension, data, length)
        monkeypatch.setattr(meshopt, 'decode_view', counting)
        load_gltf(_pack_glb(doc, compressed))
        assert sorted(decoded) == ['ATTRIBUTES', 'TRIANGLES']

    def test_a_plain_view_over_the_fallback_buffer_is_refused(self):
        doc, compressed = _meshopt_quad_document()
        del doc['bufferViews'][1]['extensions']
        with pytest.raises(ValueError, match='meshopt fallback'):
            load_gltf(_pack_glb(doc, compressed))

    def test_fallback_buffer_detection(self):
        class Buffer:
            extensions = {'EXT_meshopt_compression': {'fallback': True}}
        assert meshopt.is_fallback_buffer(Buffer())
        assert not meshopt.is_fallback_buffer(object())


@pytest.mark.network
class TestKhronosSamples:
    """Khronos glTF-Sample-Assets models published with and without meshopt."""

    BASE = 'https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models'

    def _pair(self, model, variant, tmp_path):
        plain = '%s/%s/glTF/%s.gltf' % (self.BASE, model, model)
        packed = '%s/%s/%s/%s.gltf' % (self.BASE, model, variant, model)
        reason = unreachable(plain, str(tmp_path))
        if reason:
            pytest.skip(reason)
        return (load_gltf_url(plain, str(tmp_path)), load_gltf_url(packed, str(tmp_path)))

    @pytest.mark.parametrize('variant', ['glTF-Meshopt', 'glTF-Meshopt-EXT'])
    def test_brainstem_matches_uncompressed(self, variant, tmp_path):
        plain, packed = self._pair('BrainStem', variant, tmp_path)
        assert np.allclose(plain.center, packed.center, atol=1e-2)
        assert abs(plain.radius - packed.radius) < 1e-2 * plain.radius
        assert len(plain.animations) == len(packed.animations)
        # gltfpack resamples keyframes at 30 per second.
        assert np.isclose(plain.animations[0].duration, packed.animations[0].duration,
                          atol=1 / 30.0)

    def test_meshopt_cube_test(self, tmp_path):
        url = '%s/MeshoptCubeTest/glTF-Meshopt/MeshoptCubeTest.gltf' % (self.BASE,)
        reason = unreachable(url, str(tmp_path))
        if reason:
            pytest.skip(reason)
        scene = load_gltf_url(url, str(tmp_path))
        assert scene.radius > 0
