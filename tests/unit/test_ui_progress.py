"""How far something has got, when the something takes long enough to say.

A 450 MB download, a bake, a world streaming in: each is a wait a player sits
through, and a wait with no end in sight is the one that feels broken. The
overlay UI had a Slider -- which is a *control*, something a user moves -- and
nothing that simply reports. A progress bar is not a disabled slider: it takes
no input, has no thumb to grab, and its value is somebody else's news.
"""

import pytest

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.widgets import ProgressBar


class _Renderer:
    """Enough of the overlay renderer to record what a widget asked for."""

    def __init__(self):
        self.drawn = []
        self.skin = _Skin()
        self.metrics = _Metrics()

    def rect(self, rect, colour):
        self.drawn.append(('rect', rect, tuple(colour)))

    def pill(self, rect, colour):
        self.drawn.append(('pill', rect, tuple(colour)))

    def lines(self, rect, lines, colour, align='left'):
        self.drawn.append(('lines', rect, tuple(lines)))

    def textIn(self, rect, text, colour, align='left'):
        self.drawn.append(('text', rect, text))


class _Skin:
    trackFill = (0.1, 0.11, 0.14, 0.95)
    thumbFill = (0.55, 0.66, 0.8, 1.0)
    buttonDisabledFill = (0.14, 0.15, 0.17, 0.7)
    trackThickness = 6.0
    text = (1, 1, 1, 1)
    labelText = (1, 1, 1, 1)


class _Metrics:
    char_width = 8
    line_height = 16

    def wrap(self, text, width):
        return [text]


def bar(**named):
    made = ProgressBar(**named)
    made.rect = Rect(0, 0, 200, 20)
    return made


class TestWhatItReports:
    @pytest.mark.parametrize('given,wanted', [
        (0.0, 0.0), (0.5, 0.5), (1.0, 1.0),
        (-1.0, 0.0), (2.0, 1.0),            # somebody else's arithmetic
    ])
    def test_the_fraction_is_held_between_none_and_all(self, given, wanted):
        assert bar(fraction=given).filled == pytest.approx(wanted)

    def test_it_starts_at_nothing(self):
        assert bar().filled == 0.0

    def test_the_filled_part_is_that_much_of_the_width(self):
        made = bar(fraction=0.25)
        assert made.filled_rect().width == pytest.approx(200 * 0.25, abs=1)

    def test_nothing_done_draws_no_fill(self):
        assert bar(fraction=0.0).filled_rect().empty

    def test_all_done_fills_it(self):
        assert bar(fraction=1.0).filled_rect().width == 200


class TestWhatItDraws:
    def test_a_track_and_a_fill(self):
        made = bar(fraction=0.5)
        renderer = _Renderer()
        made.paint(renderer)
        assert [one[0] for one in renderer.drawn] == ['pill', 'pill']

    def test_the_fill_is_not_the_track_s_colour(self):
        """A bar whose fill matched its track would report nothing."""
        renderer = _Renderer()
        bar(fraction=0.5).paint(renderer)
        track, fill = renderer.drawn
        assert track[2] != fill[2]

    def test_an_empty_bar_draws_only_its_track(self):
        renderer = _Renderer()
        bar(fraction=0.0).paint(renderer)
        assert len(renderer.drawn) == 1

    def test_a_label_is_drawn_when_there_is_one(self):
        renderer = _Renderer()
        bar(fraction=0.4, text='Ashdown — 40%').paint(renderer)
        assert any(one[0] == 'lines' for one in renderer.drawn)

    def test_and_not_when_there_is_not(self):
        renderer = _Renderer()
        bar(fraction=0.4).paint(renderer)
        assert not any(one[0] == 'lines' for one in renderer.drawn)


class TestWhatItIsNot:
    """It reports; it does not ask."""

    def test_it_takes_no_focus(self):
        """Tabbing onto something a user cannot change wastes the key."""
        assert not bar().focusable

    def test_it_is_not_a_control(self):
        from OpenGLContext.ui.widgets import BoundWidget
        assert not isinstance(bar(), BoundWidget)
