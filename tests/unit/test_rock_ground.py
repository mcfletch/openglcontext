"""Rocky ground meshed finely: the surface drawn is the surface walked, and tiles meet."""
import numpy as np
import pytest

from OpenGLContext.loaders.tiles3d.generated import GeneratedTileset
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.rockground import RockGround, RockGroundScatter, RockyGround
from OpenGLContext.scenegraph.terrain import RockRelief


class Slope:
    """A ground that rises 0.1 m for every metre east and has no edge."""

    def sample(self, x, z):
        return 0.1 * np.asarray(x, dtype=float) + 0.0 * np.asarray(z, dtype=float)

    extent = 1000.0


def rocky_east(x, z):
    """Rock from x = 40 eastward; ground to the west."""
    return (np.asarray(x) > 40.0).astype(float) * np.ones(np.broadcast(np.asarray(x),
                                                                      np.asarray(z)).shape)


@pytest.fixture
def relief():
    return RockRelief(where=rocky_east, height=0.6, seed=2)


@pytest.fixture
def scatter(relief):
    return RockGroundScatter(Slope(), relief, PhysicalMaterial(), cell=16.0, step=0.5)


def mesh(tile):
    return tile.group.children[0].children[0].geometry


def test_only_cells_with_rock_in_them_are_wanted(scatter):
    keys = scatter.keys_near(np.array([40.0, 0.0, 8.0]), 60.0)
    assert keys and all(i >= 2 for i, _ in keys)           # x >= 32 holds some of the rock
    assert scatter.keys_near(np.array([-200.0, 0.0, 0.0]), 50.0) == []


def test_a_cell_is_meshed_at_the_step_asked(scatter):
    tile, nbytes = scatter.generate((4, 0))
    geometry = mesh(tile)
    assert len(geometry.positions) == 33 * 33 and nbytes > 30_000
    assert len(geometry.indices) == 32 * 32 * 6


def test_the_surface_drawn_is_the_ground_and_the_rock_on_it(scatter, relief):
    tile, _ = scatter.generate((5, 1))
    p = mesh(tile).positions.astype(float)
    x0, _, z0 = scatter.origin((5, 1))
    wx, wz = p[:, 0] + x0, p[:, 2] + z0
    expected = Slope().sample(wx, wz) + relief.displacement(wx, wz, scatter.step)
    assert p[:, 1] == pytest.approx(expected, abs=1e-4)
    assert (p[:, 1] - Slope().sample(wx, wz)).min() >= 0.0


def test_neighbouring_cells_share_their_edge_exactly(scatter):
    left, right = mesh(scatter.generate((3, 2))[0]), mesh(scatter.generate((4, 2))[0])
    a = left.positions.astype(float).reshape(33, 33, 3)[:, -1]
    b = right.positions.astype(float).reshape(33, 33, 3)[:, 0]
    assert a[:, 1] == pytest.approx(b[:, 1], abs=1e-6)
    assert a[:, 2] == pytest.approx(b[:, 2])
    na = left.normals.reshape(33, 33, 3)[:, -1]
    nb = right.normals.reshape(33, 33, 3)[:, 0]
    assert na == pytest.approx(nb, abs=1e-5)


def test_the_mesh_is_a_valid_upward_facing_surface(scatter):
    geometry = mesh(scatter.generate((4, 3))[0])
    assert np.allclose(np.linalg.norm(geometry.normals, axis=1), 1.0, atol=1e-4)
    triangles = geometry.positions[geometry.indices.reshape(-1, 3)].astype(float)
    face = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    assert (face[:, 1] > 0).all()
    assert geometry.indices.max() < len(geometry.positions)
    assert set(np.unique(geometry.tangents[:, 3])) == {1.0}


def test_vertices_are_built_around_the_corner_so_they_stay_small(scatter):
    far = RockGroundScatter(Slope(), RockRelief(where=lambda x, z: np.ones(np.broadcast(x, z).shape)),
                            PhysicalMaterial(), cell=16.0, step=0.5)
    p = mesh(far.generate((100000, -100000))[0]).positions
    assert np.abs(p[:, 0]).max() <= 16.0 and np.abs(p[:, 2]).max() <= 16.0


