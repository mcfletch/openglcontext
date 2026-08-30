"""A NURBS surface's control points, as markers a pointer can pick and drag.

The surface itself is not pickable at a point -- it is one shape, and a pick
answers with the shape.  So the net puts a marker on every control point, and a
picked marker is a control point by name.

Headless: markers are scenegraph nodes and moving one is an array write.
"""
import numpy as np
import pytest

from OpenGLContext.edit.controlnet import ControlNet
from OpenGLContext.scenegraph.basenodes import (
    NurbsCurve, NurbsSurface, Transform,
)
from OpenGLContext.scenegraph.nodepath import NodePath


KNOTS = (0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0)


def _surface():
    """A flat 4x4 patch, one unit between control points."""
    points = [[[float(u), float(v), 0.0] for v in range(4)] for u in range(4)]
    return NurbsSurface(controlPoint=points, uDimension=4, vDimension=4,
                        uKnot=KNOTS, vKnot=KNOTS)


def _polylines(lines):
    """The cage's index list split back into the polylines it draws."""
    polylines, current = [], []
    for index in lines.geometry.coordIndex:
        if int(index) < 0:
            polylines.append(current)
            current = []
        else:
            current.append(int(index))
    if current:
        polylines.append(current)
    return polylines


class TestMarkers:
    """One marker per control point, standing where the point is."""

    def test_there_is_a_marker_for_every_control_point(self):
        net = ControlNet(_surface())
        assert len(net.markers) == 16
        assert all(marker in net.node.children for marker in net.markers)

    def test_each_marker_stands_on_its_control_point(self):
        surface = _surface()
        net = ControlNet(surface)
        for index, marker in enumerate(net.markers):
            assert np.allclose(marker.translation, surface.controlPoint[index])

    def test_a_path_through_a_marker_names_its_control_point(self):
        net = ControlNet(_surface())
        for index in (0, 5, 15):
            path = NodePath([net.node, net.markers[index]])
            assert net.index_for([path]) == index

    def test_a_path_through_something_else_names_no_control_point(self):
        net = ControlNet(_surface())
        assert net.index_for([NodePath([Transform()])]) is None
        assert net.index_for([]) is None


class TestTheCage:
    """The lines between the points, which are what show the grid's shape."""

    def test_every_row_and_every_column_is_drawn(self):
        """A marker on its own says where a point is; the lines say which
        points it is between, which is what tells a designer what a pull will
        do to the surface."""
        net = ControlNet(_surface())
        drawn = _polylines(net.lines)
        rows = [[row * 4 + column for column in range(4)] for row in range(4)]
        columns = [[row * 4 + column for row in range(4)] for column in range(4)]
        assert drawn == rows + columns

    def test_the_cage_stands_on_the_control_points(self):
        surface = _surface()
        net = ControlNet(surface)
        assert np.allclose(net.lines.geometry.coord.point, surface.controlPoint)

    def test_the_cage_cannot_be_picked(self):
        """It is there to be read, not aimed at: a click meant for the point
        or the surface behind it must not be swallowed by a line over them."""
        net = ControlNet(_surface())
        assert not net.lines.pickable

    def test_moving_a_point_takes_the_cage_with_it(self):
        net = ControlNet(_surface())
        net.move(5, (1.0, 2.0, 3.0))
        assert np.allclose(net.lines.geometry.coord.point[5], (1.0, 2.0, 3.0))

    def test_the_cage_points_are_assigned_rather_than_written_through(self):
        """The line buffer is cached against the coordinate's own field, so an
        in-place write would leave the cage drawn where the point used to be."""
        net = ControlNet(_surface())
        before = net.lines.geometry.coord.point
        net.move(5, (1.0, 2.0, 3.0))
        assert net.lines.geometry.coord.point is not before

    def test_a_curve_is_one_polyline_through_its_points(self):
        """A curve has no grid to cross, so the cage is the polygon itself."""
        curve = NurbsCurve(controlPoint=[[0, 0, 0], [1, 1, 0], [2, 0, 0]])
        net = ControlNet(curve)
        assert _polylines(net.lines) == [[0, 1, 2]]

    def test_the_cage_is_drawn_with_the_markers_over_it(self):
        """The markers are what a pointer aims at, so they come last."""
        net = ControlNet(_surface())
        assert net.node.children[0] is net.lines
        assert list(net.node.children[1:]) == list(net.markers)


