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


def _many_glb_bytes(parts):
    """Pack several named meshes against ONE embedded PNG.

    What a baked plant is: every variant of it and every geometry rung, sharing
    the one cutout texture they were all scanned from.
    """
    png = io.BytesIO()
    Image.new("RGBA", (2, 2), (40, 120, 40, 255)).save(png, format="PNG")
    png_bytes = png.getvalue()

    data, views, accessors, meshes = bytearray(), [], [], []

    def view(blob):
        views.append({"buffer": 0, "byteOffset": len(data),
                      "byteLength": len(blob)})
        data.extend(blob)
        while len(data) % 4:
            data.append(0)
        return len(views) - 1

    for name, P, N, UV, idx in parts:
        P = np.asarray(P, '<f4')
        N = np.asarray(N, '<f4')
        UV = np.asarray(UV, '<f4')
        idx = np.asarray(idx, '<u4')
        first = len(accessors)
        for blob, kind, count in ((P.tobytes(), "VEC3", len(P)),
                                  (N.tobytes(), "VEC3", len(N)),
                                  (UV.tobytes(), "VEC2", len(UV))):
            accessors.append({"bufferView": view(blob), "componentType": 5126,
                              "count": count, "type": kind})
        accessors.append({"bufferView": view(idx.tobytes()),
                          "componentType": 5125, "count": len(idx),
                          "type": "SCALAR"})
        meshes.append({"name": name, "primitives": [{
            "attributes": {"POSITION": first, "NORMAL": first + 1,
                           "TEXCOORD_0": first + 2},
            "indices": first + 3}]})
    image_view = view(png_bytes)

    gltf = {"asset": {"version": "2.0"},
            "buffers": [{"byteLength": len(data)}], "bufferViews": views,
            "accessors": accessors, "meshes": meshes,
            "images": [{"bufferView": image_view, "mimeType": "image/png"}]}
    js = json.dumps(gltf).encode("utf-8")
    while len(js) % 4:
        js += b' '
    out = bytearray()
    out += struct.pack('<III', 0x46546C67, 2,
                       12 + 8 + len(js) + 8 + len(data))
    out += struct.pack('<II', len(js), 0x4E4F534A) + js
    out += struct.pack('<II', len(data), 0x004E4942) + bytes(data)
    return bytes(out)


class TestOneFileHoldsEveryRungOfAPlant:
    """A baked plant is several meshes against one texture.

    A 1k cutout texture is about a megabyte; a file per variant and rung would
    carry it over and over. So the variants and the near/far rungs live in one
    file and are chosen by name or by index.
    """

    def _plant(self, tmp_path):
        near = _two_blades()
        coarse = _ribbon(n_rings=3)
        path = tmp_path / "fern.glb"
        path.write_bytes(_many_glb_bytes([
            ("fern_a_near", *near), ("fern_a_far", *coarse)]))
        return str(path)

    def test_the_first_mesh_is_what_it_reads_by_default(self, tmp_path) -> None:
        path = self._plant(tmp_path)
        assert len(load_clump_glb(path)[3]) \
            == len(load_clump_glb(path, mesh=0)[3])

    def test_a_rung_can_be_asked_for_by_index(self, tmp_path) -> None:
        path = self._plant(tmp_path)
        assert len(load_clump_glb(path, mesh=1)[3]) \
            < len(load_clump_glb(path, mesh=0)[3])

    def test_a_rung_can_be_asked_for_by_name(self, tmp_path) -> None:
        path = self._plant(tmp_path)
        np.testing.assert_array_equal(load_clump_glb(path, mesh='fern_a_far')[3],
                                      load_clump_glb(path, mesh=1)[3])

    def test_every_rung_reads_the_same_texture(self, tmp_path) -> None:
        path = self._plant(tmp_path)
        assert load_clump_glb(path, mesh=0)[4].tobytes() \
            == load_clump_glb(path, mesh=1)[4].tobytes()

    def test_a_name_the_file_does_not_have_says_what_it_does(self,
                                                             tmp_path) -> None:
        path = self._plant(tmp_path)
        with pytest.raises(KeyError) as raised:
            load_clump_glb(path, mesh='fern_b_near')
        assert 'fern_a_near' in str(raised.value)      # names what there is


    @pytest.mark.parametrize('index', [-1, 2, 9])
    def test_a_position_the_file_does_not_have_says_what_it_does(
            self, tmp_path, index) -> None:
        path = self._plant(tmp_path)
        with pytest.raises(KeyError) as raised:
            load_clump_glb(path, mesh=index)
        assert 'fern_a_near' in str(raised.value)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
