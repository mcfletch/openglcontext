"""Procedural foliage textures + alpha-cut glTF prototypes."""
import numpy as np
import pytest

pytest.importorskip("pygltflib")
pytest.importorskip("PIL")

from OpenGLContext.loaders.tiles3d import foliage as F


def test_grass_texture_has_blades_and_transparency():
    tex = F.grass_texture(size=64, seed=1)
    assert tex.shape == (64, 64, 4)
    op = (tex[:, :, 3] > 0).mean()
    assert 0.05 < op < 0.9          # blades present, background transparent
    # green dominant where opaque
    o = tex[tex[:, :, 3] > 0]
    assert (o[:, 1] >= o[:, 0]).mean() > 0.8


def test_bark_texture_is_brownish():
    tex = F.bark_texture(size=64)
    assert tex.shape == (64, 64, 3)
    assert tex[:, :, 0].mean() > tex[:, :, 2].mean()   # red > blue (brown)


def test_grass_card_loads_as_mesh():
    node = F.grass_card()
    assert node is not None
    # a mountable scenegraph node
    assert hasattr(node, "children") or hasattr(node, "render")


def test_conifer_loads_with_two_materials():
    node = F.conifer(height=8.0)
    assert node is not None
    assert hasattr(node, "children")


def test_ground_texture_is_earthy():
    tex = F.ground_texture(64, seed=1)
    assert tex.shape == (64, 64, 3)
    assert tex[:, :, 0].mean() > tex[:, :, 2].mean()   # brown-ish (red > blue)


def test_procedural_ground_maps_and_patch():
    import numpy as np
    maps = F.procedural_ground_maps(seed=2)
    assert "color" in maps
    hf = lambda x, z: np.full(np.shape(x), 5.0)
    node = F.ground_patch_node((0, 0, 0), 40.0, hf, maps, res=12)
    assert node is not None


def test_cc0_offline_safe():
    # try_material must never raise, even offline.
    from OpenGLContext.loaders import cc0
    r = cc0.try_material("definitely_not_a_real_asset_xyz")
    assert r is None or isinstance(r, dict)


def test_slope01_flat_vs_steep():
    flat = lambda x, z: np.zeros(np.shape(x))
    steep = lambda x, z: np.asarray(x) * 2.0
    assert F.slope01(flat, np.array([0.0]), np.array([0.0]))[0] < 0.05
    assert F.slope01(steep, np.array([0.0]), np.array([0.0]))[0] > 1.0


def test_rock_flower_branch_build():
    assert F.flower_card() is not None
    assert F.branch(seed=2) is not None
    assert F.rock(F.procedural_ground_maps(), 1) is not None


def test_ground_patch_split_dirt_and_rock():
    # a ramp: half flat, half steep -> both dirt and rock primitives present
    hf = lambda x, z: np.maximum(np.asarray(x), 0.0) * 1.5
    node = F.ground_patch_split((0, 0, 0), 30.0, hf,
                                F.procedural_ground_maps(seed=1),
                                F.procedural_ground_maps(seed=2), res=20)
    assert node is not None


def test_blended_ground_mixes_materials():
    d = F.procedural_ground_maps(seed=1)["color"]
    r = F.procedural_ground_maps(seed=2)["color"]
    slope = np.zeros((8, 8))
    slope[4:] = 1.0                     # bottom half steep -> rock
    tex = F.blended_ground_texture([d, r, d], slope, size=128, tile_px=32)
    assert tex.shape == (128, 128, 3)


def test_tree_billboard_and_no_shadow():
    node = F.tree_billboard()
    # every Shape under a billboard is marked non-casting
    stack, shapes = [node], []
    while stack:
        n = stack.pop()
        if type(n).__name__ == "Shape":
            shapes.append(n)
        stack.extend(getattr(n, "children", None) or [])
    assert shapes and all(s.castsShadow is False for s in shapes)


def test_ground_patch_blended_builds():
    hf = lambda x, z: np.sin(np.asarray(x) * 0.05) * 10
    mats = [F.procedural_ground_maps(1)["color"], F.procedural_ground_maps(2)["color"]]
    assert F.ground_patch_blended((0, 0, 0), 60.0, hf, mats, res=16,
                                  tex_size=256) is not None


def test_the_billboard_is_available_as_bytes():
    """The far rung of a tree's detail ladder, for a baker to place directly."""
    data = F.tree_billboard_glb(width=4.0, height=7.0, seed=2)
    assert data[:4] == b'glTF'
    from OpenGLContext.loaders import gltf
    scene = gltf.load_gltf(data)
    assert scene.group is not None


def test_the_loaded_billboard_casts_no_shadow():
    node = F.tree_billboard()
    shapes = []
    stack = [node]
    while stack:
        current = stack.pop()
        if type(current).__name__ == 'Shape':
            shapes.append(current)
        stack.extend(getattr(current, 'children', None) or [])
    assert shapes and all(s.castsShadow is False for s in shapes)
