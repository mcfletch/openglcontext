"""Tile content made in child processes."""
import os
import threading
import time

import numpy as np
import pytest

from OpenGLContext.loaders.tiles3d.generated import GeneratedTileset
from OpenGLContext.loaders.tiles3d.tileprocess import TileProcesses, TileProcessError

MAKERS = 'tests.unit.tileprocess_makers'


@pytest.fixture
def processes():
    made = []

    def start(factory='Maker', args=(), count=2):
        made.append(TileProcesses('%s:%s' % (MAKERS, factory), args, count))
        return made[-1]

    yield start
    for each in made:
        each.close()


def test_a_tile_is_made_in_another_process_and_its_arrays_arrive_whole(processes):
    pid, array = processes().make(7)
    assert pid != os.getpid()
    assert array.shape == (200, 300) and array.dtype == np.float32 and (array == 7.0).all()


def test_tiles_are_made_at_the_same_time_by_as_many_processes_as_there_are(processes):
    pool = processes(args=(0.8,), count=2)
    pool.make(0)
    pool.make(1)
    answers = []
    started = time.perf_counter()
    threads = [threading.Thread(target=lambda k=k: answers.append(pool.make(k))) for k in (2, 3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert time.perf_counter() - started < 1.4
    assert len({pid for pid, _ in answers}) == 2


def test_a_maker_that_raises_reports_its_traceback_and_the_process_carries_on(processes):
    pool = processes(count=1)
    with pytest.raises(TileProcessError, match='no tile boom'):
        pool.make('boom')
    assert pool.make(3)[1][0, 0] == 3.0


def test_a_process_that_dies_is_reported_and_replaced(processes):
    pool = processes(count=1)
    first = pool.make(1)[0]
    with pytest.raises(TileProcessError, match='stopped'):
        pool.make('die')
    assert pool.make(2)[0] != first


def test_a_factory_that_raises_is_reported_with_its_traceback(processes):
    with pytest.raises(TileProcessError, match='cannot build the maker'):
        processes('broken_factory', count=1).make(1)


def test_closing_stops_the_processes_and_refuses_more_work(processes):
    pool = processes(count=2)
    pool.make(1)
    pool.make(2)
    children = [child.process for child in pool._children]
    pool.close()
    assert all(child.poll() is not None for child in children)
    with pytest.raises(TileProcessError, match='closed'):
        pool.make(3)


def test_a_count_below_one_is_refused():
    with pytest.raises(ValueError, match='count'):
        TileProcesses('%s:Maker' % MAKERS, (), 0)


class Generator:
    """Assembles a tile from a payload; builds nothing itself."""

    def keys_near(self, point, radius):
        return [1]

    def bounds(self, key):
        raise AssertionError('not asked')

    def generate(self, key):
        raise AssertionError('the processes make the tiles')

    def assemble(self, key, payload):
        return ('scene', key, payload[1].shape), payload[1].nbytes


def test_a_tileset_with_processes_assembles_what_a_child_made(processes):
    from OpenGLContext.loaders.tiles3d.tileset import RuntimeTile

    tileset = GeneratedTileset(Generator(), 100.0, processes=processes())
    tile = RuntimeTile.__new__(RuntimeTile)
    tile.content_key = 5
    scene, nbytes = tileset.loader(tile)
    assert scene == ('scene', 5, (200, 300)) and nbytes == 200 * 300 * 4