class TestMoving:
    """Writing a moved point back to the surface."""

    def test_moving_a_point_moves_its_marker(self):
        net = ControlNet(_surface())
        net.move(5, (1.0, 2.0, 3.0))
        assert np.allclose(net.markers[5].translation, (1.0, 2.0, 3.0))

    def test_moving_a_point_rewrites_the_surface(self):
        surface = _surface()
        net = ControlNet(surface)
        net.move(5, (1.0, 2.0, 3.0))
        assert np.allclose(surface.controlPoint[5], (1.0, 2.0, 3.0))

    def test_the_field_is_assigned_rather_than_written_through(self):
        """The tessellation is cached against the field, and a cache watches
        for the field being *set*.  An in-place write would leave the old
        surface on screen under the new control net."""
        surface = _surface()
        net = ControlNet(surface)
        before = surface.controlPoint
        net.move(5, (1.0, 2.0, 3.0))
        assert surface.controlPoint is not before
        assert np.allclose(before[5], (1.0, 1.0, 0.0))

    def test_the_other_points_are_left_alone(self):
        surface = _surface()
        net = ControlNet(surface)
        original = np.array(surface.controlPoint, copy=True)
        net.move(5, (1.0, 2.0, 3.0))
        moved = np.asarray(surface.controlPoint)
        assert np.allclose(np.delete(moved, 5, axis=0),
                           np.delete(original, 5, axis=0))

    def test_point_answers_where_a_control_point_stands(self):
        net = ControlNet(_surface())
        net.move(5, (1.0, 2.0, 3.0))
        assert np.allclose(net.point(5), (1.0, 2.0, 3.0))

    def test_an_index_outside_the_net_is_refused(self):
        net = ControlNet(_surface())
        with pytest.raises(IndexError):
            net.move(16, (0.0, 0.0, 0.0))


class TestSelection:
    """Which point is being worked on, and showing it."""

    def test_nothing_is_selected_to_begin_with(self):
        net = ControlNet(_surface())
        assert net.selected is None

    def test_selecting_marks_the_one_marker(self):
        net = ControlNet(_surface())
        plain = net.markers[5].children[0].appearance
        net.select(5)
        assert net.selected == 5
        assert net.markers[5].children[0].appearance is not plain
        assert net.markers[6].children[0].appearance is plain

    def test_selecting_another_releases_the_first(self):
        net = ControlNet(_surface())
        plain = net.markers[5].children[0].appearance
        net.select(5)
        net.select(6)
        assert net.selected == 6
        assert net.markers[5].children[0].appearance is plain

    def test_deselecting_puts_the_marker_back(self):
        net = ControlNet(_surface())
        plain = net.markers[5].children[0].appearance
        net.select(5)
        net.deselect()
        assert net.selected is None
        assert net.markers[5].children[0].appearance is plain

    def test_deselecting_nothing_is_harmless(self):
        net = ControlNet(_surface())
        net.deselect()
        assert net.selected is None

    def test_markers_share_one_appearance_so_they_batch(self):
        """Sixty-odd identical spheres are one instanced draw when they share
        a geometry and an appearance; a node each would be sixty draws."""
        net = ControlNet(_surface())
        appearances = {id(marker.children[0].appearance)
                       for marker in net.markers}
        geometries = {id(marker.children[0].geometry)
                      for marker in net.markers}
        assert len(appearances) == 1
        assert len(geometries) == 1
