"""The tri-axis handle: which arm was grabbed, and where the drag takes it.

A gizmo is the answer to "I have picked a point, now let me move it".  Three
arms stand at the point, one per axis; grabbing one constrains the drag to that
axis, so a point moves in the direction the designer meant rather than
wherever the ray happened to land.

Headless: the closest approach of two lines is a division, and the arms are
scenegraph nodes that need no window to be built or walked.
"""
import math

import numpy as np
import pytest

from OpenGLContext.edit.gizmo import AXES, TranslationGizmo, axis_parameter
from OpenGLContext.events.mouseevents import MouseEvent
from OpenGLContext.scenegraph.basenodes import Transform, sceneGraph
from OpenGLContext.scenegraph.nodepath import NodePath


FIELD_OF_VIEW = math.radians(60.0)


def _matrices(eye=(0.0, 10.0, 20.0), target=(0.0, 0.0, 0.0),
              viewport=(0, 0, 800, 600), fov=FIELD_OF_VIEW):
    """A camera looking at a target, as the row-vector matrices an event has."""
    forward = np.asarray(target, 'd') - np.asarray(eye, 'd')
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, (0.0, 1.0, 0.0))
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    view = np.identity(4)
    view[:3, 0] = right
    view[:3, 1] = up
    view[:3, 2] = -forward
    view[3, :3] = -np.array([np.dot(eye, right), np.dot(eye, up),
                             np.dot(eye, -forward)])
    aspect = viewport[2] / viewport[3]
    f = 1.0 / math.tan(fov / 2.0)
    near, far = 0.5, 500.0
    projection = np.zeros((4, 4))
    projection[0, 0] = f / aspect
    projection[1, 1] = f
    projection[2, 2] = (far + near) / (near - far)
    projection[2, 3] = -1.0
    projection[3, 2] = 2 * far * near / (near - far)
    return view, projection, viewport


class _Event(MouseEvent):
    """A real mouse event with a camera on it, so the ray the gizmo works
    from is the engine's own unprojection rather than a second copy of it."""

    def __init__(self, x, y, paths=(), button=0, modifiers=(0, 0, 0)):
        view, projection, viewport = _matrices()
        self.modelViewMatrix = view
        self.projectionMatrix = projection
        self.viewport = viewport
        self.pickPoint = (x, y)
        self.viewCoordinate = ()
        self.worldCoordinate = ()
        self.button = button
        self._modifiers = modifiers
        self.setObjectPaths(list(paths))

    def getModifiers(self):
        return self._modifiers


def _pixel_of(point, event=None):
    """The window pixel a world point is drawn at, by the test camera."""
    view, projection, viewport = _matrices()
    clip = np.dot(np.append(np.asarray(point, 'd'), 1.0),
                  np.dot(view, projection))
    ndc = clip[:3] / clip[3]
    return (viewport[0] + (ndc[0] + 1.0) * viewport[2] / 2.0,
            viewport[1] + (ndc[1] + 1.0) * viewport[3] / 2.0)


DOWN = (0.0, -1.0, 0.0)


class TestAxisParameter:
    """How far along an axis the pointer's ray comes closest to it."""

    def test_ray_crossing_the_axis_answers_where_it_crosses(self):
        assert axis_parameter((3.0, 10.0, 0.0), DOWN,
                              (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)) == \
            pytest.approx(3.0)

    def test_the_parameter_is_in_units_of_the_axis_vector(self):
        """A half-length axis vector answers twice the number of them.

        This is what carries a drag through a scaled transform: hand it the
        axis as the outer transform draws it and the answer comes back in the
        units the point being dragged is written in.
        """
        assert axis_parameter((3.0, 10.0, 0.0), DOWN,
                              (0.0, 0.0, 0.0), (0.5, 0.0, 0.0)) == \
            pytest.approx(6.0)

    def test_an_anchor_away_from_the_origin_is_measured_from(self):
        assert axis_parameter((3.0, 10.0, 0.0), DOWN,
                              (1.0, 0.0, 0.0), (1.0, 0.0, 0.0)) == \
            pytest.approx(2.0)

    def test_a_ray_beside_the_axis_answers_the_nearest_point_on_it(self):
        """Off-axis distance changes nothing: only the travel along it counts."""
        assert axis_parameter((4.0, 10.0, 7.0), DOWN,
                              (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)) == \
            pytest.approx(4.0)

    def test_a_ray_along_the_axis_has_no_answer(self):
        """Every point of the axis is equally near, so there is no one place
        the pointer means."""
        assert axis_parameter((0.0, 5.0, 0.0), (1.0, 0.0, 0.0),
                              (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)) is None

    def test_a_zero_length_axis_has_no_answer(self):
        assert axis_parameter((0.0, 5.0, 0.0), DOWN,
                              (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)) is None


