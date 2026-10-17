"""Rocks scattered over any ground: the same each time, seated, and only where the mask says."""
import numpy as np
import pytest

from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.loaders.tiles3d.generated import GeneratedTileset
from OpenGLContext.scenegraph.rockfield import RockField, RockScatter


class Slope:
    """A ground that rises 0.1 m for every metre east and has no edge."""

    def sample(self, x, z):
        return 0.1 * np.asarray(x, dtype=float) + 0.0 * np.asarray(z, dtype=float)


def scatter(**named):
    named.setdefault('density', 0.02)
    return RockScatter(Slope(), PhysicalMaterial(), **named)


def positions(tile):
    return tile.group.children[0].children[0].geometry.positions.astype(float)


def test_the_cells_wanted_are_those_in_reach_nearest_first():
    keys = scatter(cell=50.0).keys_near(np.array([10.0, 0.0, 10.0]), 60.0)
    assert keys[0] == (0, 0) and (1, 0) in keys and (-2, 0) not in keys
    assert (5, 5) not in keys


def test_a_cell_is_made_the_same_each_time_and_differs_from_another():
    s = scatter()
    a, b, other = s.generate((3, 4))[0], s.generate((3, 4))[0], s.generate((3, 5))[0]
    assert np.array_equal(positions(a), positions(b))
    assert not np.array_equal(positions(a), positions(other))


def test_a_seed_makes_another_scatter():
    a = scatter(seed=1).generate((0, 0))[0]
    b = scatter(seed=2).generate((0, 0))[0]
    assert not np.array_equal(positions(a), positions(b))


def test_rocks_lie_in_their_cell_seated_on_the_ground_and_sunk_a_little():
    s = scatter(cell=64.0)
    tile, nbytes = s.generate((2, -1))
    p = positions(tile)
    x0, _, z0 = s.origin((2, -1))
    world = p + np.array([x0, 0.0, z0])
    assert nbytes > 10_000
    assert world[:, 0].min() > x0 - 3.0 and world[:, 0].max() < x0 + 64.0 + 3.0
    assert world[:, 2].min() > z0 - 3.0 and world[:, 2].max() < z0 + 64.0 + 3.0
    ground = Slope().sample(world[:, 0], world[:, 2])
    assert (world[:, 1] - ground).min() < 0.0          # sunk
    assert (world[:, 1] - ground).max() < 2.2 * 0.9 * 2.0 and (world[:, 1] - ground).max() > 0.1


def test_a_cell_is_built_around_its_corner_so_its_vertices_stay_small():
    s = scatter(cell=64.0)
    p = positions(s.generate((100000, 100000))[0])
    assert np.abs(p[:, 0]).max() < 70.0 and np.abs(p[:, 2]).max() < 70.0


def test_rocks_grow_only_where_the_mask_allows():
    s = scatter(mask=lambda x, z: (np.asarray(x) > 32.0).astype(float), cell=64.0)
    p = positions(s.generate((0, 0))[0]) + np.array([0.0, 0.0, 0.0])
    assert len(p) > 0 and p[:, 0].min() > 32.0 - 3.0
    nothing = scatter(mask=lambda x, z: np.zeros_like(np.asarray(x, dtype=float)))
    tile, nbytes = nothing.generate((0, 0))
    assert nbytes == 0 and tile.group.children == []


def test_the_bounds_hold_every_rock_of_the_cell():
    s = scatter()
    box = s.bounds((1, 1))
    centre, radius = box.bounding_sphere()
    x0, _, z0 = s.origin((1, 1))
    world = positions(s.generate((1, 1))[0]) + np.array([x0, 0.0, z0])
    assert np.linalg.norm(world - np.array(centre), axis=1).max() <= radius + 1e-6


def test_the_scatter_asks_for_sensible_numbers():
    with pytest.raises(ValueError):
        RockScatter(Slope(), None, sizes=(0.5, 0.1))
    with pytest.raises(ValueError):
        RockScatter(Slope(), None, cell=0.0)


def test_rocks_cast_shadows_and_wear_the_material_given():
    material = PhysicalMaterial()
    s = RockScatter(Slope(), material, density=0.02)
    shape = s.generate((0, 0))[0].group.children[0].children[0]
    assert shape.castShadow is True and shape.appearance.material is material


def test_the_scatter_drives_a_generated_tileset():
    s = scatter(cell=50.0)
    tileset = GeneratedTileset(s, reach=80.0)
    changes = tileset.ensure(np.array([0.0, 0.0, 0.0]))
    assert len(changes.created) == len(s.keys_near(np.array([0.0, 0.0, 0.0]), 80.0)) > 4
    tile = changes.created[0]
    assert tile.world_transform[:3, 3] == pytest.approx(s.origin(tile.content_key))


def test_a_field_is_a_node_that_streams_the_scatter():
    field = RockField(Slope(), PhysicalMaterial(), reach=100.0, density=0.02)
    try:
        assert field.scatter.cell == 64.0
        assert field.tileset.generator is field.scatter
    finally:
        field.shutdown()


# -- what stops a walker ----------------------------------------------------------

def test_colliders_are_the_rocks_that_are_big_enough_to_be_in_the_way():
    s = scatter(density=0.05, sizes=(0.1, 1.2))
    positions, radii = s.colliders((0, 0))
    assert len(radii) > 5 and positions.shape == (len(radii), 3)
    from OpenGLContext.scenegraph.rockfield import COLLIDE_FROM, FOOTPRINT
    assert radii.min() >= COLLIDE_FROM * FOOTPRINT - 1e-6


def test_colliders_sit_where_the_rocks_are_drawn():
    s = scatter(density=0.05, sizes=(0.1, 1.2))
    tile, _ = s.generate((1, 1))
    drawn = positions(tile) + np.array(s.origin((1, 1)))
    cx, cr = s.colliders((1, 1))
    ground = Slope().sample(cx[:, 0], cx[:, 2])
    assert cx[:, 1] == pytest.approx(ground, abs=1e-3)
    for centre, radius in zip(cx, cr):
        around = drawn[np.hypot(drawn[:, 0] - centre[0], drawn[:, 2] - centre[2]) < radius * 1.3]
        assert len(around) > 10, 'a collider has a rock under it'


def test_colliders_are_the_same_each_time_and_need_no_meshes():
    s = scatter(density=0.05)
    a, b = s.colliders((2, 3)), s.colliders((2, 3))
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_the_field_answers_the_colliders_near_a_point_across_cells():
    field = RockField(Slope(), PhysicalMaterial(), reach=100.0, density=0.05, cell=40.0,
                      sizes=(0.1, 1.2))
    try:
        positions_, radii = field.colliders_near(40.0, 40.0, reach=10.0)
        near = [field.scatter.colliders(key) for key in ((0, 0), (1, 0), (0, 1), (1, 1))]
        assert len(radii) == sum(len(r) for _, r in near) > 0
        again = field.colliders_near(40.0, 40.0, reach=10.0)
        assert np.array_equal(again[1], radii)
        assert positions_.shape == (len(radii), 3)
    finally:
        field.shutdown()


def test_the_field_keeps_only_so_many_cells(monkeypatch):
    from OpenGLContext.scenegraph import rockfield
    monkeypatch.setattr(rockfield, 'CELLS_KEPT', 4)
    field = RockField(Slope(), PhysicalMaterial(), reach=100.0, density=0.05, cell=40.0)
    try:
        for i in range(10):
            field.colliders_near(i * 40.0 + 1.0, 1.0, reach=1.0)
        assert len(field._held) == 4
    finally:
        field.shutdown()
