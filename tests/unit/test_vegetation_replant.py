"""A forest's trees can be replaced without making its models and textures again."""
import numpy as np
import pytest

from OpenGLContext.scenegraph.vegetation.field import TreeSpecies, VegetationField


def species(count=3):
    return [TreeSpecies(name='kind%d' % i, mesh='k%d.npz' % i, solidTexture='b%d.png' % i,
                        foliageTexture='f%d.png' % i, impostor='i%d.png' % i)
            for i in range(count)]


def table(n, seed, kinds=(0, 1), z0=0.0):
    rng = np.random.default_rng(seed)
    positions = np.stack([rng.uniform(-30, 30, n), np.zeros(n), -(z0 + rng.uniform(0, 400, n))], 1)
    return (positions, rng.uniform(0, 6, n), rng.uniform(8, 16, n),
            rng.choice(kinds, n))


@pytest.fixture
def field():
    positions, yaws, heights, kinds = table(300, 1)
    return VegetationField(positions, yaws, heights, species(), species_id=kinds)


def test_replanting_changes_the_trees_and_keeps_the_nodes_that_draw_them(field):
    near, cards = field.near, list(field.impostors)
    positions, yaws, heights, kinds = table(500, 2, z0=2000.0)
    field.replant(positions, yaws, heights, kinds)
    assert field.tree_count == 500
    assert field.near is near
    assert field.impostors[:len(cards)] == cards
    assert np.array_equal(near.all_pos, positions.astype('f'))


def test_what_is_drawn_is_chosen_from_the_new_trees(field):
    field.update((0.0, 2.0, -200.0), facing=(0, 0, -1))
    positions, yaws, heights, kinds = table(500, 2, z0=2000.0)
    field.replant(positions, yaws, heights, kinds)
    field.update((0.0, 2.0, -2200.0), facing=(0, 0, -1))
    staged = field.near.staged
    rows = np.concatenate([rows for rows in staged.values() if len(rows)])
    assert len(rows) > 0
    assert (rows[:, 2] < -1900.0).all()


def test_a_kind_that_had_no_trees_before_gets_its_cards_when_it_has_some(field):
    assert len(field.impostors) == 2
    positions, yaws, heights, _ = table(200, 3)
    field.replant(positions, yaws, heights, np.full(200, 2))
    assert len(field.impostors) == 3
    field.update((0.0, 2.0, -100.0))
    assert len(field.impostors[-1].pos) > 0


def test_a_kind_with_no_trees_after_a_replant_draws_no_cards(field):
    positions, yaws, heights, _ = table(200, 3)
    field.update((0.0, 2.0, -100.0))
    field.replant(positions, yaws, heights, np.full(200, 1))
    field.update((0.0, 2.0, -100.0))
    first = field.impostors[0]
    assert len(first.pos) == 0


def test_a_replant_that_does_not_fit_is_refused(field):
    positions, yaws, heights, kinds = table(50, 4)
    with pytest.raises(ValueError, match='yaws'):
        field.replant(positions, yaws[:10], heights, kinds)
    assert field.tree_count == 300


def test_the_light_each_tree_gets_is_asked_for_again_when_the_trees_change(field):
    field.lit_by(lambda x, z: np.full(len(x), 0.5))
    assert field.shades is not None
    positions, yaws, heights, kinds = table(100, 5)
    field.replant(positions, yaws, heights, kinds, shade=lambda x, z: np.full(len(x), 0.25))
    assert np.allclose(field.shades, 0.25) and len(field.shades) == 100
    field.replant(positions, yaws, heights, kinds)
    assert field.shades is None


def test_a_species_that_is_not_there_or_a_table_of_the_wrong_length_is_refused(field):
    positions, yaws, heights, kinds = table(50, 6)
    with pytest.raises(ValueError, match='species'):
        field.replant(positions, yaws, heights, np.full(50, 3))
    with pytest.raises(ValueError, match='species'):
        field.replant(positions, yaws, heights, kinds[:10])
    assert field.tree_count == 300


def test_a_new_forest_is_refused_for_the_same_reasons():
    positions, yaws, heights, _ = table(50, 6)
    with pytest.raises(ValueError, match='species'):
        VegetationField(positions, yaws, heights, species(), species_id=np.full(50, 7))
    with pytest.raises(ValueError, match='yaws'):
        VegetationField(positions, yaws[:3], heights, species())


def none():
    return np.zeros((0, 3)), np.zeros(0), np.zeros(0), np.zeros(0, int)


def test_a_forest_may_have_no_trees_and_draws_nothing():
    forest = VegetationField(*none()[:3], species(), species_id=none()[3])
    assert forest.tree_count == 0
    forest.update((0.0, 2.0, -200.0), facing=(0, 0, -1))


def test_a_forest_replanted_with_no_trees_draws_nothing_and_can_be_planted_again(field):
    field.update((0.0, 2.0, -200.0), facing=(0, 0, -1))
    field.replant(*none())
    assert field.tree_count == 0
    field.update((0.0, 2.0, -200.0), facing=(0, 0, -1))
    positions, yaws, heights, kinds = table(200, 3)
    field.replant(positions, yaws, heights, kinds)
    field.update((0.0, 2.0, -200.0), facing=(0, 0, -1))
    assert field.tree_count == 200


def test_the_shapes_that_draw_vegetation_cast_no_shadow(field):
    """A forest's bound is as wide as the forest; as a caster it would stretch every cascade of
    the sun's shadows over all of it."""
    assert field.children and all(shape.castShadow is False for shape in field.children)
