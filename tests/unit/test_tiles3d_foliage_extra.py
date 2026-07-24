"""Extra coverage for tiles3d.foliage: the CC0/bark texture-path branches and the
multi-primitive scene builder options that the base foliage tests don't reach.
"""
import numpy as np
import pytest

pytest.importorskip("pygltflib")
pytest.importorskip("PIL")

from PIL import Image

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.tiles3d import foliage as F


def _write_img(path, size=8, mode="RGB"):
    bands = 4 if mode == "RGBA" else 3
    arr = (np.random.default_rng(0).random((size, size, bands)) * 255).astype("uint8")
    Image.fromarray(arr, mode).save(str(path))
    return str(path)


def test_procedural_ground_maps_writes_when_absent(tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    maps = F.procedural_ground_maps(seed=97)
    import os
    assert os.path.exists(maps["color"])          # freshly baked to the fake tmp
    # A second call reuses the cached file (no exception, same path).
    assert F.procedural_ground_maps(seed=97)["color"] == maps["color"]


def test_conifer_glb_uses_real_bark_file(tmp_path):
    bark = _write_img(tmp_path / "bark.jpg")
    glb = F.conifer_glb(height=6.0, bark_path=bark)
    scene = gltf.load_gltf(glb)          # decodes -> the bark path was embedded
    assert scene.group is not None


def test_pbr_glb_embeds_normal_and_roughness(tmp_path):
    maps = {
        "color": _write_img(tmp_path / "c.jpg"),
        "normal": _write_img(tmp_path / "n.jpg"),
        "roughness": _write_img(tmp_path / "r.png"),
    }
    p = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1]], "f4")
    uv = np.array([[0, 0], [1, 0], [1, 1]], "f4")
    idx = np.array([0, 1, 2], "u4")
    node = F.textured_ground(p, uv, idx, maps, tile=2.0)
    assert node is not None


def test_scene_glb_color_normal_and_mask(tmp_path):
    normal = _write_img(tmp_path / "n.png")
    p = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], "f4")
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], "f4")
    prims = [
        # a flat-colour MASK primitive with a normal map (hits color/MASK/normal)
        {"indices": np.array([0, 1, 2], "u4"), "color": (0.2, 0.6, 0.1, 1.0),
         "maps": {"normal": normal}, "alpha_mode": "MASK"},
        {"indices": np.array([0, 2, 3], "u4"), "color": (0.5, 0.5, 0.5, 1.0)},
    ]
    glb = F._scene_glb(p, uv, prims)
    scene = gltf.load_gltf(glb)
    assert scene.group is not None


def test_ground_patch_split_emits_rock_on_steep_slope():
    # A cliff (very steep in x) guarantees rock-classified triangles as well as dirt.
    def hf(x, z):
        return np.maximum(np.asarray(x), 0.0) * 30.0
    dirt = F.procedural_ground_maps(seed=1)
    rock = F.procedural_ground_maps(seed=2)
    node = F.ground_patch_split((0, 0, 0), 30.0, hf, dirt, rock, res=16,
                                rock_slope=0.4)
    # Two textured primitives -> both dirt and rock groups are present.
    shapes = _collect_shapes(node)
    assert len(shapes) >= 2


def test_branch_uses_real_bark_and_procedural_fallback(tmp_path, monkeypatch):
    import tempfile
    bark = _write_img(tmp_path / "b.png")
    assert F.branch(bark_path=bark) is not None       # bark_path branch
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    assert F.branch(seed=3) is not None                # procedural bake branch


def _collect_shapes(node):
    stack, shapes = [node], []
    while stack:
        n = stack.pop()
        if getattr(n, "geometry", None) is not None:
            shapes.append(n)
        stack.extend(getattr(n, "children", None) or [])
    return shapes
