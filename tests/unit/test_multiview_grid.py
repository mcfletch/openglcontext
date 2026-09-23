"""The grid a view is measured against.

An editor's views draw a grid to place things on: one line every so many
units, thicker every so many lines, in the plane the view looks at. How
closely it is ruled follows the view's scale, so a view zoomed out is not a
sheet of solid lines and one zoomed in is not a bare field.

Headless: which lines to draw, and where they are in the world.
"""
import numpy as np
import pytest

from OpenGLContext.edit.mapview import MapView, MapViewPlatform
from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform
from OpenGLContext.multiview.grid import (
    DECADE,
    Grid,
    lines_for,
    spacing_for,
)
from OpenGLContext.multiview.views import View

SIZE = (400, 300)


def _view(camera):
    view = View(camera, name='view')
    view.rect = (0, 0, *SIZE)
    return view


def _plan(span=100.0):
    return _view(MapViewPlatform(MapView(span=span), SIZE))


def _elevation(span=100.0):
    return _view(OrthoViewPlatform(OrthoView('front', span=span), SIZE))


def _angled(distance=100.0):
    return _view(OrbitViewPlatform(OrbitView(distance=distance), SIZE))


class TestHowCloselyItIsRuled:
    """The spacing follows the scale, in the steps a ruler is marked in."""

    def test_the_step_is_one_of_the_ones_a_ruler_has(self):
        for shown in (0.4, 3.0, 17.0, 260.0, 9000.0):
            assert spacing_for(shown, SIZE[1]) in _steps()

    def test_a_closer_view_is_ruled_more_finely(self):
        far = spacing_for(1000.0, SIZE[1])
        near = spacing_for(10.0, SIZE[1])
        assert near < far

    def test_the_lines_stay_far_enough_apart_to_be_read(self):
        """However far out a view is zoomed, the grid is not a grey wash."""
        for shown in (1.0, 12.0, 340.0, 5000.0, 120000.0):
            spacing = spacing_for(shown, SIZE[1])
            pixels = spacing / shown * SIZE[1]
            assert pixels >= 4.0, (shown, spacing, pixels)

    def test_and_close_enough_together_to_be_a_grid(self):
        for shown in (1.0, 12.0, 340.0, 5000.0, 120000.0):
            spacing = spacing_for(shown, SIZE[1])
            pixels = spacing / shown * SIZE[1]
            assert pixels <= 4.0 * DECADE, (shown, spacing, pixels)

    def test_a_view_showing_nothing_is_still_asked_safely(self):
        assert spacing_for(0.0, SIZE[1]) > 0.0
        assert spacing_for(10.0, 0) > 0.0


def _steps():
    """One, two and five in every decade, which is how a ruler is marked."""
    return {step * DECADE ** power
            for step in (1.0, 2.0, 5.0) for power in range(-6, 9)}


class TestWhereTheLinesAre:
    def test_a_plan_view_is_ruled_across_the_ground(self):
        lines = lines_for(_plan(span=100.0))
        assert lines is not None
        for start, end in lines.segments:
            assert start[1] == pytest.approx(0.0)
            assert end[1] == pytest.approx(0.0)

    def test_an_elevation_is_ruled_in_its_own_plane(self):
        """The front view looks down -z, so its grid stands in x and y."""
        lines = lines_for(_elevation(span=100.0))
        assert lines is not None
        for start, end in lines.segments:
            assert start[2] == pytest.approx(0.0)
            assert end[2] == pytest.approx(0.0)

    def test_a_view_that_turns_is_ruled_across_the_ground(self):
        lines = lines_for(_angled())
        assert lines is not None
        for start, _end in lines.segments:
            assert start[1] == pytest.approx(0.0)

    def test_it_covers_what_the_view_shows(self):
        view = _plan(span=100.0)
        lines = lines_for(view)
        reach = max(abs(value) for start, end in lines.segments
                    for value in (start[0], start[2], end[0], end[2]))
        assert reach >= 50.0

    def test_it_follows_the_view_as_it_moves(self):
        view = _plan(span=100.0)
        view.camera.view.centre = (1000.0, 0.0)
        lines = lines_for(view)
        middle = np.mean([start[0] for start, _end in lines.segments])
        assert 900.0 < middle < 1100.0

    def test_the_lines_are_on_the_step_rather_than_where_the_view_happens_to_be(self):
        """So a line stands at a round number, which is what makes it a ruler."""
        view = _plan(span=100.0)
        view.camera.view.centre = (3.7, -2.2)
        lines = lines_for(view)
        step = lines.spacing
        for start, _end in lines.segments:
            along = start[0] if start[0] != _end[0] else start[2]
            assert abs(along / step - round(along / step)) < 1e-6

    def test_every_tenth_line_is_a_heavier_one(self):
        lines = lines_for(_plan(span=100.0))
        assert lines.heavy, 'no line was drawn heavier than the rest'
        assert len(lines.heavy) < len(lines.segments)

    def test_a_view_with_no_camera_has_nothing_to_rule(self):
        assert lines_for(View(name='plain')) is None


class TestTheNodeAViewDraws:
    def test_it_starts_off_in_every_view(self):
        grid = Grid()
        assert not grid.shownIn(_plan())

    def test_a_view_can_be_told_to_show_one(self):
        grid, view = Grid(), _plan()
        grid.show(view, True)
        assert grid.shownIn(view)
        grid.show(view, False)
        assert not grid.shownIn(view)

    def test_each_view_is_asked_for_itself(self):
        grid, plan, front = Grid(), _plan(), _elevation()
        grid.show(plan, True)
        assert grid.shownIn(plan) and not grid.shownIn(front)

    def test_a_view_it_has_never_heard_of_shows_nothing(self):
        assert not Grid().shownIn(View(name='elsewhere'))
