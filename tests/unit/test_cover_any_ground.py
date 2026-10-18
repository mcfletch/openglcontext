"""Ground cover sits on any ground that answers a height, not only on a HeightField."""
import numpy as np

from OpenGLContext.scenegraph.vegetation.cover import CoverSpecies, GroundCover


class Rolling:
    """An endless land: a height at ``(x, z)`` and nothing else."""

    def sample(self, x, z):
        return 0.5 * np.sin(np.asarray(x) / 7.0) + 0.002 * np.asarray(z)


def cover():
    species = CoverSpecies(name='tuft', card='tuft.png', density=1.0, height=0.3)
    return GroundCover(Rolling(), [species])


def test_plants_are_seated_on_the_height_the_ground_answers():
    near = cover().compute_near(10.0, -300.0)
    (cards, _clumps), = near
    positions = cards[0]
    assert len(positions) > 100
    land = Rolling().sample(positions[:, 0], positions[:, 2])
    assert np.allclose(positions[:, 1], land, atol=1e-4)


def test_the_cover_follows_the_camera_over_ground_with_no_edge():
    node = cover()
    first = node.compute_near(0.0, 0.0)[0][0][0]
    far = node.compute_near(0.0, -50000.0)[0][0][0]
    assert len(first) > 100 and len(far) > 100
    assert far[:, 2].max() < -49000.0


class Flat:
    """A level ground a metre higher than :class:`Rolling` ever gets."""

    def sample(self, x, z):
        return np.full(np.shape(x), 5.0)


def seated(node):
    return node.rungs[0].cards.pos


def test_relocated_cover_keeps_its_nodes_and_grows_on_the_new_ground():
    node = cover()
    drawn = list(node.children)
    nodes = [rung.nodes for rung in node.rungs]
    node.update((0.0, 0.0, 0.0))
    node.relocate(Flat())
    assert list(node.children) == drawn
    assert [rung.nodes for rung in node.rungs] == nodes
    node.update((0.0, 0.0, 0.0))
    assert len(seated(node)) > 100
    assert np.allclose(seated(node)[:, 1], 5.0)


def test_relocating_cover_empties_what_the_old_ground_staged():
    node = cover()
    node.apply_near(node.compute_near(0.0, 0.0))
    assert len(seated(node)) > 0
    node.relocate(Flat())
    assert len(seated(node)) == 0
    assert all(rung.cache is None for rung in node.rungs)


def test_relocating_cover_takes_the_rules_of_the_new_ground():
    node = cover()
    node.mask = lambda x, z: np.zeros(np.shape(x))
    node.update((0.0, 0.0, 0.0))
    assert len(seated(node)) == 0
    node.relocate(Flat())
    node.update((0.0, 0.0, 0.0))
    assert node.mask is None and len(seated(node)) > 100
    node.relocate(Flat(), mask=lambda x, z: np.zeros(np.shape(x)))
    node.update((0.0, 0.0, 0.0))
    assert len(seated(node)) == 0


def test_a_background_scatter_begun_on_the_old_ground_does_not_reach_the_new():
    node = cover()
    node.background = True
    try:
        node.update((0.0, 0.0, 0.0))
        node.relocate(Flat())
        node.update((0.0, 0.0, 0.0))
        node.wait(10.0)
        node.update((0.0, 0.0, 0.0))
        assert len(seated(node)) > 100
        assert np.allclose(seated(node)[:, 1], 5.0)
    finally:
        node.shutdown()


def test_disposing_cover_frees_every_node_and_stops_the_worker():
    node = cover()
    node.background = True
    node.update((0.0, 0.0, 0.0))
    freed = []
    for rung in node.rungs:
        for drawn in rung.nodes:
            drawn.dispose = lambda drawn=drawn: freed.append(drawn)
    node.dispose()
    assert len(freed) == sum(len(rung.nodes) for rung in node.rungs) > 0
    assert node.wait(0.1)
    node.dispose()


def test_the_shapes_that_draw_cover_cast_no_shadow():
    node = cover()
    assert node.children and all(shape.castShadow is False for shape in node.children)
