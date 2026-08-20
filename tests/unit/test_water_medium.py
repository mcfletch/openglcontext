"""What a substance does to a body inside it, and where the substances are.

A table and a box test, so none of it needs a window.
"""
import pytest

from OpenGLContext.scenegraph.water.medium import (
    LAVA,
    MEDIA,
    SLIME,
    WATER,
    Medium,
    medium_for,
    worst_of,
)
from OpenGLContext.scenegraph.water.volumes import Volume, Volumes


class TestTheStandardMedia:
    def test_the_three_a_game_needs_are_there(self) -> None:
        assert {WATER, SLIME, LAVA} <= set(MEDIA)

    def test_water_does_not_hurt(self) -> None:
        """In the table at zero rather than left out: "water does not hurt" is
        a decision, and a table with a hole in it reads as an oversight."""
        assert MEDIA[WATER].harm == 0.0

    def test_lava_hurts_most(self) -> None:
        assert MEDIA[LAVA].harm > MEDIA[SLIME].harm > MEDIA[WATER].harm

    def test_you_can_see_furthest_through_water(self) -> None:
        assert MEDIA[WATER].visibility > MEDIA[SLIME].visibility \
            > MEDIA[LAVA].visibility

    def test_none_of_them_is_silent(self) -> None:
        """Total silence reads as the sound having broken, not as being under
        water, and a player still needs to hear what is shooting at them."""
        assert all(0.0 < one.muffle < 1.0 for one in MEDIA.values())

    def test_they_are_dark(self) -> None:
        """The fog blends in linear HDR before tone mapping, so a colour that
        reads as a pleasant mid-blue arrives far brighter than the level: a fog
        that makes distant walls brighter is a fog lamp, not a body of water."""
        assert all(max(one.color) < 0.6 for one in MEDIA.values())


class TestAskingForOne:
    def test_by_name(self) -> None:
        assert medium_for(WATER) is MEDIA[WATER]

    def test_nothing_named_is_dry_air(self) -> None:
        assert medium_for('') is None

    def test_a_substance_nobody_declared_is_still_a_substance(self) -> None:
        """A map may name one this table has no entry for, and reading that as
        dry air is the one wrong answer: the camera is inside something."""
        assert medium_for('quicksilver') is not None

    def test_air_is_not_a_medium(self) -> None:
        assert medium_for(None) is None


class TestWhichOneMatters:
    def test_the_worst_of_several_is_the_one_reported(self) -> None:
        """A body may span two; a swimmer needs to hear about the one that will
        hurt them, not the one that happened to be found first."""
        assert worst_of([WATER, LAVA, SLIME]) == LAVA

    def test_slime_beats_water(self) -> None:
        assert worst_of([WATER, SLIME]) == SLIME

    def test_nothing_is_dry_air(self) -> None:
        assert worst_of([]) == ''

    def test_one_nobody_declared_is_taken_seriously(self) -> None:
        assert worst_of(['quicksilver']) == 'quicksilver'


class TestWhereTheyAre:
    def _volumes(self):
        return Volumes([
            Volume(minimum=(-10.0, -5.0, -10.0), maximum=(10.0, 0.0, 10.0),
                   medium=WATER),
            Volume(minimum=(20.0, -8.0, -10.0), maximum=(40.0, -2.0, 10.0),
                   medium=LAVA),
        ])

    def test_a_point_inside_one_finds_it(self) -> None:
        assert self._volumes().medium_at((0.0, -1.0, 0.0)) == WATER

    def test_a_point_in_the_air_finds_nothing(self) -> None:
        assert self._volumes().medium_at((0.0, 5.0, 0.0)) == ''

    def test_a_point_outside_them_all_finds_nothing(self) -> None:
        assert self._volumes().medium_at((100.0, -1.0, 0.0)) == ''

    def test_the_surface_counts_as_inside(self) -> None:
        """A body exactly at the waterline is in the water: the alternative is
        a plane one frame thick where the swimmer is neither."""
        assert self._volumes().medium_at((0.0, 0.0, 0.0)) == WATER

    def test_a_body_in_two_hears_about_the_worse(self) -> None:
        both = Volumes([
            Volume(minimum=(-10.0, -5.0, -10.0), maximum=(10.0, 0.0, 10.0),
                   medium=WATER),
            Volume(minimum=(-1.0, -5.0, -1.0), maximum=(1.0, 0.0, 1.0),
                   medium=LAVA),
        ])
        assert both.medium_at((0.0, -1.0, 0.0)) == LAVA

    def test_an_empty_world_is_dry(self) -> None:
        assert Volumes([]).medium_at((0.0, 0.0, 0.0)) == ''

    def test_a_flat_sheet_can_be_a_volume(self) -> None:
        """A lake is a level and a footprint; how deep it goes is the bed's
        business, so a caller says how far down to look."""
        lake = Volumes([Volume.below((-100.0, -100.0), (100.0, 100.0),
                                     level=3.0, depth=50.0, medium=WATER)])
        assert lake.medium_at((0.0, 2.9, 0.0)) == WATER
        assert lake.medium_at((0.0, 3.1, 0.0)) == ''
        assert lake.medium_at((0.0, -48.0, 0.0)) == ''   # under the bed


class TestWhichRuleDecides:
    """Two worlds want two different answers when volumes overlap, and both
    are right about their own maps."""

    def _nested(self):
        return Volumes([
            Volume(minimum=(-10.0, -5.0, -10.0), maximum=(10.0, 0.0, 10.0),
                   medium=WATER),
            Volume(minimum=(-1.0, -5.0, -1.0), maximum=(1.0, 0.0, 1.0),
                   medium=SLIME),
        ])

    def test_by_default_the_worst_wins(self) -> None:
        """A swimmer needs to hear about the one that will hurt them."""
        assert self._nested().medium_at((0.0, -1.0, 0.0)) == SLIME

    def test_the_smallest_can_win_instead(self) -> None:
        """A pit inside a flooded room: where the boxes are a partition's own
        bounds rather than the liquid's shape, the smaller box is the more
        specific answer."""
        assert self._nested().medium_at((0.0, -1.0, 0.0), rule='smallest') \
            == SLIME

    def test_the_two_rules_can_disagree(self) -> None:
        volumes = Volumes([
            Volume(minimum=(-1.0, -5.0, -1.0), maximum=(1.0, 0.0, 1.0),
                   medium=WATER),
            Volume(minimum=(-10.0, -5.0, -10.0), maximum=(10.0, 0.0, 10.0),
                   medium=LAVA),
        ])
        assert volumes.medium_at((0.0, -1.0, 0.0)) == LAVA
        assert volumes.medium_at((0.0, -1.0, 0.0), rule='smallest') == WATER

    def test_a_rule_nobody_offers_is_refused(self) -> None:
        with pytest.raises(ValueError):
            self._nested().medium_at((0.0, -1.0, 0.0), rule='deepest')

    def test_either_rule_finds_nothing_in_the_air(self) -> None:
        for rule in ('worst', 'smallest'):
            assert self._nested().medium_at((0.0, 9.0, 0.0), rule=rule) == ''
