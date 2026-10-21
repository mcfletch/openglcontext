"""A ground cover's scatter made in a child process.

The scatter is numpy over a hash of each cell, and a thread running it takes the
interpreter lock from the render thread; a child process does the same work with
no lock to share. The child holds a cover of its own, built from a factory, and
runs the very code the cover runs in line, so what it answers is what the cover
would have made.
"""
import os
import time

import numpy as np
import pytest

from OpenGLContext.scenegraph.vegetation.coverprocess import CoverProcess
from tests.unit.cover_process_makers import cover as local_cover

MAKERS = 'tests.unit.cover_process_makers'


@pytest.fixture
def child():
    made = []

    def start(factory='maker', args=(), start=True):
        made.append(CoverProcess('%s:%s' % (MAKERS, factory), args, start=start))
        return made[-1]

    yield start
    for each in made:
        each.close()


def _same(found, wanted):
    return len(found) == len(wanted) and all(
        (a is None and b is None) or np.array_equal(a, b) for a, b in zip(found, wanted, strict=True))


class TestWhatTheChildMakes:
    def test_a_disc_is_what_the_cover_makes_in_line(self, child) -> None:
        near = local_cover()
        rung = near.rungs[0]
        wanted = near._scatter(rung, 'cards', 40.0, -25.0, 90.0, 2.0, 1.0)  # noqa: SLF001 the scatter is the thing compared
        found = child().disc(0, 'cards', 40.0, -25.0, 90.0, 2.0, 1.0)
        assert len(found[0]) > 100
        assert _same(found, wanted)

    def test_each_rung_is_its_own_species(self, child) -> None:
        remote = child()
        first = remote.disc(0, 'cards', 0.0, 0.0, 60.0, 2.0, 1.0)
        second = remote.disc(1, 'cards', 0.0, 0.0, 60.0, 2.0, 1.0)
        assert not np.array_equal(first[0][:20], second[0][:20])

    def test_it_is_made_in_another_process(self, child) -> None:
        remote = child()
        remote.disc(0, 'cards', 0.0, 0.0, 60.0, 2.0, 1.0)
        assert remote.process_id() != os.getpid()
        assert remote.requests >= 1

    def test_ground_warmed_ahead_is_not_scattered_again_by_the_disc_that_reaches_it(
            self, child) -> None:
        remote = child()
        remote.warm(0, 'cards', 0.0, -80.0, 90.0, 2.0, 1.0)
        warmed = remote.scattered()
        remote.disc(0, 'cards', 0.0, -80.0, 90.0, 2.0, 1.0)
        assert remote.scattered() == warmed > 0

    def test_a_scatter_that_cannot_be_built_is_reported(self) -> None:
        remote = CoverProcess('%s:broken' % MAKERS)
        try:
            with pytest.raises(Exception, match='cannot build the scatter'):
                remote.disc(0, 'cards', 0.0, 0.0, 60.0, 2.0, 1.0)
        finally:
            remote.close()


class TestWhenTheCoverUsesIt:
    def _both(self, child):
        inline, remote = local_cover(), local_cover()
        process = child()
        remote.use_process(process)
        return inline, remote, process

    def test_the_cover_it_grows_is_the_cover_grown_in_line(self, child) -> None:
        inline, remote, process = self._both(child)
        process.wait_until_ready()
        for place in ((0.0, 0.0, 0.0), (35.0, 0.0, -20.0), (140.0, 0.0, -90.0)):
            inline.update(place)
            remote.update(place)
            assert np.array_equal(inline.rungs[0].cards.pos, remote.rungs[0].cards.pos)
            assert np.array_equal(inline.rungs[1].cards.pos, remote.rungs[1].cards.pos)
        assert process.requests > 0

    def test_it_is_not_asked_before_it_is_ready(self, child) -> None:
        remote = local_cover()
        process = child(start=False)
        remote.use_process(process)
        remote.update((0.0, 0.0, 0.0))
        assert process.requests == 0
        assert len(remote.rungs[0].cards.pos) > 0

    def test_ground_prepared_ahead_is_made_by_the_child(self, child) -> None:
        _, remote, process = self._both(child)
        process.wait_until_ready()
        remote.update((0.0, 0.0, 0.0))
        remote.prepare([(0.0, -60.0), (0.0, -120.0)])
        remote.wait(60.0)
        assert process.requests > 1

    def test_a_child_that_cannot_answer_is_replaced_by_scattering_in_line(self, child) -> None:
        inline, remote = local_cover(), local_cover()
        process = child('faulty')
        remote.use_process(process)
        process.wait_until_ready()
        for place in ((0.0, 0.0, 0.0), (60.0, 0.0, -40.0)):
            inline.update(place)
            remote.update(place)
        assert np.array_equal(inline.rungs[0].cards.pos, remote.rungs[0].cards.pos)
        assert remote._remote is None  # noqa: SLF001 the cover has stopped asking
        assert process.closed

    def test_a_request_that_fails_after_the_cover_has_a_new_process_does_not_stop_the_new_one(
            self, child) -> None:
        """A worker still waiting on the old process when the cover is given another."""
        remote = local_cover()
        old, new = child('faulty'), child()
        remote.use_process(old)
        old.wait_until_ready()
        new.wait_until_ready()
        stale = remote._remote  # noqa: SLF001 the process a request in flight was sent to
        remote.use_process(new)
        remote._stop_using_process(RuntimeError('the old one stopped'), stale)  # noqa: SLF001 what a worker does when its request fails
        assert remote._remote is new  # noqa: SLF001 the cover keeps asking the new process
        assert not new.closed
        assert stale.closed

    def test_a_child_that_has_been_closed_is_not_asked(self, child) -> None:
        inline, remote, process = self._both(child)
        process.wait_until_ready()
        process.close()
        remote.update((0.0, 0.0, 0.0))
        inline.update((0.0, 0.0, 0.0))
        assert np.array_equal(inline.rungs[0].cards.pos, remote.rungs[0].cards.pos)

    def test_shutting_the_cover_down_stops_the_child(self, child) -> None:
        _, remote, process = self._both(child)
        process.wait_until_ready()
        remote.shutdown()
        assert process.closed

    def test_the_frame_that_asks_does_not_wait_for_the_child(self, child) -> None:
        remote = local_cover(background=True)
        process = child()
        remote.use_process(process)
        started = time.perf_counter()
        remote.update((0.0, 0.0, 0.0))
        assert time.perf_counter() - started < 0.5
        remote.wait(60.0)
        remote.shutdown()
