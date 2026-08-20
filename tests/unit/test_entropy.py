"""The randomness a session starts from.

A game whose world, loot, spread or bot decisions come out of a random number
generator does not replay from its input alone: the same keys pressed against a
different sequence of numbers give a different game.  So a session has a
**seed**, the engine owns it, and every unseeded generator in the engine draws
from a stream derived from it -- which is what makes the seed worth recording
and worth putting back.
"""

import random

import numpy as np
import pytest

from OpenGLContext import entropy


@pytest.fixture(autouse=True)
def a_session_of_its_own():
    """Each test gets a fresh session, and the process's own generators back."""
    before = (random.getstate(), np.random.get_state())
    entropy.forget()
    yield
    entropy.forget()
    random.setstate(before[0])
    np.random.set_state(before[1])


class TestTheSessionSeed:
    def test_a_session_has_one_seed_however_often_it_is_asked(self):
        assert entropy.seed() == entropy.seed()

    def test_it_is_an_integer_a_person_could_write_down(self):
        assert isinstance(entropy.seed(), int)
        assert 0 <= entropy.seed() < 2 ** 64

    def test_two_sessions_do_not_get_the_same_one(self):
        first = entropy.seed()
        entropy.forget()
        assert entropy.seed() != first

    def test_the_environment_can_name_it(self, monkeypatch):
        monkeypatch.setenv(entropy.SEED_ENV, '4242')
        assert entropy.seed() == 4242

    def test_a_seed_that_is_not_a_number_is_a_warning_and_not_a_failure(
            self, monkeypatch):
        """A mistyped switch must not be why a game will not start."""
        monkeypatch.setenv(entropy.SEED_ENV, 'lots')
        assert isinstance(entropy.seed(), int)


class TestWhatAskingForASeedDoes:
    def test_naming_one_makes_the_ordinary_generators_reproducible(
            self, monkeypatch):
        """A game calling ``random.random()`` is the commonest case of all,
        and it has to be covered by naming a seed or the seed means little."""
        monkeypatch.setenv(entropy.SEED_ENV, '99')
        entropy.seed()
        first = [random.random(), float(np.random.random())]
        entropy.forget()
        entropy.seed()
        assert [random.random(), float(np.random.random())] == first

    def test_not_naming_one_leaves_the_process_s_generators_alone(self):
        """Recording a session must not change what happens in it."""
        before = random.getstate()
        entropy.seed()
        assert random.getstate() == before

    def test_reseeding_is_explicit_and_always_takes_effect(self):
        entropy.reseed(7)
        first = random.random()
        entropy.reseed(7)
        assert random.random() == first

    def test_reseeding_with_nothing_starts_somewhere_new(self):
        assert entropy.reseed() != entropy.reseed()


class TestDerivedStreams:
    def test_a_stream_is_reproducible_from_the_session_seed(self):
        entropy.reseed(11)
        first = entropy.generator('trees').random(4).tolist()
        entropy.reseed(11)
        assert entropy.generator('trees').random(4).tolist() == first

    def test_two_streams_do_not_repeat_each_other(self):
        entropy.reseed(11)
        trees = entropy.generator('trees').random(8).tolist()
        entropy.reseed(11)
        assert entropy.generator('grass').random(8).tolist() != trees

    def test_asking_twice_gets_the_stream_and_not_the_start_of_it(self):
        """A caller asking again wants what comes next, not the same numbers:
        a bot picking a destination every few seconds would otherwise pick the
        same one for ever."""
        entropy.reseed(11)
        first = entropy.generator('bots').random()
        assert entropy.generator('bots').random() != first

    def test_the_stdlib_flavour_works_the_same_way(self):
        entropy.reseed(11)
        first = [entropy.randomizer('audio').random() for _ in range(4)]
        entropy.reseed(11)
        assert [entropy.randomizer('audio').random()
                for _ in range(4)] == first

    def test_the_two_flavours_of_one_name_are_still_one_stream_each(self):
        entropy.reseed(11)
        assert entropy.generator('x') is entropy.generator('x')
        assert entropy.randomizer('x') is entropy.randomizer('x')


class TestCapturingWhatTheGeneratorsHold:
    """A game that seeded itself, or that has been drawing since before the
    recording began, is not described by a seed: it is described by where its
    generators have got to."""

    def test_the_ordinary_generator_carries_on_where_it_was(self):
        captured = entropy.capture()
        expected = [random.random() for _ in range(3)]
        entropy.restore(captured)
        assert [random.random() for _ in range(3)] == expected

    def test_so_does_numpy_s(self):
        captured = entropy.capture()
        expected = np.random.random(3).tolist()
        entropy.restore(captured)
        assert np.random.random(3).tolist() == expected

    def test_the_session_seed_comes_back_with_it(self):
        entropy.reseed(1234)
        captured = entropy.capture()
        entropy.forget()
        entropy.restore(captured)
        assert entropy.seed() == 1234

    def test_the_derived_streams_start_again_from_the_restored_seed(self):
        entropy.reseed(1234)
        captured = entropy.capture()
        expected = entropy.generator('trees').random(3).tolist()
        entropy.restore(captured)
        assert entropy.generator('trees').random(3).tolist() == expected

    def test_it_is_all_plain_data(self):
        import json
        assert json.loads(json.dumps(entropy.capture()))

    def test_a_record_from_somewhere_else_is_ignored_rather_than_fatal(self):
        """A journal from another Python, or a truncated one: a replay that
        cannot put the numbers back is a worse replay, not a crash."""
        entropy.restore({'random': ['nonsense'], 'numpy': 42})
        entropy.restore({})
        random.random()          # still usable