class TestArms:
    """The three arms, and recognising the one the pick hit."""

    def test_a_new_gizmo_draws_nothing(self):
        gizmo = TranslationGizmo()
        assert not gizmo.attached
        assert list(gizmo.node.children) == []

    def test_attaching_puts_the_arms_at_the_point(self):
        gizmo = TranslationGizmo()
        gizmo.attach((1.0, 2.0, 3.0))
        assert gizmo.attached
        assert np.allclose(gizmo.position, (1.0, 2.0, 3.0))
        assert np.allclose(gizmo.node.translation, (1.0, 2.0, 3.0))
        assert len(gizmo.node.children) == 3

    def test_detaching_leaves_nothing_to_draw_or_pick(self):
        gizmo = TranslationGizmo()
        gizmo.attach((1.0, 2.0, 3.0))
        gizmo.detach()
        assert not gizmo.attached
        assert list(gizmo.node.children) == []

    def test_a_path_through_an_arm_names_its_axis(self):
        gizmo = TranslationGizmo()
        gizmo.attach((0.0, 0.0, 0.0))
        for axis in range(3):
            path = NodePath([gizmo.node, gizmo.arms[axis]])
            assert gizmo.axis_for([path]) == axis

    def test_a_path_through_something_else_names_no_axis(self):
        gizmo = TranslationGizmo()
        gizmo.attach((0.0, 0.0, 0.0))
        assert gizmo.axis_for([NodePath([Transform()])]) is None
        assert gizmo.axis_for([]) is None


class TestDragging:
    """A grabbed arm, and where the pointer takes the point."""

    def _grabbed(self, axis=0, at=(0.0, 0.0, 0.0), origin=(2.0, 10.0, 0.0)):
        gizmo = TranslationGizmo()
        gizmo.attach(at)
        assert gizmo.begin(axis, origin, DOWN)
        return gizmo

    def test_grabbing_moves_nothing_by_itself(self):
        """The point stays where it was until the pointer travels: a handle
        that jumped to the cursor on the press would lose the offset the
        designer grabbed it by."""
        gizmo = self._grabbed()
        assert np.allclose(gizmo.position, (0.0, 0.0, 0.0))
        assert gizmo.dragging == 0

    def test_the_point_travels_as_far_as_the_pointer_did(self):
        gizmo = self._grabbed()
        assert np.allclose(gizmo.drag_to((5.0, 10.0, 0.0), DOWN),
                           (3.0, 0.0, 0.0))
        assert np.allclose(gizmo.node.translation, (3.0, 0.0, 0.0))

    def test_the_drag_is_held_to_the_grabbed_axis(self):
        """The pointer wandering off the axis moves the point along it only."""
        gizmo = self._grabbed()
        assert np.allclose(gizmo.drag_to((5.0, 10.0, 8.0), DOWN),
                           (3.0, 0.0, 0.0))

    def test_each_axis_moves_its_own_component(self):
        gizmo = TranslationGizmo()
        gizmo.attach((0.0, 0.0, 0.0))
        gizmo.begin(2, (0.0, 10.0, 2.0), DOWN)
        assert np.allclose(gizmo.drag_to((0.0, 10.0, 5.0), DOWN),
                           (0.0, 0.0, 3.0))

    def test_a_ray_along_the_arm_leaves_the_point_alone(self):
        """Edge-on to the arm there is no travel to read, so the point holds
        its ground rather than leaping to whatever the arithmetic produced."""
        gizmo = self._grabbed()
        assert gizmo.drag_to((0.0, 5.0, 0.0), (1.0, 0.0, 0.0)) is None
        assert np.allclose(gizmo.position, (0.0, 0.0, 0.0))

    def test_dragging_without_a_grab_does_nothing(self):
        gizmo = TranslationGizmo()
        gizmo.attach((0.0, 0.0, 0.0))
        assert gizmo.drag_to((5.0, 10.0, 0.0), DOWN) is None

    def test_grabbing_an_unattached_gizmo_is_refused(self):
        gizmo = TranslationGizmo()
        assert not gizmo.begin(0, (2.0, 10.0, 0.0), DOWN)

    def test_cancel_puts_the_point_back_where_the_drag_began(self):
        gizmo = self._grabbed(at=(1.0, 1.0, 1.0), origin=(3.0, 10.0, 0.0))
        gizmo.drag_to((9.0, 10.0, 0.0), DOWN)
        assert np.allclose(gizmo.cancel(), (1.0, 1.0, 1.0))
        assert gizmo.dragging is None

    def test_release_keeps_where_the_drag_left_it(self):
        gizmo = self._grabbed()
        gizmo.drag_to((5.0, 10.0, 0.0), DOWN)
        gizmo.release()
        assert gizmo.dragging is None
        assert np.allclose(gizmo.position, (3.0, 0.0, 0.0))

    def test_the_grabbed_arm_is_lit_while_it_is_held(self):
        gizmo = TranslationGizmo()
        gizmo.attach((0.0, 0.0, 0.0))
        dim = [tuple(material.emissiveColor) for material in gizmo.materials]
        gizmo.begin(0, (2.0, 10.0, 0.0), DOWN)
        assert tuple(gizmo.materials[0].emissiveColor) != dim[0]
        assert [tuple(material.emissiveColor)
                for material in gizmo.materials[1:]] == dim[1:]
        gizmo.release()
        assert [tuple(material.emissiveColor)
                for material in gizmo.materials] == dim


