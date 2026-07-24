"""GLB clump loader (:func:`load_clump_glb`) — pure CPU, no GL.

Builds a minimal in-memory ``.glb`` (single mesh, embedded PNG) and drives the
loader that the forest demo uses to pull a grass-clump mesh: accessor/bufferView
parsing, height normalization, embedded-image decode, and the optional
length-decimation hand-off.
"""
import io
import json
import struct

import numpy as np
import pytest
from PIL import Image

from OpenGLContext.scenegraph.vegetation.clumps import load_clump_glb


def _glb_bytes(P, N, UV, idx):
    """Pack arrays + a tiny PNG into a valid single-mesh binary glTF."""
    P = np.asarray(P, '<f4')
    N = np.asarray(N, '<f4')
    UV = np.asarray(UV, '<f4')
    idx = np.asarray(idx, '<u4')
    png = io.BytesIO()
    Image.new("RGBA", (2, 2), (40, 120, 40, 255)).save(png, format="PNG")
    png_bytes = png.getvalue()

    blobs = [P.tobytes(), N.tobytes(), UV.tobytes(), idx.tobytes(), png_bytes]
    bin_data = bytearray()
    real_offsets = []
    for blob in blobs:
        real_offsets.append(len(bin_data))
        bin_data += blob
        while len(bin_data) % 4:                    # keep 4-byte alignment
            bin_data += b'\x00'

    n = len(P)
    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(bin_data)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": real_offsets[0], "byteLength": len(blobs[0])},
            {"buffer": 0, "byteOffset": real_offsets[1], "byteLength": len(blobs[1])},
            {"buffer": 0, "byteOffset": real_offsets[2], "byteLength": len(blobs[2])},
            {"buffer": 0, "byteOffset": real_offsets[3], "byteLength": len(blobs[3])},
            {"buffer": 0, "byteOffset": real_offsets[4], "byteLength": len(png_bytes)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": n, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": n, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": n, "type": "VEC2"},
            {"bufferView": 3, "componentType": 5125, "count": len(idx), "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
            "indices": 3}]}],
        "images": [{"bufferView": 4, "mimeType": "image/png"}],
    }
    json_bytes = json.dumps(gltf).encode("utf-8")
    while len(json_bytes) % 4:
        json_bytes += b' '
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_data)
    out = bytearray()
    out += struct.pack('<III', 0x46546C67, 2, total)
    out += struct.pack('<II', len(json_bytes), 0x4E4F534A) + json_bytes
    out += struct.pack('<II', len(bin_data), 0x004E4942) + bytes(bin_data)
    return bytes(out)


def _ribbon(n_rings=6, y0=0.0, x=0.0):
    """A single blade ribbon: n_rings cross-pairs stacked in +y, UV.v 0..1."""
    P, N, UV, idx = [], [], [], []
    base = 0
    for r in range(n_rings):
        v = r / (n_rings - 1)
        P += [(x - 0.05, y0 + v, 0.0), (x + 0.05, y0 + v, 0.0)]
        N += [(0, 0, 1), (0, 0, 1)]
        UV += [(0.0, v), (1.0, v)]
        if r > 0:
            a, b_, c, d = base - 2, base - 1, base, base + 1
            idx += [a, b_, c, b_, d, c]
        base += 2
    return P, N, UV, idx


def _two_blades():
    P1, N1, UV1, I1 = _ribbon(x=0.0)
    P2, N2, UV2, I2 = _ribbon(x=1.0)
    off = len(P1)
    P = P1 + P2
    N = N1 + N2
    UV = UV1 + UV2
    idx = I1 + [i + off for i in I2]
    return P, N, UV, idx


def _write_glb(tmp_path, P, N, UV, idx):
    path = tmp_path / "clump.glb"
    path.write_bytes(_glb_bytes(P, N, UV, idx))
    return str(path)


def test_loads_mesh_arrays_and_texture(tmp_path):
    P, N, UV, idx = _two_blades()
    path = _write_glb(tmp_path, P, N, UV, idx)
    lp, ln, luv, lidx, tex = load_clump_glb(path, normalize_height=False)
    assert lp.shape == (len(P), 3)
    assert ln.shape == (len(N), 3)
    assert luv.shape == (len(UV), 2)
    assert lidx.shape == (len(idx),)
    assert isinstance(tex, Image.Image) and tex.mode == "RGBA"


def test_normalize_height_makes_unit_tall_base_at_zero(tmp_path):
    # Raise the whole clump so base != 0 and height != 1 before normalizing.
    P, N, UV, idx = _two_blades()
    P = [(x, y + 3.0, z) for (x, y, z) in P]       # shift up
    P = [(x, y * 4.0, z) for (x, y, z) in P]       # and make it 4x tall-ish
    path = _write_glb(tmp_path, P, N, UV, idx)
    lp, _n, _uv, _idx, _tex = load_clump_glb(path, normalize_height=True)
    assert lp[:, 1].min() == pytest.approx(0.0, abs=1e-6)
    assert lp[:, 1].max() == pytest.approx(1.0, abs=1e-6)


def test_length_samples_decimates_triangles(tmp_path):
    P, N, UV, idx = _two_blades()
    path = _write_glb(tmp_path, P, N, UV, idx)
    _p_full, _n, _uv, idx_full, _t = load_clump_glb(path, length_samples=None)
    _p, _n2, _uv2, idx_dec, _t2 = load_clump_glb(path, length_samples=3)
    assert len(idx_dec) < len(idx_full)            # rings collapsed -> fewer tris
    assert len(idx_dec) % 3 == 0                    # still whole triangles


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