def test_the_bounds_hold_the_cell(scatter):
    centre, radius = scatter.bounds((5, 0)).bounding_sphere()
    x0, _, z0 = scatter.origin((5, 0))
    p = mesh(scatter.generate((5, 0))[0]).positions.astype(float) + np.array([x0, 0.0, z0])
    assert np.linalg.norm(p - np.array(centre), axis=1).max() <= radius + 1e-6


def test_the_tile_is_drawn_with_the_material_and_casts_no_shadow(scatter):
    shape = scatter.generate((4, 0))[0].group.children[0].children[0]
    assert shape.appearance.material is scatter.material and shape.castShadow is False


def test_the_scatter_asks_for_sensible_numbers(relief):
    with pytest.raises(ValueError):
        RockGroundScatter(Slope(), relief, None, cell=0.5, step=0.5)


# -- the ground to stand on ------------------------------------------------------------

def test_a_rocky_ground_stands_where_the_rock_is_drawn(relief):
    ground = RockyGround(Slope(), relief, spacing=0.5)
    x, z = np.array([60.0, 70.0, 10.0]), np.array([3.0, 4.0, 5.0])
    assert ground.sample(x, z) == pytest.approx(
        Slope().sample(x, z) + relief.displacement(x, z, 0.5))
    assert ground.height_at(60.0, 3.0) == pytest.approx(float(ground.sample(60.0, 3.0)))
    assert ground.sample(np.array([10.0]), np.array([5.0]))[0] == pytest.approx(1.0)  # no rock west


def test_a_rocky_ground_answers_for_the_ground_beneath(relief):
    ground = RockyGround(Slope(), relief)
    assert ground.extent == 1000.0
    assert not hasattr(ground, 'no_such_thing')


def test_the_slope_of_rocky_ground_is_the_slope_of_what_is_drawn(relief):
    ground = RockyGround(Slope(), relief)
    assert float(ground.slope(np.array([5.0]), np.array([0.0]), eps=2.0)[0]) == pytest.approx(0.1)
    x = np.linspace(60.0, 120.0, 400)
    assert ground.slope(x, np.full_like(x, 3.0), eps=0.5).max() > 0.2     # faces and steps


def test_the_tileset_makes_tiles_for_the_rocky_cells_only(scatter):
    tileset = GeneratedTileset(scatter, reach=80.0)
    changes = tileset.ensure(np.array([60.0, 0.0, 0.0]))
    assert changes.created
    assert all(tile.content_key[0] >= 2 for tile in changes.created)
    assert changes.created[0].world_transform[:3, 3] == pytest.approx(
        scatter.origin(changes.created[0].content_key))


def test_a_node_streams_the_scatter_and_hands_out_the_ground(relief):
    node = RockGround(Slope(), relief, PhysicalMaterial(), reach=60.0, cell=16.0, step=0.5)
    try:
        assert node.tileset.generator is node.scatter
        ground = node.ground
        assert ground.spacing == 0.5 and ground.rock is relief
    finally:
        node.shutdown()


def test_a_walker_bound_to_the_rocky_ground_builds_its_physics_world_from_the_fields_own_figures():
    """The walker reads ``extent``, ``grid`` and ``relief`` (metres of height) off its ground;
    a rocky ground must answer them with the field's, not with its own rock."""
    from OpenGLContext.move.terrainwalk import TerrainWalkMixin
    from OpenGLContext.scenegraph.terrain import HeightField

    class Walker(TerrainWalkMixin):
        platform = None

    field = HeightField(np.linspace(0.0, 1.0, 81).reshape(9, 9), 400.0, 50.0)
    rock = RockRelief(where=rocky_east, height=0.6)
    walker = Walker()
    walker.init_walk(RockyGround(field, rock))
    world, (low, high) = walker.buildPhysicsWorld()
    assert float(high[0]) == 200.0 and float(high[1]) == pytest.approx(50.0)
    assert RockyGround(field, rock).relief == 50.0
    assert RockyGround(field, rock).rock is rock


