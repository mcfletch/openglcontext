"""What an examine drag orbits, and how fast.

Right-drag orbits the view about a point, and which point that is decides
whether the interaction is useful or unusable. Clicking *on* something gives the
best answer -- the place you touched -- but a click on empty sky, or a context
whose picking gave nothing back, has to fall back to something.

It fell back to a point **ten units in front of the camera**, a constant with no
relation to what is being looked at. A model framed four units away then orbits
about a pivot six units behind itself, and a small drag swings the camera right
around it; a model a kilometre across pivots about a point inside its own
surface. Both are wild for the same reason: the pivot has nothing to do with the
thing on screen.

So the fallback is the scene's own bounding sphere.
"""
import numpy as np
import pytest

from OpenGLContext.context import Context


class _Platform:
    def __init__(self, position=(0.0, 0.0, 10.0)):
        self.position = np.array(position, dtype='d')

    class _Quaternion:
        """Identity: the camera looks down -Z."""

        def __mul__(self, vector):
            return np.array(vector[:3], dtype='d')

    quaternion = _Quaternion()


class _Event:
    """A click that picked nothing, which is the case that matters."""

    def unproject(self):
        raise ValueError('nothing under the cursor')


class _Picked(_Event):
    def __init__(self, point):
        self.point = point

    def unproject(self):
        return self.point


class _Context:
    """The little of a context the pivot needs."""

    examineCenter = Context.examineCenter
    # Wrapped: taken bare it would become an instance method here.
    _withinScene = staticmethod(Context._withinScene)

    def __init__(self, bounds=((0.0, 0.0, 0.0), 2.0), position=(0.0, 0.0, 10.0)):
        self._bounds = bounds
        self._platform = _Platform(position)

    def getViewPlatform(self):
        return self._platform

    def sceneBounds(self):
        return self._bounds


class TestWhatWasClicked:
    def test_the_point_under_the_cursor_wins(self):
        """Examining what you touched is the whole gesture.

        Within reach of the scene: a bounding sphere of radius two, and a point
        a unit and a half from its centre is plainly on the thing.
        """
        held = _Context(bounds=((0.0, 0.0, 0.0), 2.0))
        assert list(held.examineCenter(_Picked((1.0, 1.0, 0.5)))[:3]) == [1.0, 1.0, 0.5]


class TestClickingTheBackground:
    """Unprojecting a click that hit nothing gives the **far plane**.

    A depth of 1.0 unprojects to a real, usable-looking world point that is
    simply where the frustum ends -- measured at 127 units out for a model three
    units across. Orbiting that is orbiting nothing, and it is what a click
    anywhere off the model used to do.

    So the picked point is trusted only where it lies within reach of the scene
    itself.
    """

    def test_a_point_out_at_the_far_plane_is_refused(self):
        held = _Context(bounds=((0.0, 0.0, 0.0), 3.0), position=(0.0, 0.0, 10.0))
        centre = held.examineCenter(_Picked((53.8, 42.1, 114.3)))
        assert np.allclose(centre[:3], [0.0, 0.0, 0.0]), 'orbited the sky'

    def test_a_point_on_the_model_is_kept(self):
        held = _Context(bounds=((0.0, 0.0, 0.0), 3.0), position=(0.0, 0.0, 10.0))
        centre = held.examineCenter(_Picked((1.0, 0.5, 2.0)))
        assert np.allclose(centre[:3], [1.0, 0.5, 2.0])

    def test_a_point_just_outside_the_sphere_is_still_kept(self):
        """A bounding sphere is generous; its surface is not a hard edge."""
        held = _Context(bounds=((0.0, 0.0, 0.0), 3.0), position=(0.0, 0.0, 10.0))
        centre = held.examineCenter(_Picked((3.6, 0.0, 0.0)))
        assert np.allclose(centre[:3], [3.6, 0.0, 0.0])

    def test_with_no_bounds_any_picked_point_is_taken(self):
        """Nothing to judge it against, and a pivot is still needed."""
        held = _Context(bounds=None)
        assert np.allclose(
            held.examineCenter(_Picked((99.0, 0.0, 0.0)))[:3], [99.0, 0.0, 0.0])


class TestFallingBackToTheModel:
    def test_it_orbits_the_middle_of_the_scene(self):
        held = _Context(bounds=((0.0, 1.0, 0.0), 2.0))
        assert np.allclose(held.examineCenter(_Event())[:3], [0.0, 1.0, 0.0])

    def test_a_model_far_from_the_origin_is_still_the_pivot(self):
        held = _Context(bounds=((50.0, 0.0, -20.0), 3.0), position=(50.0, 0.0, 0.0))
        assert np.allclose(held.examineCenter(_Event())[:3], [50.0, 0.0, -20.0])

    def test_the_pivot_does_not_depend_on_the_scene_being_small(self):
        """A kilometre-wide model pivots about itself, not ten units ahead."""
        held = _Context(bounds=((0.0, 0.0, 0.0), 500.0), position=(0.0, 0.0, 1200.0))
        assert np.allclose(held.examineCenter(_Event())[:3], [0.0, 0.0, 0.0])


