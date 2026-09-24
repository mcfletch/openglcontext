"""Procedural surfaces: tileable PBR maps from NumPy.

The maps are plain arrays, so the engine turns them into a ``PBRMaterial`` and
a Blender script bakes the same ones into a model. These hold each surface to
what it is: it tiles, it is the same for the same seed, its values are in
range, and its pattern is the one it is named for.
"""
import ast
from pathlib import Path

import numpy as np
import pytest

from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

SIZE = 128


def _seam(image):
    """How much the wrap from last column to first differs, against a neighbour step."""
    across = np.abs(image[:, 0] - image[:, -1]).mean()
    inside = np.abs(np.diff(image, axis=1)).mean()
    return across / max(inside, 1e-9)


def test_noise_tiles_both_ways():
    noise = surfaces.tileable_noise(SIZE, cells=8, seed=3)
    assert noise.shape == (SIZE, SIZE)
    assert 0.0 <= noise.min() and noise.max() <= 1.0
    assert _seam(noise) < 2.0
    assert _seam(noise.T) < 2.0


def test_the_same_seed_is_the_same_surface():
    assert np.array_equal(surfaces.fbm(SIZE, 4, seed=9), surfaces.fbm(SIZE, 4, seed=9))
    assert not np.array_equal(surfaces.fbm(SIZE, 4, seed=9), surfaces.fbm(SIZE, 4, seed=10))


# A checker's texture edge is a tile joint, where the colour changes as it does
# at every joint, so the seam is measured on the others.
@pytest.mark.parametrize('make, seamless', [
    (lambda: surfaces.checkered_marble(SIZE), False),
    (lambda: surfaces.marble(SIZE), True),
    (lambda: surfaces.brick(SIZE), True),
    (lambda: surfaces.plaster(SIZE), True),
    (lambda: surfaces.brushed_metal(SIZE, surfaces.GOLD), True),
    (lambda: surfaces.sandstone(SIZE), True),
])
def test_every_surface_is_a_full_set_of_maps_in_range(make, seamless):
    maps = make()
    assert maps.base.shape == (SIZE, SIZE, 3)
    for channel in (maps.base, maps.roughness, maps.metallic, maps.height):
        assert 0.0 <= channel.min() and channel.max() <= 1.0
    if seamless:
        assert _seam(maps.base[..., 0]) < 2.5


def test_a_checkered_floor_has_dark_tiles_and_light_ones():
    maps = surfaces.checkered_marble(SIZE, tiles=2)
    lum = maps.base.mean(axis=-1)
    quarter = SIZE // 4
    first, second = lum[quarter, quarter], lum[quarter, quarter + SIZE // 2]
    assert abs(first - second) > 0.3


def test_the_grout_is_rougher_and_lower_than_the_stone():
    maps = surfaces.checkered_marble(SIZE, tiles=2)
    edge, middle = (0, SIZE // 4), (SIZE // 4, SIZE // 4)
    assert maps.roughness[edge] > maps.roughness[middle]
    assert maps.height[edge] < maps.height[middle]


def test_bricks_are_bonded_with_mortar_between():
    maps = surfaces.brick(SIZE, courses=4, bricks=2)
    mortar = maps.height < 0.2
    assert 0.05 < mortar.mean() < 0.35
    # Alternate courses are offset by half a brick: a mortar joint in one
    # course falls in the middle of a brick in the next.
    course = SIZE // 4
    joints = [np.flatnonzero(mortar[row].astype(int) - mortar[row].mean() > 0.5)
              for row in (course // 2, course + course // 2)]
    assert set(joints[0]).isdisjoint(set(joints[1]))


def test_a_metal_is_metallic_and_a_stone_is_not():
    assert surfaces.brushed_metal(SIZE, surfaces.COPPER).metallic.min() == 1.0
    assert surfaces.plaster(SIZE).metallic.max() == 0.0


def test_brushing_streaks_run_along_one_direction():
    rough = surfaces.brushed_metal(SIZE, surfaces.STEEL).roughness
    along = np.abs(np.diff(rough, axis=1)).mean()
    across = np.abs(np.diff(rough, axis=0)).mean()
    assert across > 2.0 * along


def test_a_flat_height_is_a_normal_straight_out():
    normal = surfaces.normal_map(np.full((8, 8), 0.5))
    assert np.allclose(normal, (0.5, 0.5, 1.0))


def test_a_slope_tilts_the_normal_away_from_the_rise():
    rise = np.tile(np.linspace(0.0, 1.0, 16), (16, 1))
    normal = surfaces.normal_map(rise, strength=4.0) * 2.0 - 1.0
    assert normal[8, 8, 0] < -0.1
    assert np.allclose(np.linalg.norm(normal, axis=-1), 1.0, atol=1e-6)


def test_a_material_carries_every_map_with_the_right_encoding():
    material = surfaces.pbr_material(surfaces.checkered_marble(SIZE), roughness=0.3)
    assert isinstance(material, PBRMaterial)
    textures = material.textures
    assert set(textures) == {'baseColor', 'metallicRoughness', 'normal'}
    assert textures['baseColor'].srgb and not textures['normal'].srgb
    assert material.roughness == pytest.approx(0.3)
    green = np.asarray(textures['metallicRoughness'].image)[..., 1]
    assert green.max() > green.min()


def test_the_module_needs_nothing_but_numpy_to_import():
    """A Blender script loads it by path, and Blender has NumPy and no engine."""
    tree = ast.parse(Path(surfaces.__file__).read_text(encoding='utf-8'))
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add(node.module.split('.')[0])
    assert imported <= {'__future__', 'dataclasses', 'typing', 'math', 'numpy'}
