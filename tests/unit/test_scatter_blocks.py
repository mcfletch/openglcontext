"""A world-anchored scatter kept by the block, so each place is scattered once.

Every instance of :func:`world_grid_scatter` is decided by its own grid cell,
so the scatter of a piece of ground is the same whoever asks and from where.
:class:`ScatterBlocks` keeps it: a disc around the camera is made of the blocks
it reaches, each scattered the first time it is reached, and moving on costs
only the ground newly reached.
"""
import threading

import numpy as np

from OpenGLContext.scenegraph.terrain import HeightField
from OpenGLContext.scenegraph.vegetation.grid import ScatterBlocks, world_grid_scatter

DENSITY = 0.5


def _field():
    return HeightField(np.linspace(0, 1, 33 * 33).reshape(33, 33), 4096.0, 10.0)


def _mask(x, _z):
    return 0.5 + 0.5 * np.sin(np.asarray(x) * 0.05)


def _blocks(**named):
    field = _field()
    named.setdefault('mask', _mask)
    return ScatterBlocks(DENSITY, field, salt=3, jitter=1.7, **named), field


def _rows(points, *rest):
    return sorted(zip(*(np.round(points, 4).T), *(np.round(a, 5) for a in rest)))


class TestTheSameScatter:
    def test_a_disc_is_the_scatter_of_that_disc(self):
        blocks, field = _blocks()
        found = blocks.disc(120.0, -40.0, 90.0)
        expected = world_grid_scatter(120.0, -40.0, 90.0, DENSITY, field, salt=3,
                                      jitter=1.7, mask=_mask)
        assert len(found[0]) > 100
        assert _rows(*found) == _rows(*expected)

    def test_scale_and_spread_are_the_scatters(self):
        blocks, field = _blocks(scale_mul=0.4, scale_range=(0.7, 1.3))
        found = blocks.disc(0.0, 0.0, 60.0)
        expected = world_grid_scatter(0.0, 0.0, 60.0, DENSITY, field, salt=3,
                                      jitter=1.7, mask=_mask, scale_mul=0.4,
                                      scale_range=(0.7, 1.3))
        assert _rows(*found) == _rows(*expected)

    def test_what_is_added_to_each_instance_comes_with_it(self):
        def lit(points, yaws, scales):
            return points, yaws, scales, points[:, 0].astype('f4')
        blocks, _field_ = _blocks(finish=lit)
        points, _yaws, _scales, extra = blocks.disc(0.0, 0.0, 60.0)
        assert np.array_equal(extra, points[:, 0])


class TestEachPlaceOnce:
    def test_asking_again_scatters_nothing(self):
        blocks, _field_ = _blocks()
        blocks.disc(0.0, 0.0, 90.0)
        built = blocks.built
        blocks.disc(0.0, 0.0, 90.0)
        blocks.disc(3.0, 0.0, 90.0)
        assert blocks.built == built

    def test_moving_on_scatters_only_the_new_ground(self):
        blocks, _field_ = _blocks()
        blocks.disc(0.0, 0.0, 90.0)
        first = blocks.built
        blocks.disc(blocks.span * 1.5, 0.0, 90.0)
        assert 0 < blocks.built - first < first * 0.6

    def test_ground_left_far_behind_is_let_go(self):
        blocks, _field_ = _blocks()
        for step in range(40):
            blocks.disc(step * 60.0, 0.0, 90.0)
        span = blocks.span
        across = 2 * (blocks.keep * 90.0 + span) / span + 2
        assert len(blocks) <= across * across
        assert len(blocks) < blocks.built / 2

    def test_forgetting_scatters_it_again(self):
        blocks, _field_ = _blocks()
        blocks.disc(0.0, 0.0, 90.0)
        built = blocks.built
        blocks.clear()
        blocks.disc(0.0, 0.0, 90.0)
        assert blocks.built == 2 * built

    def test_an_empty_disc_is_empty_arrays(self):
        blocks, _field_ = _blocks(mask=lambda x, _z: np.zeros(np.shape(x)))
        points, yaws, scales = blocks.disc(0.0, 0.0, 50.0)
        assert points.shape == (0, 3) and len(yaws) == len(scales) == 0


class TestNoDensityIsNoPlants:
    def test_a_grid_of_no_density_scatters_nothing(self):
        points, yaws, scales = world_grid_scatter(0.0, 0.0, 50.0, 0.0, _field())
        assert points.shape == (0, 3) and len(yaws) == len(scales) == 0

    def test_blocks_of_no_density_hold_nothing(self):
        blocks = ScatterBlocks(0.0, _field())
        points, yaws, scales = blocks.disc(0.0, 0.0, 50.0)
        assert points.shape == (0, 3) and len(yaws) == len(scales) == 0


class TestBlocksMadeOnOtherThreads:
    """A thread making blocks ahead of the camera shares the blocks with the thread making its
    discs: one waits for another only for a block both want."""

    @staticmethod
    def _held_mask(entered, gate):
        """A mask that stops where x is far out until ``gate`` opens."""
        def mask(x, z):
            if float(np.max(np.asarray(x))) > 5000.0:
                entered.set()
                assert gate.wait(10.0)
            return _mask(x, z)
        return mask

    def test_a_disc_of_made_blocks_is_not_held_up_by_another_block_being_made(self):
        entered, gate = threading.Event(), threading.Event()
        blocks, _field_ = _blocks(mask=self._held_mask(entered, gate))
        blocks.disc(0.0, 0.0, 90.0)
        ahead = threading.Thread(target=blocks.warm, args=(8000.0, 0.0, 10.0))
        ahead.start()
        try:
            assert entered.wait(5.0)
            reader = threading.Thread(target=blocks.disc, args=(0.0, 0.0, 90.0))
            reader.start()
            reader.join(5.0)
            assert not reader.is_alive(), 'a disc of made blocks waits for an unrelated block'
        finally:
            gate.set()
            ahead.join(10.0)

    def test_two_threads_that_want_a_block_make_it_once(self):
        blocks, _field_ = _blocks()
        results = []
        start = threading.Barrier(4)

        def ask():
            start.wait()
            results.append(blocks.disc(0.0, 0.0, 90.0))

        threads = [threading.Thread(target=ask) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30.0)
        assert len(results) == 4
        assert blocks.built == len(blocks)
        assert all(_rows(*found) == _rows(*results[0]) for found in results)

    def test_a_block_being_made_when_the_blocks_are_cleared_is_not_kept(self):
        entered, gate = threading.Event(), threading.Event()
        blocks, _field_ = _blocks(mask=self._held_mask(entered, gate))
        middle = (round(8000.0 / blocks.span) + 0.5) * blocks.span
        ahead = threading.Thread(target=blocks.warm, args=(middle, blocks.span / 2, 1.0))
        ahead.start()
        try:
            assert entered.wait(5.0)
            blocks.clear()
        finally:
            gate.set()
            ahead.join(10.0)
        assert len(blocks) == 0