# -- keeping the coarse ground out of the rock's way -----------------------------------------

def field_of(extent=256.0, res=65):
    from OpenGLContext.scenegraph.terrain import HeightField
    grid = np.linspace(0.0, 1.0, res * res).reshape(res, res)
    return HeightField(grid, extent, 40.0, base=3.0)


def east_half(x, z):
    return (np.asarray(x) > 0.0).astype(float) * np.ones(np.broadcast(np.asarray(x),
                                                                      np.asarray(z)).shape)


def test_the_coarse_ground_is_lowered_where_there_is_rock_and_left_alone_elsewhere():
    from OpenGLContext.scenegraph.rockground import beneath
    field = field_of()
    rock = RockRelief(where=east_half, height=0.6)
    lowered = beneath(field, rock, depth=0.3)
    axis = np.linspace(-128.0, 128.0, 65)
    gx, gz = np.meshgrid(axis, axis)
    drop = field.sample(gx, gz) - lowered.sample(gx, gz)
    assert drop[gx < -1.0].max() == pytest.approx(0.0, abs=1e-9)
    assert drop[gx > 1.0].min() == pytest.approx(0.3, abs=1e-6)
    assert lowered.extent == field.extent and lowered.relief == field.relief and lowered.base == field.base


def test_the_rock_is_above_the_lowered_ground_everywhere_by_the_depth_times_the_rock_there():
    from OpenGLContext.scenegraph.rockground import beneath
    field = field_of()
    rock = RockRelief(where=lambda x, z: np.clip(np.asarray(x) / 100.0 + 0.5, 0.0, 1.0)
                      * np.ones(np.broadcast(np.asarray(x), np.asarray(z)).shape), height=0.6)
    lowered = beneath(field, rock, depth=0.3)
    ground = RockyGround(field, rock, spacing=0.4)
    rng = np.random.default_rng(1)
    x, z = rng.uniform(-120, 120, 4000), rng.uniform(-120, 120, 4000)
    gap = ground.sample(x, z) - lowered.sample(x, z)
    assert gap.min() >= -1e-9
    interp = field.sample(x, z) - lowered.sample(x, z)
    assert (gap >= interp - 1e-9).all()


def test_the_fine_mesh_leaves_out_the_ground_that_has_no_rock_and_keeps_the_rest():
    scatter = RockGroundScatter(Slope(), RockRelief(where=east_half, height=0.6), PhysicalMaterial(),
                                cell=16.0, step=0.5)
    scatter.relief = RockRelief(where=lambda x, z: np.clip(np.asarray(x) / 8.0, 0.0, 1.0)
                                * np.ones(np.broadcast(np.asarray(x), np.asarray(z)).shape))
    geometry = mesh(scatter.generate((0, 0))[0])
    x = geometry.positions[geometry.indices.reshape(-1, 3)][:, :, 0]
    assert len(geometry.indices) < 32 * 32 * 6
    assert x.max(axis=1).min() > 0.0             # no kept triangle lies wholly where there is no rock


def test_a_cell_with_a_corner_of_rock_is_wanted_however_small_the_corner(scatter):
    sparse = RockGroundScatter(Slope(), RockRelief(
        where=lambda x, z: ((np.asarray(x) > 46.2) & (np.asarray(z) > 46.2)).astype(float)
        * np.ones(np.broadcast(np.asarray(x), np.asarray(z)).shape)), PhysicalMaterial(),
        cell=32.0, step=0.5)
    assert sparse.has_rock((1, 1)) and not sparse.has_rock((0, 0))


def test_the_edge_of_the_fine_ground_fades_in_and_is_opaque_where_the_rock_is_whole(scatter):
    geometry_node = scatter.generate((4, 0))[0].group.children[0].children[0]
    colours = geometry_node.geometry.colors
    assert colours.shape[1] == 4 and colours[:, 3].min() >= 0.0 and colours[:, 3].max() == 1.0
    assert geometry_node.appearance.alphaMode == 'BLEND'
