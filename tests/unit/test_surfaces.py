"""Procedural surfaces: tileable PBR maps from NumPy.

The maps are plain arrays, so the engine turns them into a ``PBRMaterial`` and
a Blender script bakes the same ones into a model. These hold each surface to
what it is: it tiles, it is the same for the same seed, its values are in
range, and its pattern is the one it is named for.
"""
import ast
import math
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
    (lambda: surfaces.marble_tiles(SIZE), False),
    (lambda: surfaces.tiles(SIZE), False),
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


def test_black_marble_tiles_are_black_stone_veined_and_grouted():
    maps = surfaces.marble_tiles(SIZE, tiles=2)
    lum = maps.base.mean(axis=-1)
    quarter, half = SIZE // 4, SIZE // 2
    for top in (0, half):
        for left in (0, half):
            assert lum[top:top + half, left:left + half].mean() < 0.2
    stone = lum[SIZE // 8:3 * SIZE // 8, SIZE // 8:3 * SIZE // 8]
    assert stone.max() > stone.min() + 0.15              # veined, not flat
    edge, middle = (0, quarter), (quarter, quarter)
    assert maps.roughness[edge] > maps.roughness[middle]
    assert maps.height[edge] < maps.height[middle]


def test_glazed_tiles_are_a_grid_of_near_colours_in_rough_grout():
    maps = surfaces.tiles(SIZE, count=4, colour=(0.1, 0.4, 0.5))
    step = SIZE // 4
    centres = maps.base[step // 2::step, step // 2::step]
    assert centres.shape[:2] == (4, 4)
    assert np.allclose(centres.mean(axis=(0, 1)), (0.1, 0.4, 0.5), atol=0.06)
    assert np.ptp(centres[..., 1]) > 0.01                  # each tile its own shade
    assert maps.roughness[0, step // 2] > maps.roughness[step // 2, step // 2]
    assert maps.height[0, step // 2] < maps.height[step // 2, step // 2]


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


# --- geometry that wears a surface at its size ------------------------------------

def _faces(geometry):
    """Each triangle's corners, and its winding normal."""
    corners = geometry.positions[geometry.indices.reshape(-1, 3)]
    winding = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    return corners, winding


def _texture_runs_along_the_tangents(geometry):
    """On every triangle, u grows along the tangent and v against normal x
    tangent, the bitangent: v runs down a face, as glTF's does.

    Measured against the triangle's mean tangent and normal: on a curved mesh
    each corner's are the smooth surface's, half a facet away from the
    triangle's own plane.
    """
    triangles = geometry.indices.reshape(-1, 3)
    for corners in triangles:
        p = geometry.positions[corners].astype('d')
        uv = geometry.texcoords[corners].astype('d')
        edges, steps = np.array([p[1] - p[0], p[2] - p[0]]), np.array([uv[1] - uv[0], uv[2] - uv[0]])
        along_u, along_v = np.linalg.solve(steps, edges)
        tangent = geometry.tangents[corners, :3].mean(axis=0)
        tangent /= np.linalg.norm(tangent)
        normal = geometry.normals[corners].mean(axis=0)
        bitangent = np.cross(normal / np.linalg.norm(normal), tangent) * geometry.tangents[corners[0], 3]
        assert np.dot(along_u, tangent) > 0.99 * np.linalg.norm(along_u)
        assert np.dot(along_v, bitangent) < -0.99 * np.linalg.norm(along_v)


def test_a_panel_repeats_its_surface_every_so_many_metres():
    panel = surfaces.panel(4.0, 3.0, repeat=2.0)
    assert np.ptp(panel.texcoords[:, 0]) == pytest.approx(2.0)
    assert np.ptp(panel.texcoords[:, 1]) == pytest.approx(1.5)
    _corners, winding = _faces(panel)
    assert (winding[:, 2] > 0).all() and np.allclose(panel.normals, (0, 0, 1))
    _texture_runs_along_the_tangents(panel)


def test_a_block_faces_out_on_every_side_and_is_textured_by_the_metre():
    block = surfaces.block((2.0, 1.0, 0.5), repeat=0.5)
    corners, winding = _faces(block)
    centres = corners.mean(axis=1)
    assert (np.einsum('ij,ij->i', winding, centres) > 0).all()
    assert len(block.positions) == 24 and len(block.indices) == 36
    spans = {tuple(np.round(np.ptp(block.texcoords[face * 4:face * 4 + 4], axis=0), 6))
             for face in range(6)}
    assert spans == {(4.0, 2.0), (1.0, 2.0), (4.0, 1.0)}
    _texture_runs_along_the_tangents(block)


def test_a_polygon_is_a_flat_disc_of_so_many_sides():
    octagon = surfaces.polygon(1.5, sides=8, repeat=1.0)
    _corners, winding = _faces(octagon)
    assert len(octagon.indices) == 3 * 8 and (winding[:, 2] > 0).all()
    assert np.linalg.norm(octagon.positions[1:, :2], axis=1) == pytest.approx(np.full(8, 1.5))
    assert np.ptp(octagon.texcoords[:, 0]) == pytest.approx(np.ptp(octagon.positions[:, 0]))
    _texture_runs_along_the_tangents(octagon)


def test_a_shape_wears_its_material_where_it_is_put():
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    material = surfaces.pbr_material(surfaces.plaster(16))
    placed = surfaces.shape(surfaces.panel(1.0, 1.0), material,
                            translation=(1.0, 2.0, 3.0), rotation=(0.0, 1.0, 0.0, 0.5))
    assert tuple(placed.translation) == (1.0, 2.0, 3.0)
    assert tuple(placed.rotation) == pytest.approx((0.0, 1.0, 0.0, 0.5))
    [held] = placed.children
    assert held.appearance.material is material
    assert isinstance(held.geometry, PBRMesh)
    assert held.geometry.tangents is not None and len(held.geometry.tangents) == 4


def test_panels_cut_from_one_wall_keep_its_pattern_in_line():
    """Pieces round an opening start their texture where they sit on the wall."""
    left = surfaces.panel(2.0, 3.0, repeat=0.5, start=(0.0, 0.0))
    right = surfaces.panel(2.0, 3.0, repeat=0.5, start=(2.0, 0.0))
    assert left.texcoords[:, 0].max() == pytest.approx(right.texcoords[:, 0].min())
    assert right.texcoords[:, 0].min() == pytest.approx(4.0)


def test_a_cylinder_faces_out_and_is_textured_round_its_curve():
    column = surfaces.cylinder(0.25, 3.0, sides=16, repeat=0.5)
    corners, winding = _faces(column)
    centres = corners.mean(axis=1)
    outward = centres.copy()
    outward[:, 1] = 0.0
    assert (np.einsum('ij,ij->i', winding, outward) > 0).all()
    assert np.ptp(column.texcoords[:, 0]) == pytest.approx(2 * math.pi * 0.25 / 0.5)
    assert np.ptp(column.texcoords[:, 1]) == pytest.approx(3.0 / 0.5)
    _texture_runs_along_the_tangents(column)


def test_a_half_column_stands_against_a_wall_facing_out_from_it():
    half = surfaces.cylinder(0.2, 2.0, sides=8, arc=math.pi)
    assert half.positions[:, 2].min() == pytest.approx(0.0, abs=1e-6)
    assert (half.normals[:, 2] >= -1e-6).all()
    _texture_runs_along_the_tangents(half)


def test_a_sphere_faces_out_and_is_textured_round_its_equator():
    ball = surfaces.sphere(0.5, sides=16, repeat=0.25)
    assert np.allclose(np.linalg.norm(ball.positions, axis=1), 0.5, atol=1e-6)
    assert np.allclose(ball.normals, ball.positions / 0.5, atol=1e-6)
    corners, winding = _faces(ball)
    assert (np.einsum('ij,ij->i', winding, corners.mean(axis=1)) > 0).all()
    assert np.ptp(ball.texcoords[:, 0]) == pytest.approx(2 * math.pi * 0.5 / 0.25)
    # Round the middle, where the wrapping is not gathered towards a pole.
    triangles = ball.indices.reshape(-1, 3)
    middle = (np.abs(ball.positions[triangles, 1]) < 0.2).all(axis=1)
    _texture_runs_along_the_tangents(ball._replace(indices=triangles[middle].ravel()))


def test_fewer_sides_is_fewer_triangles():
    """What a level of detail is made of."""
    counts = [len(surfaces.sphere(1.0, sides=sides).indices)
              for sides in (32, 16, 8)]
    assert counts == sorted(counts, reverse=True)


def test_a_prism_is_its_outline_stood_up_and_capped():
    square = [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)]
    prism = surfaces.prism(square, 2.0, repeat=0.5)
    corners, winding = _faces(prism)
    centres = corners.mean(axis=1)
    assert (np.einsum('ij,ij->i', winding, centres) > 0).all()
    sides = prism.normals[:, 1] == 0
    assert np.ptp(prism.texcoords[sides, 0]) == pytest.approx(4.0 / 0.5)
    _texture_runs_along_the_tangents(prism)


def test_a_chamfered_block_has_its_upright_edges_cut():
    """A 5 mm chamfer: no corner of the footprint is left, each cut the same."""
    block = surfaces.block((0.6, 3.0, 0.6), chamfer=0.005)
    footprint = np.unique(np.round(block.positions[:, [0, 2]], 6), axis=0)
    assert not (np.isclose(np.abs(footprint), 0.3).all(axis=1)).any()
    cut = footprint[np.isclose(np.abs(footprint[:, 0]), 0.3)]
    assert np.abs(cut[:, 1]).max() == pytest.approx(0.295)
    corners, winding = _faces(block)
    assert (np.einsum('ij,ij->i', winding, corners.mean(axis=1)) > 0).all()
    _texture_runs_along_the_tangents(block)


def test_pieces_moved_and_merged_are_one_mesh():
    left = surfaces.moved(surfaces.panel(1.0, 1.0), (-1.0, 0.0, 0.0))
    right = surfaces.moved(surfaces.panel(1.0, 1.0), (1.0, 0.0, 0.0))
    both = surfaces.merge([left, right])
    assert len(both.positions) == 8 and len(both.indices) == 12
    assert both.positions[:4, 0].max() == pytest.approx(-0.5)
    assert both.indices[6:].min() == 4


def test_a_piece_placed_in_its_parent_carries_its_frame_with_it():
    """Turned a quarter about y and moved, a panel facing +z faces +x there."""
    panel = surfaces.panel(2.0, 1.0)
    placed = surfaces.placed(panel, (5.0, 1.0, 0.0), (0.0, 1.0, 0.0, math.pi / 2))
    assert np.allclose(placed.normals, (1.0, 0.0, 0.0), atol=1e-6)
    assert np.allclose(placed.tangents[:, :3], (0.0, 0.0, -1.0), atol=1e-6)
    assert np.allclose(placed.positions.mean(axis=0), (5.0, 1.0, 0.0), atol=1e-6)
    assert np.allclose(placed.texcoords, panel.texcoords)
    _texture_runs_along_the_tangents(placed)


def test_placing_agrees_with_a_transform_turning_it():
    """The same points a VRML97 Transform with that rotation puts them at."""
    from OpenGLContext.scenegraph import basenodes
    block = surfaces.block((1.0, 2.0, 3.0))
    rotation = (0.3, 0.8, -0.5, 1.1)
    transform = basenodes.Transform(translation=(1.0, -2.0, 0.5), rotation=rotation)
    matrix = np.asarray(transform.localMatrices().data[0], 'd')
    expected = (np.c_[block.positions, np.ones(len(block.positions))] @ matrix)[:, :3]
    placed = surfaces.placed(block, (1.0, -2.0, 0.5), rotation)
    assert np.allclose(placed.positions, expected, atol=1e-5)