class TestStandingInsideTheScene:
    """A building you are walking through must not swing about its far side."""

    def test_the_pivot_is_ahead_of_you_not_across_the_room(self):
        held = _Context(bounds=((0.0, 0.0, 0.0), 40.0), position=(0.0, 0.0, 0.0))
        centre = np.asarray(held.examineCenter(_Event())[:3], dtype='d')
        assert not np.allclose(centre, [0.0, 0.0, 0.0]), 'pivoting on the camera'
        assert np.linalg.norm(centre) < 40.0, 'pivot is outside the room'

    def test_it_is_in_front_of_the_camera(self):
        held = _Context(bounds=((0.0, 0.0, 0.0), 40.0), position=(0.0, 0.0, 0.0))
        centre = np.asarray(held.examineCenter(_Event())[:3], dtype='d')
        assert centre[2] < 0.0, 'the camera looks down -Z'


class TestWithNothingToGoOn:
    def test_an_empty_scene_still_gives_a_pivot(self):
        """A viewer with nothing loaded must not raise on a right-drag."""
        held = _Context(bounds=None)
        centre = held.examineCenter(_Event())
        assert centre is not None
        assert len(centre) >= 3

    def test_a_degenerate_bounding_sphere_does_not_divide_by_itself(self):
        held = _Context(bounds=((0.0, 0.0, 0.0), 0.0), position=(0.0, 0.0, 0.0))
        assert held.examineCenter(_Event()) is not None


class TestTheSceneBoundsItself:
    def test_a_context_reports_the_bounds_of_its_scenegraph(self):
        from OpenGLContext.scenegraph.box import Box
        from OpenGLContext.scenegraph.scenegraph import SceneGraph
        from OpenGLContext.scenegraph.shape import Shape
        from OpenGLContext.scenegraph.transform import Transform

        class _Real:
            sceneBounds = Context.sceneBounds

            def getSceneGraph(self):
                return SceneGraph(children=[
                    Transform(translation=(4.0, 0.0, 0.0),
                              children=[Shape(geometry=Box(size=(2, 2, 2)))]),
                ])

        centre, radius = _Real().sceneBounds()
        assert np.allclose(centre, [4.0, 0.0, 0.0])
        assert radius == pytest.approx(np.sqrt(3.0), abs=0.01)

    def test_a_context_with_no_scenegraph_reports_nothing(self):
        class _Bare:
            sceneBounds = Context.sceneBounds

            def getSceneGraph(self):
                return None

        assert _Bare().sceneBounds() is None


class TestHowFarADragTurns:
    """A drag to the edge of the window turned the camera a **full circle**.

    The trackball measures a drag as a fraction of the way from where it started
    to the edge of the window, and multiplied that by its own default of 2*pi.
    So half a window put you on the far side of the model and there was no way to
    look at anything: the pivot being right is not enough if a nudge spins it.
    """

    def _trackball(self, width=800, height=600, start=(400, 300)):
        from OpenGLContext.move.examinemanager import ExamineManager
        from OpenGLContext.quaternion import fromXYZR
        facing = fromXYZR(0, 1, 0, 0.0)

        class _Platform:
            # Named on the outside: an attribute called ``quaternion`` would
            # shadow the module while the class body is being evaluated.
            # Homogeneous, as a real ViewPlatform's is.
            position = np.array([0.0, 0.0, 10.0, 1.0], dtype='d')
            quaternion = facing

        class _Event:
            def getPickPoint(self):
                return start

        made = ExamineManager.__new__(ExamineManager)
        made.OnBuildTrackball(_Platform(), (0.0, 0.0, 0.0), _Event(),
                              width, height)
        return made.trackball

    def test_a_drag_to_the_edge_is_half_a_turn_not_a_whole_one(self):
        from OpenGLContext.move import examinemanager
        assert examinemanager.EXAMINE_DRAG_ANGLE == pytest.approx(np.pi)
        assert self._trackball().dragAngle == pytest.approx(np.pi)

    def test_the_far_side_of_the_model_takes_the_whole_window(self):
        """Not a third of it."""
        trackball = self._trackball()
        _position, turned = trackball.update(800, 300)      # centre to right edge
        original = trackball.originalQuaternion
        swing = 2.0 * np.arccos(min(1.0, abs(float(
            np.dot(np.asarray(list(original), 'd'), np.asarray(list(turned), 'd'))))))
        assert np.degrees(swing) == pytest.approx(180.0, abs=5.0)

    def test_a_small_drag_is_a_small_turn(self):
        """A tenth of the way to the edge should not be a quarter turn."""
        trackball = self._trackball()
        _position, turned = trackball.update(440, 300)      # 40px of 400 available
        original = trackball.originalQuaternion
        swing = 2.0 * np.arccos(min(1.0, abs(float(
            np.dot(np.asarray(list(original), 'd'), np.asarray(list(turned), 'd'))))))
        assert np.degrees(swing) < 25.0, np.degrees(swing)

    def test_the_distance_to_the_pivot_is_unchanged(self):
        """It is an orbit: the camera goes round the thing, not towards it."""
        trackball = self._trackball()
        before = np.linalg.norm(trackball.originalPosition[:3])
        moved, _turned = trackball.update(600, 400)
        assert np.linalg.norm(np.asarray(moved, 'd')[:3]) == pytest.approx(before,
                                                                          abs=1e-6)
