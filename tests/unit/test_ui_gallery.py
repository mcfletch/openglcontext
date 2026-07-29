"""Choosing one of several things by looking at them.

A drop-down is the right control for a setting and the wrong one for a level:
what tells one arena from another is what it *looks* like, and a list of names
makes a player open each in turn to find out. So the carousel shows a band of
pictures with their names under them, and the arrows roll it along.

All of it is arithmetic — which items are on screen, what an arrow does at the
end of the list, how a band is laid out in the room it has — so none of it
needs a window.
"""

import pytest

from OpenGLContext.ui.gallery import Carousel, Picture
from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.metrics import FontMetrics


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


def carousel(count=5, **named):
    named.setdefault('options', ['map%d' % index for index in range(count)])
    named.setdefault('optionLabels', ['Map %d' % index for index in range(count)])
    named.setdefault('optionImages', ['/art/map%d.jpg' % index
                                      for index in range(count)])
    return Carousel(**named)


class TestOnePicture:

    def test_it_knows_where_its_image_is(self):
        assert Picture(url='/art/a.jpg').url == '/art/a.jpg'

    def test_it_asks_for_room_in_proportion(self):
        """A level shot is a landscape; a square slot crops or letterboxes it."""
        wide = Picture(url='/art/a.jpg', aspect=4 / 3.0)
        width, height = wide.content_size(FontMetrics(8, 16, 2))
        assert width > height

    def test_a_picture_with_no_image_still_has_a_size(self):
        """A level with no art must not collapse the row it is in."""
        width, height = Picture().content_size(FontMetrics(8, 16, 2))
        assert width > 0 and height > 0

    def test_it_takes_no_focus(self):
        """It is something to look at; the carousel round it is the control."""
        assert not Picture(url='/art/a.jpg').focusable