class TestOuterTransform:
    """A gizmo standing inside a transformed group works in that group's
    units, because that is where the thing it is moving is written."""

    def test_a_scaled_group_moves_the_point_in_its_own_units(self):
        gizmo = TranslationGizmo()
        gizmo.attach((0.0, 0.0, 0.0))
        matrix = np.identity(4)
        matrix[0, 0] = matrix[1, 1] = matrix[2, 2] = 2.0
        gizmo.begin(0, (4.0, 10.0, 0.0), DOWN, matrix=matrix)
        # The pointer is over root x=8, which is local x=4.
        assert np.allclose(gizmo.drag_to((8.0, 10.0, 0.0), DOWN),
                           (2.0, 0.0, 0.0))

    def test_the_matrix_is_taken_from_the_path_the_arm_was_picked_through(self):
        gizmo = TranslationGizmo()
        outer = Transform(scale=(2.0, 2.0, 2.0), children=[gizmo.node])
        graph = sceneGraph(children=[outer])
        gizmo.attach((0.0, 0.0, 0.0))
        path = NodePath([graph, outer, gizmo.node, gizmo.arms[0]])
        assert np.allclose(gizmo.outer_matrix(path),
                           [[2, 0, 0, 0], [0, 2, 0, 0], [0, 0, 2, 0],
                            [0, 0, 0, 1]])


class TestFromEvents:
    """The pick's own events, end to end: press, drag, release."""

    def _scene(self):
        gizmo = TranslationGizmo(size=2.0)
        graph = sceneGraph(children=[gizmo.node])
        gizmo.attach((0.0, 0.0, 0.0))
        return gizmo, graph

    def test_a_press_on_an_arm_takes_the_drag(self):
        gizmo, graph = self._scene()
        path = NodePath([graph, gizmo.node, gizmo.arms[0]])
        x, y = _pixel_of((1.0, 0.0, 0.0))
        assert gizmo.press(_Event(x, y, paths=[path])) == 0
        assert gizmo.dragging == 0

    def test_a_press_on_nothing_leaves_the_drag_alone(self):
        gizmo, graph = self._scene()
        x, y = _pixel_of((1.0, 0.0, 0.0))
        assert gizmo.press(_Event(x, y, paths=[])) is None
        assert gizmo.dragging is None

    def test_dragging_follows_the_pointer_along_the_arm(self):
        gizmo, graph = self._scene()
        path = NodePath([graph, gizmo.node, gizmo.arms[0]])
        start = _pixel_of((1.0, 0.0, 0.0))
        gizmo.press(_Event(start[0], start[1], paths=[path]))
        end = _pixel_of((4.0, 0.0, 0.0))
        moved = gizmo.drag(_Event(end[0], end[1]))
        assert moved is not None
        assert moved[0] == pytest.approx(3.0, abs=1e-6)
        assert np.allclose(moved[1:], (0.0, 0.0), atol=1e-6)

    def test_dragging_without_a_press_answers_nothing(self):
        gizmo, graph = self._scene()
        x, y = _pixel_of((4.0, 0.0, 0.0))
        assert gizmo.drag(_Event(x, y)) is None


def test_the_axes_are_the_three_unit_vectors():
    assert np.allclose(AXES, np.identity(3))
