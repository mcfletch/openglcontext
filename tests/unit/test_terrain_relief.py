"""Micro-relief: the grain a tile carries once it is close enough to show it."""
import numpy as np
import pytest

from OpenGLContext.scenegraph.terrain.relief import GROUND_RELIEF, Relief


def _grid(side=64.0, count=33, at=0.0):
    axis = np.linspace(at, at + side, count)
    return np.meshgrid(axis, axis, indexing='ij')


class TestWhichFeaturesATileCanCarry:
    def test_a_coarse_tile_carries_none_of_them(self) -> None:
        """A feature four metres across sampled every sixty is noise."""
        assert Relief().bands(spacing=60.0) == ()

    def test_a_fine_tile_carries_the_lot(self) -> None:
        relief = Relief()
        assert len(relief.bands(spacing=0.05)) == len(relief.wavelengths())

    def test_and_each_step_finer_adds_one(self) -> None:
        relief = Relief()
        counts = [len(relief.bands(spacing=relief.coarsest / 2.0 ** k))
                  for k in range(6)]
        assert counts == sorted(counts)
        assert counts[-1] - counts[0] <= 6

    def test_a_feature_is_only_drawn_where_it_is_sampled(self) -> None:
        relief = Relief(coarsest=32.0, finest=32.0, samples_per_feature=4.0)
        assert relief.bands(spacing=8.0) == (32.0,)
        assert relief.bands(spacing=8.01) == ()


class TestHowFarTheGroundMoves:
    def test_never_further_than_the_error_the_streamer_allows(self) -> None:
        relief = Relief()
        for error in (0.01, 0.1, 1.0, 4.0, 90.0):
            gx, gz = _grid()
            found = relief.height(gx, gz, spacing=0.25, error=error)
            assert float(np.abs(found).max()) <= error + 1e-9

    def test_a_tile_with_no_features_to_carry_is_left_flat(self) -> None:
        gx, gz = _grid()
        found = Relief().height(gx, gz, spacing=120.0, error=180.0)
        assert not found.any()

    def test_the_ground_is_moved_both_ways_about_where_it_was(self) -> None:
        """Relief is grain in the surface, not a layer laid over it: a hillside
        with relief on it sits where the hillside did."""
        gx, gz = _grid(side=512.0, count=129)
        found = Relief().height(gx, gz, spacing=0.5, error=2.0)
        assert float(found.min()) < 0.0 < float(found.max())
        assert float(abs(found.mean())) < 0.1 * float(np.abs(found).max())

    def test_and_it_is_the_same_ground_every_time(self) -> None:
        gx, gz = _grid()
        first = Relief().height(gx, gz, spacing=0.5, error=2.0)
        second = Relief().height(gx, gz, spacing=0.5, error=2.0)
        assert np.array_equal(first, second)

    def test_two_tiles_meeting_agree_along_their_edge(self) -> None:
        """The relief is a function of where the ground is, not of which tile is
        drawing it, so neighbours at one level need nothing said between them."""
        relief = Relief()
        z = np.linspace(-40.0, 40.0, 81)
        edge = np.full_like(z, 64.0)
        left = relief.height(edge, z, spacing=0.5, error=2.0)
        right = relief.height(edge, z, spacing=0.5, error=2.0)
        assert np.array_equal(left, right)

    def test_a_seed_chooses_which_grain(self) -> None:
        gx, gz = _grid()
        one = Relief(seed=1).height(gx, gz, spacing=0.5, error=2.0)
        two = Relief(seed=2).height(gx, gz, spacing=0.5, error=2.0)
        assert not np.allclose(one, two)

    def test_the_shape_asked_for_is_the_shape_answered(self) -> None:
        found = Relief().height(np.zeros((3, 4)), np.zeros((3, 4)),
                                spacing=0.5, error=2.0)
        assert found.shape == (3, 4)

    def test_nothing_is_added_where_nothing_is_asked_for(self) -> None:
        gx, gz = _grid()
        assert not Relief(roughness=0.0).height(
            gx, gz, spacing=0.1, error=9.0).any()


class TestGroundWithReliefOnIt:
    def _flat(self, x, z):
        return np.zeros(np.broadcast(np.asarray(x), np.asarray(z)).shape)

    def test_a_height_function_can_be_given_the_grain(self) -> None:
        ground = Relief().over(self._flat, spacing=0.5, error=2.0)
        gx, gz = _grid()
        assert np.abs(ground(gx, gz)).max() > 0.0

    def test_and_what_it_answers_is_the_ground_plus_the_grain(self) -> None:
        relief = Relief()
        ground = relief.over(lambda x, _z: np.full(np.shape(x), 12.0),
                             spacing=0.5, error=2.0)
        gx, gz = _grid()
        assert np.allclose(ground(gx, gz) - 12.0,
                           relief.height(gx, gz, spacing=0.5, error=2.0))

    def test_a_tile_too_coarse_for_any_of_it_gets_its_own_function_back(self) -> None:
        """Nothing wrapped, so a coarse tile pays nothing for a feature it could
        not draw."""
        flat = self._flat
        assert Relief().over(flat, spacing=200.0, error=300.0) is flat


