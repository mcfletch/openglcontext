"""A map of the route, with the player on it.

A driver on an eight-kilometre circuit cannot see what is round the next bend
and has no idea how much of the lap is left. A map answers both, and it is the
same widget whether the route is a race circuit, a rally stage or a delivery
round -- so it takes a polyline and some marks and knows nothing about either.

The fitting is the whole of it: a route in world metres, drawn into a square of
pixels, keeping its shape. A map that stretches the circuit to fill its box is a
map of a different circuit.
"""
import numpy as np
import pytest

from OpenGLContext.ui.hudwidgets import MiniMap
from OpenGLContext.ui.layout import Rect


def _oval(count=64, across=800.0, along=400.0):
    angle = np.linspace(0.0, 2.0 * np.pi, count)
    return np.stack([np.cos(angle) * across, np.sin(angle) * along], axis=-1)


BOX = Rect(0, 0, 200, 200)


def _map(route=None, box=BOX, **named):
    found = MiniMap(**named)
    found.route = _oval() if route is None else route
    found.rect = box
    return found


class TestFittingARouteIntoABox:
    def test_the_whole_route_lands_inside(self) -> None:
        found = _map()
        drawn = np.asarray([found.at(x, z) for x, z in found.route])
        assert drawn[:, 0].min() >= -0.01 and drawn[:, 0].max() <= 200.01
        assert drawn[:, 1].min() >= -0.01 and drawn[:, 1].max() <= 200.01

    def test_and_touches_the_edges(self) -> None:
        """Fitted, not shrunk into the middle."""
        found = _map(inset=0.0)
        drawn = np.asarray([found.at(x, z) for x, z in found.route])
        assert drawn[:, 0].max() - drawn[:, 0].min() > 195.0

    def test_it_keeps_the_route_s_shape(self) -> None:
        """Twice as wide as it is long, and it still is on the map."""
        found = _map(inset=0.0)
        drawn = np.asarray([found.at(x, z) for x, z in found.route])
        wide = drawn[:, 0].max() - drawn[:, 0].min()
        tall = drawn[:, 1].max() - drawn[:, 1].min()
        assert wide / tall == pytest.approx(2.0, rel=0.05)

    def test_the_middle_of_the_route_is_the_middle_of_the_box(self) -> None:
        found = _map()
        middle = found.at(0.0, 0.0)
        assert middle[0] == pytest.approx(100.0, abs=1.0)
        assert middle[1] == pytest.approx(100.0, abs=1.0)

    def test_an_inset_keeps_the_edge_clear(self) -> None:
        found = _map(inset=20.0)
        drawn = np.asarray([found.at(x, z) for x, z in found.route])
        assert drawn[:, 0].min() >= 19.0

    def test_a_route_of_one_point_is_not_a_division(self) -> None:
        found = _map(route=np.zeros((1, 2)))
        assert found.at(0.0, 0.0) == pytest.approx((100.0, 100.0), abs=1.0)

    def test_no_route_at_all_draws_nothing(self) -> None:
        found = MiniMap()
        found.rect = Rect(0, 0, 200, 200)
        assert found.strokes() == []

    def test_it_is_square_by_default(self) -> None:
        found = MiniMap(size=160.0)
        assert found.content_size(_Metrics()) == (160, 160)


class TestWhatIsDrawn:
    def test_the_route_is_a_stroke_per_segment(self) -> None:
        found = _map(route=_oval(count=8))
        assert len(found.strokes()) == 7

    def test_each_stroke_joins_two_places_on_the_map(self) -> None:
        found = _map(route=_oval(count=8))
        start, end = found.strokes()[0]
        assert start != end
        assert 0.0 <= start[0] <= 200.0

    def test_a_long_route_is_thinned_rather_than_drawn_whole(self) -> None:
        """Two thousand quads for a line nobody can see the corners of."""
        found = _map(route=_oval(count=2000))
        assert len(found.strokes()) < 200

    def test_a_mark_is_where_the_thing_is(self) -> None:
        found = _map()
        found.marks = [(800.0, 0.0, 'player')]
        (x, _y), _kind = found.marked()[0]
        assert x > 150.0

    def test_marks_off_the_map_are_still_on_it(self) -> None:
        """A car that has left the road is somewhere, and that is worth seeing."""
        found = _map()
        found.marks = [(4000.0, 0.0, 'player')]
        (x, _y), _kind = found.marked()[0]
        assert 0.0 <= x <= 200.0

    def test_with_nothing_to_mark_it_marks_nothing(self) -> None:
        assert _map().marked() == []


class _Metrics:
    """Enough of a font metrics object to size a widget."""

    def pixels(self, value):
        return int(round(float(value)))


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestTheColoursMarksAreDrawnIn:
    """A mark names a colour in the skin. A skin's colours are arrays, so
    asking whether one is "truthy" is asking a vector a yes-or-no question --
    which numpy quite rightly refuses to answer."""

    def test_a_named_colour_is_taken_from_the_skin(self) -> None:
        found = _map()
        assert found.colour(_Skin(), 'crosshair') is _Skin.crosshair

    def test_a_name_the_skin_does_not_have_falls_back(self) -> None:
        found = _map()
        assert found.colour(_Skin(), 'nonesuch') is _Skin.crosshair


class _Skin:
    """A skin whose colours are arrays, which is what a real one has."""

    crosshair = np.array([1.0, 1.0, 1.0, 1.0])
    hudText = np.array([0.8, 0.8, 0.8, 1.0])
    hudTrack = np.array([0.0, 0.0, 0.0, 0.4])
