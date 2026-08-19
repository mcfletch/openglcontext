"""A row of lamps: a count a player sees rather than reads.

Some counts want a number and some want a shape. Ammunition wants a number.
A start sequence does not: what a driver acts on is *how much of the rig is
lit*, taken in at a glance with their eyes on the road, and a numeral makes
them read it instead.

The whole of it is the geometry -- where each lamp sits and which of them are
burning -- so none of it needs a window.
"""
import pytest

from OpenGLContext.ui.hudwidgets import LampRow
from OpenGLContext.ui.layout import Rect


class _Metrics:
    """Font metrics at the reference size: a pixel is a pixel."""

    char_height = 16

    @staticmethod
    def pixels(value):
        return int(round(float(value)))

    @staticmethod
    def text_width(text):
        return 8 * len(text)


METRICS = _Metrics()


def _row(**named):
    found = LampRow(**named)
    found.rect = Rect(0, 0, *found.content_size(METRICS))
    return found


class TestHowManyAreBurning:
    def test_a_fresh_rig_is_dark(self):
        assert _row().lit == 0

    def test_it_lights_from_one_end(self):
        row = _row(count=5, lit=2)
        assert [row.burning(at) for at in range(5)] == \
            [True, True, False, False, False]

    def test_a_full_rig_is_all_lit(self):
        row = _row(count=4, lit=4)
        assert all(row.burning(at) for at in range(4))

    def test_more_lit_than_there_are_lamps_is_all_of_them(self):
        """A caller counting something else's count is not an error here."""
        row = _row(count=3, lit=9)
        assert all(row.burning(at) for at in range(3))

    def test_fewer_than_none_is_none(self):
        row = _row(count=3, lit=-2)
        assert not any(row.burning(at) for at in range(3))

    def test_a_lamp_that_is_not_there_is_not_burning(self):
        assert not _row(count=3, lit=3).burning(7)


class TestWhereTheLampsSit:
    def test_a_rig_is_as_wide_as_its_lamps_and_the_gaps_between(self):
        row = _row(count=5, lampSize=20.0, gap=10.0)
        assert row.content_size(METRICS)[0] == 5 * 20 + 4 * 10

    def test_and_as_tall_as_one_lamp(self):
        assert _row(count=5, lampSize=20.0).content_size(METRICS)[1] == 20

    def test_one_lamp_has_no_gaps(self):
        row = _row(count=1, lampSize=20.0, gap=10.0)
        assert row.content_size(METRICS)[0] == 20

    def test_no_lamps_take_no_room(self):
        assert _row(count=0).content_size(METRICS) == (0, 0)

    def test_they_are_evenly_spaced_along_the_row(self):
        row = _row(count=4, lampSize=20.0, gap=10.0)
        lefts = [row.lampRect(at, METRICS).x for at in range(4)]
        assert lefts == [0, 30, 60, 90]

    def test_each_is_square(self):
        found = _row(count=3, lampSize=18.0).lampRect(1, METRICS)
        assert (found.width, found.height) == (18, 18)

    def test_the_row_ends_where_it_says_it_does(self):
        row = _row(count=5, lampSize=20.0, gap=10.0)
        assert row.lampRect(4, METRICS).right == row.content_size(METRICS)[0]


class TestWhatColourTheyAre:
    class _Skin:
        hudCritical = (1.0, 0.4, 0.35, 1)
        hudTrack = (1, 1, 1, 0.15)

    SKIN = _Skin()

    def test_a_burning_lamp_takes_the_skin_s_warning_colour(self):
        """Red, because that is what a start rig is everywhere it exists."""
        row = _row(count=3, lit=2)
        assert row.lampColour(0, self.SKIN) == self.SKIN.hudCritical

    def test_a_dark_one_is_the_skin_s_unlit_colour(self):
        row = _row(count=3, lit=2)
        assert row.lampColour(2, self.SKIN) == self.SKIN.hudTrack

    def test_a_game_may_choose_its_own_colour_for_the_lit_ones(self):
        row = _row(count=3, lit=1, color=(0.2, 0.9, 0.3, 1.0))
        assert tuple(row.lampColour(0, self.SKIN)) == (0.2, 0.9, 0.3, 1.0)

    def test_and_the_dark_ones_stay_the_skin_s(self):
        row = _row(count=3, lit=1, color=(0.2, 0.9, 0.3, 1.0))
        assert row.lampColour(2, self.SKIN) == self.SKIN.hudTrack


class TestTheHousingAndTheHalo:
    """A lamp reads as a lamp because of what is around it."""

    class _Skin:
        hudCritical = (1.0, 0.4, 0.35, 1)
        hudTrack = (1, 1, 1, 0.15)
        hudFill = (0, 0, 0, 0.45)

    SKIN = _Skin()

    def test_every_lamp_has_a_housing_whether_it_burns_or_not(self):
        """An unlit rig is still a rig: five places, none of them alight."""
        row = _row(count=5, lit=0, lampSize=20.0)
        assert all(row.housingRect(at, METRICS).width > 20 for at in range(5))

    def test_the_housing_is_centred_on_its_lamp(self):
        row = _row(count=3, lampSize=20.0)
        lamp = row.lampRect(1, METRICS)
        housing = row.housingRect(1, METRICS)
        assert (lamp.x + lamp.width / 2 == housing.x + housing.width / 2)

    def test_a_halo_stays_inside_the_spacing(self):
        """Two burning lamps have to read as two, not as a bar of light."""
        row = _row(count=5, lampSize=26.0, gap=12.0, lit=5)
        first = row.haloRect(0, METRICS)
        second = row.haloRect(1, METRICS)
        assert first.right <= second.x + 1

    def test_a_halo_carries_the_lamp_s_own_colour(self):
        row = _row(count=3, lit=3, color=(1.0, 0.2, 0.1, 1.0))
        assert row.haloColour(0, self.SKIN)[:3] == pytest.approx((1.0, 0.2, 0.1))

    def test_and_carries_it_faintly(self):
        row = _row(count=3, lit=3, haloStrength=0.3)
        assert row.haloColour(0, self.SKIN)[3] == pytest.approx(0.3)


class TestBeingSeen:
    def test_a_rig_of_no_lamps_draws_nothing(self):
        """Nothing to say and no space taken saying it."""
        assert _row(count=0).visibleLamps() == []

    def test_a_rig_lists_its_lamps(self):
        assert _row(count=4).visibleLamps() == [0, 1, 2, 3]


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