class TestTheReliefAWorldUses:
    def test_it_is_a_relief(self) -> None:
        assert isinstance(GROUND_RELIEF, Relief)

    def test_its_features_run_from_a_footstep_to_a_hillock(self) -> None:
        assert GROUND_RELIEF.finest <= 1.0
        assert 8.0 <= GROUND_RELIEF.coarsest <= 64.0

    def test_and_it_is_gentle_enough_to_walk_on(self) -> None:
        """Metres of rise per metre of feature: a tenth is a shallow slope, and
        relief steeper than the ground it is added to reads as spikes."""
        assert 0.0 < GROUND_RELIEF.roughness <= 0.15


class TestWhatARefusedDescriptionSays:
    def test_features_have_to_run_coarse_to_fine(self) -> None:
        with pytest.raises(ValueError):
            Relief(coarsest=1.0, finest=8.0)

    def test_and_a_feature_has_to_have_a_size(self) -> None:
        with pytest.raises(ValueError):
            Relief(finest=0.0)

    def test_and_has_to_be_sampled_more_than_once(self) -> None:
        with pytest.raises(ValueError):
            Relief(samples_per_feature=1.0)


class TestGrainSomethingElseHasToCarryToo:
    """The drawn surface and the collided one have to agree, so a band finer
    than the surface a world is collided against can hold is a band nothing
    should draw: it would be relief a player sees and walks straight through."""

    def test_the_fine_bands_can_be_held_back(self) -> None:
        held = Relief(coarsest=32.0, finest=0.5).no_finer_than(4.0)
        assert min(held.wavelengths()) >= 16.0

    def test_which_is_the_grain_a_grid_that_size_can_carry(self) -> None:
        relief = Relief(coarsest=32.0, finest=0.5)
        held = relief.no_finer_than(4.0)
        assert held.bands(spacing=4.0) == held.wavelengths()

    def test_a_grid_fine_enough_holds_it_all_back_from_nothing(self) -> None:
        relief = Relief()
        assert relief.no_finer_than(0.01).wavelengths() == relief.wavelengths()

    def test_and_what_comes_back_is_the_same_grain_otherwise(self) -> None:
        relief = Relief(coarsest=32.0, finest=0.5, roughness=0.05, seed=4)
        held = relief.no_finer_than(4.0)
        assert (held.roughness, held.seed, held.coarsest) \
            == (relief.roughness, relief.seed, relief.coarsest)

    def test_a_grid_too_coarse_for_any_of_it_leaves_the_coarsest(self) -> None:
        """One band and no relief are different answers, and a surface with a
        band it cannot quite resolve is better than a surface with none."""
        held = Relief(coarsest=24.0, finest=0.75).no_finer_than(400.0)
        assert held.wavelengths() == (24.0,)


class TestGroundThatWasGraded:
    """Not every surface has grain in it. A road is built by levelling the
    ground it runs on, and hummocks through the carriageway are hummocks a
    grader took out -- so a caller says where the grain applies and where the
    ground was worked."""

    def _beside(self, half=10.0, fade=10.0):
        def weight(x, _z):
            away = np.abs(np.asarray(x, dtype='d'))
            return np.clip((away - half) / fade, 0.0, 1.0)
        return weight

    def test_the_worked_ground_is_left_as_it_was(self) -> None:
        relief = Relief(where=self._beside())
        z = np.zeros(9)
        x = np.linspace(-8.0, 8.0, 9)
        assert not relief.height(x, z, spacing=0.5, error=4.0).any()

    def test_and_the_ground_past_it_keeps_its_grain(self) -> None:
        relief = Relief(where=self._beside())
        x = np.linspace(40.0, 200.0, 81)
        found = relief.height(x, np.zeros_like(x), spacing=0.5, error=4.0)
        assert float(np.abs(found).max()) > 0.1

    def test_it_comes_back_in_over_the_fade_rather_than_at_a_step(self) -> None:
        """A grader leaves a batter, not a cliff, and grain that switches on
        across one cell is a ridge down the length of the road."""
        relief = Relief(where=self._beside(half=10.0, fade=10.0))
        x = np.full(400, 15.0)
        z = np.linspace(0.0, 400.0, 400)
        half = relief.height(x, z, spacing=0.5, error=4.0)
        full = relief.height(x + 10.0, z, spacing=0.5, error=4.0)
        assert 0.0 < float(np.abs(half).max()) < float(np.abs(full).max())

    def test_a_height_function_given_the_grain_is_graded_too(self) -> None:
        relief = Relief(where=self._beside())
        ground = relief.over(lambda x, _z: np.zeros(np.shape(x)),
                             spacing=0.5, error=4.0)
        assert not np.asarray(ground(np.linspace(-8.0, 8.0, 9),
                                     np.zeros(9))).any()

    def test_and_holding_the_fine_bands_back_keeps_the_grading(self) -> None:
        where = self._beside()
        assert Relief(where=where).no_finer_than(4.0).where is where

    def test_a_relief_that_says_nothing_applies_everywhere(self) -> None:
        assert Relief().where is None
