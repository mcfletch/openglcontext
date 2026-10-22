"""Tile content made in child processes."""
import os
import signal
import threading
import time

import numpy as np
import pytest

from OpenGLContext.loaders.tiles3d.generated import GeneratedTileset
from OpenGLContext.loaders.tiles3d.tileprocess import (
    INTERRUPTED, TileProcesses, TileProcessError, TileProcessInterrupted,
)

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


@pytest.mark.skipif(os.name == 'nt', reason='SIGINT is delivered to a child through a console event there')
class TestAnInterruptReachingEveryProcess:
    """A terminal's Ctrl-C goes to the parent and to each child at once."""

    def test_a_child_idle_when_interrupted_ends_without_a_traceback(self, processes, capfd):
        pool = processes(count=1)
        pool.make(1)
        child = pool._children[0].process
        child.send_signal(signal.SIGINT)
        assert child.wait(timeout=10) == INTERRUPTED
        assert capfd.readouterr().err == ''

    def test_a_child_interrupted_while_making_ends_without_a_traceback(self, processes, capfd):
        pool = processes(count=1)
        with pytest.raises(TileProcessInterrupted, match='interrupted'):
            pool.make('interrupt')
        assert capfd.readouterr().err == ''

    def test_an_interrupted_child_is_replaced_for_the_next_request(self, processes):
        pool = processes(count=1)
        with pytest.raises(TileProcessInterrupted):
            pool.make('interrupt')
        assert pool.make(2)[1][0, 0] == 2.0

    def test_an_interrupt_is_a_tile_process_error_to_a_caller_that_does_not_ask(self):
        assert issubclass(TileProcessInterrupted, TileProcessError)

    def test_a_dead_child_is_not_taken_for_an_interrupted_one(self, processes):
        with pytest.raises(TileProcessError, match='stopped') as raised:
            processes(count=1).make('die')
        assert not isinstance(raised.value, TileProcessInterrupted)


def test_a_parent_that_closes_the_connection_mid_request_leaves_the_child_quiet(processes, capfd):
    pool = processes(args=(0.5,), count=1)
    pool.make(0)
    child = pool._children[0]
    asking = threading.Thread(target=lambda: pytest.raises(TileProcessError, pool.make, 1))
    asking.start()
    time.sleep(0.2)
    child.sock.close()
    asking.join()
    assert child.process.wait(timeout=10) == 0
    assert capfd.readouterr().err == ''


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