class TestWhatTheCarouselShows:

    def test_it_starts_on_the_first_option(self):
        assert carousel().value == 'map0'

    def test_it_can_start_on_a_named_one(self):
        assert carousel(value='map3').value == 'map3'

    def test_a_value_that_is_not_an_option_falls_back_to_the_first(self):
        """A remembered level that has since been deleted must not stick."""
        assert carousel(value='gone').value == 'map0'

    def test_it_shows_a_band_rather_than_one_at_a_time(self):
        """The whole point: you can see what is either side of your choice."""
        assert len(carousel(count=9, visibleCount=5).visible()) == 5

    def test_the_band_is_centred_on_the_selection(self):
        band = carousel(count=9, value='map4', visibleCount=5).visible()
        assert band[len(band) // 2].option == 'map4'

    def test_the_selected_item_says_it_is_selected(self):
        band = carousel(count=9, value='map4', visibleCount=5).visible()
        assert [item.selected for item in band] == [False, False, True,
                                                    False, False]

    def test_each_item_carries_its_label_and_its_art(self):
        band = carousel(count=9, value='map4', visibleCount=3).visible()
        assert [item.label for item in band] == ['Map 3', 'Map 4', 'Map 5']
        assert band[0].image == '/art/map3.jpg'

    def test_the_selection_stays_in_the_middle_even_at_the_start(self):
        """It rotates rather than sliding, so the band wraps round the ends.

        On the first option a band of three shows the *last* option to its
        left.  That is what a carousel is — the pictures move and the choice
        stays put — and it is the behaviour the arrows imply.  The alternative,
        clamping at the ends, moves the selection out from under the player's
        eye exactly when they reach the part of the list they were heading for.
        """
        band = carousel(count=3, visibleCount=3).visible()
        assert [item.label for item in band] == ['Map 2', 'Map 0', 'Map 1']
        assert band[1].selected

    def test_fewer_options_than_the_band_shows_them_all(self):
        assert len(carousel(count=2, visibleCount=5).visible()) == 2

    def test_no_options_shows_nothing_rather_than_failing(self):
        empty = Carousel(options=[], optionLabels=[], optionImages=[])
        assert empty.visible() == []
        assert empty.value == ''

    def test_a_missing_label_falls_back_to_the_option(self):
        """A caller who gave options and no labels still gets something read."""
        bare = Carousel(options=['aggressor', 'ce1m7'], visibleCount=1)
        assert bare.visible()[0].label == 'aggressor'

    def test_a_missing_image_is_no_image_rather_than_an_error(self):
        bare = Carousel(options=['a', 'b'], optionLabels=['A', 'B'],
                        visibleCount=1)
        assert bare.visible()[0].image == ''


class TestRollingItAlong:

    def test_the_right_arrow_moves_on(self):
        band = carousel()
        band.next()
        assert band.value == 'map1'

    def test_the_left_arrow_moves_back(self):
        band = carousel(value='map3')
        band.previous()
        assert band.value == 'map2'

    def test_it_wraps_at_the_end(self):
        """A band that stops dead at the last level makes the last level hard
        to reach from the first, which is the one journey a player repeats."""
        band = carousel(count=3, value='map2')
        band.next()
        assert band.value == 'map0'

    def test_it_wraps_at_the_beginning(self):
        band = carousel(count=3, value='map0')
        band.previous()
        assert band.value == 'map2'

    def test_the_band_that_is_shown_follows_the_selection(self):
        band = carousel(count=9, visibleCount=3)
        band.next()
        assert band.visible()[1].option == 'map1'

    def test_rolling_an_empty_carousel_is_harmless(self):
        empty = Carousel(options=[])
        empty.next()
        empty.previous()
        assert empty.value == ''

    def test_moving_tells_whoever_is_listening(self):
        seen = []
        band = carousel()
        band.on_change = lambda widget: seen.append(widget.value)
        band.next()
        assert seen == ['map1']

    def test_moving_to_where_it_already_is_says_nothing(self):
        """One option: every arrow press would otherwise be a change event."""
        seen = []
        band = carousel(count=1)
        band.on_change = lambda widget: seen.append(widget.value)
        band.next()
        assert seen == []

    def test_choosing_by_name_selects_it(self):
        band = carousel()
        band.select('map3')
        assert band.value == 'map3'

    def test_choosing_something_that_is_not_there_changes_nothing(self):
        band = carousel(value='map1')
        band.select('nowhere')
        assert band.value == 'map1'


class TestWhereEverythingLands:

    def laid(self, band, width=600, height=200):
        band.rect = Rect(0, 0, width, height)
        return band

    def test_the_arrows_sit_at_either_end(self, metrics):
        band = self.laid(carousel())
        left, right = band.arrowRects()
        assert left.x < right.x
        assert left.x >= band.rect.x
        assert right.x + right.width <= band.rect.x + band.rect.width

    def test_the_pictures_run_between_the_arrows(self, metrics):
        band = self.laid(carousel(count=5, visibleCount=3))
        left, right = band.arrowRects()
        slots = band.slotRects(metrics)
        assert slots
        assert min(slot.x for slot in slots) >= left.x + left.width
        assert max(slot.x + slot.width for slot in slots) <= right.x

    def test_the_slots_are_in_order_and_do_not_overlap(self, metrics):
        band = self.laid(carousel(count=9, visibleCount=5))
        slots = band.slotRects(metrics)
        for near, far in zip(slots, slots[1:], strict=False):
            assert near.x + near.width <= far.x + 1

    def test_a_narrow_band_still_lays_out(self, metrics):
        """A small window must not produce negative widths."""
        band = self.laid(carousel(count=9, visibleCount=5), width=120)
        assert all(slot.width >= 0 for slot in band.slotRects(metrics))

    def test_it_asks_for_room_for_a_picture_and_a_caption(self, metrics):
        _width, height = carousel().content_size(metrics)
        assert height > metrics.char_height * 2


class TestBeingClicked:

    def laid(self, band):
        band.rect = Rect(0, 0, 600, 200)
        return band

    def click(self, band, rect):
        band.press(rect.x + rect.width / 2, rect.y + rect.height / 2)
        band.release(rect.x + rect.width / 2, rect.y + rect.height / 2)

    def test_clicking_the_right_arrow_moves_on(self):
        band = self.laid(carousel())
        self.click(band, band.arrowRects()[1])
        assert band.value == 'map1'

    def test_clicking_the_left_arrow_moves_back(self):
        band = self.laid(carousel(value='map2'))
        self.click(band, band.arrowRects()[0])
        assert band.value == 'map1'

    def test_clicking_a_picture_chooses_it(self):
        """Faster than arrowing to something you can already see."""
        band = self.laid(carousel(count=9, value='map4', visibleCount=5))
        self.click(band, band.slotRects(FontMetrics(8, 16, 2))[-1])
        assert band.value == 'map6'

    def test_clicking_nothing_in_particular_changes_nothing(self):
        band = self.laid(carousel())
        band.press(-50, -50)
        band.release(-50, -50)
        assert band.value == 'map0'


class TestTheKeys:

    def test_the_arrow_keys_roll_it(self):
        band = carousel()
        assert band.key('<right>', (0, 0, 0))
        assert band.value == 'map1'
        assert band.key('<left>', (0, 0, 0))
        assert band.value == 'map0'

    def test_a_key_it_does_not_use_is_left_for_the_panel(self):
        """Tab must still move focus and Escape must still close the screen."""
        band = carousel()
        assert not band.key('<tab>', (0, 0, 0))
        assert not band.key('<escape>', (0, 0, 0))

    def test_it_takes_focus_so_the_keys_can_reach_it(self):
        assert carousel().focusable