class TestWhenAGeneratorWillNotDescribeItself:
    """A recording is diagnostic equipment: a generator it cannot write down,
    or a seed it cannot read back, costs that half and never the session."""

    def test_a_state_that_will_not_unpack_costs_that_half_only(self, monkeypatch):
        monkeypatch.setattr(random, 'getstate', lambda: 'not a state')
        found = entropy.capture()
        assert 'random' not in found
        assert found['numpy']

    def test_the_same_goes_for_numpy(self, monkeypatch):
        monkeypatch.setattr(np.random, 'get_state', lambda: 'not a state')
        found = entropy.capture()
        assert 'numpy' not in found
        assert found['random']

    def test_a_recorded_seed_that_is_not_a_number_is_passed_over(self):
        entropy.reseed(11)
        entropy.restore({'seed': 'four thousand'})
        assert entropy.seed() == 11


class TestWhatTheEngineDrawsFrom:
    """The engine's own unseeded generators draw from the session, so they
    replay with it."""

    def test_particles_repeat_within_a_session_seed(self):
        from OpenGLContext.scenegraph.particles import ParticlePool

        entropy.reseed(5)
        first = ParticlePool(capacity=4)._random.random(4).tolist()
        entropy.reseed(5)
        assert ParticlePool(capacity=4)._random.random(4).tolist() == first

    def test_an_emitter_that_names_its_own_seed_still_wins(self):
        from OpenGLContext.scenegraph.particles import ParticlePool

        entropy.reseed(5)
        first = ParticlePool(capacity=4, seed=77)._random.random(4).tolist()
        entropy.reseed(6)
        assert ParticlePool(capacity=4, seed=77)._random.random(4).tolist() == first

    def test_a_navmesh_wander_repeats_within_a_session_seed(self):
        from OpenGLContext.nav.navmesh import NavMesh

        mesh = _square_mesh()
        entropy.reseed(5)
        first = [mesh.random_point() for _ in range(6)]
        entropy.reseed(5)
        assert [mesh.random_point() for _ in range(6)] == first
        assert isinstance(mesh, NavMesh)

    def test_a_navmesh_still_wanders_rather_than_standing_still(self):
        """One stream, advancing: a bot asking again must be able to get
        somewhere else."""
        mesh = _square_mesh()
        entropy.reseed(5)
        assert len({mesh.random_point() for _ in range(30)}) > 1


def _square_mesh():
    from OpenGLContext.nav.navmesh import NavMesh

    points = np.array([[0, 0, 0], [4, 0, 0], [4, 0, 4], [0, 0, 4],
                       [8, 0, 0], [8, 0, 4]], dtype='f')
    cells = np.array([[0, 1, 2], [0, 2, 3], [1, 4, 5], [1, 5, 2]], dtype='i')
    return NavMesh(points, cells, neighbours={}, portals={})


class TestWhenTheSeedTakesEffect:
    """A pinned seed has to be in force before the application builds
    anything: a world generated from different numbers is a different world,
    and a game builds its world in ``OnInit``."""

    def _probe(self):
        from OpenGLContext.context import Context
        from OpenGLContext.interactivecontext import InteractiveContext

        class Probe(InteractiveContext, Context):
            """A whole context short of the window: everything
            ``Context.__init__`` does, with the one step that needs GL --
            binding the window and calling ``OnInit`` -- standing in for the
            application."""

            def DoInit(self):
                # Where an application's OnInit would be, drawing the numbers
                # its world is made of.
                self.world = [random.random(), float(np.random.random())]

        return Probe

    def test_a_pinned_seed_is_in_force_by_the_time_a_world_is_built(
            self, monkeypatch):
        monkeypatch.setenv(entropy.SEED_ENV, '4242')
        probe = self._probe()
        entropy.forget()
        first = probe().world
        entropy.forget()
        assert probe().world == first

    def test_a_context_has_a_seed_whether_or_not_one_was_asked_for(self):
        self._probe()()
        assert isinstance(entropy.seed(), int)

    def test_without_one_the_world_is_different_every_time(self):
        probe = self._probe()
        entropy.forget()
        first = probe().world
        entropy.forget()
        assert probe().world != first
