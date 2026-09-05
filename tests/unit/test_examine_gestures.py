"""The three examine gestures, from the event to the camera.

Right-drag orbits, middle-drag pans and the wheel dollies -- the arrangement
every 3D viewer has, and the one a user arrives expecting. What the maths does
is `tests/unit/test_orbit.py`; this is the wiring: which button starts which
gesture, what ends one, and what a stray event in the middle of one does.

The stray event mattered: a wheel notch is delivered as the press *and release*
of a button that is never held, and the release read as "a button other than
mine came up", which is the condition that **cancels** an examine and puts the
camera back. Scrolling to back away from a model you had lost, in the middle of
the drag that lost it, therefore undid the drag.
"""
import numpy as np
import pytest

from OpenGLContext import quaternion
from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP
from OpenGLContext.move import examinemanager, movementmanager
from OpenGLContext.move.viewplatform import ViewPlatform


class _Context:
    """The little of a context an examine gesture touches."""

    def __init__(self, centre=(0.0, 0.0, 0.0), size=(800, 600)):
        self.captured = {}
        self.redraws = 0
        self._centre = centre
        self._size = size

    def getViewPort(self):
        return self._size

    def captureEvents(self, name, manager):
        self.captured[name] = manager

    def isCapturingEvents(self, name):
        return self.captured.get(name) is not None

    def triggerRedraw(self, force=0):
        self.redraws += 1

    def examineCenter(self, event):
        return np.array(tuple(self._centre) + (1.0,), dtype='d')


class _Button:
    type = 'mousebutton'

    def __init__(self, button=1, state=1, point=(400, 300)):
        self.button, self.state, self.point = button, state, point

    def getPickPoint(self):
        return self.point


class _Move:
    type = 'mousemove'

    def __init__(self, point):
        self.point = point

    def getPickPoint(self):
        return self.point


def _platform(position=(0.0, 0.0, 10.0)):
    platform = ViewPlatform(position=position, orientation=(0, 1, 0, 0))
    platform.quaternion = examinemanager.orbit.aimAt(position, (0.0, 0.0, 0.0))
    return platform


def _started(gesture=examinemanager.ROTATE, context=None, platform=None,
             point=(400, 300)):
    context = context or _Context()
    platform = platform or _platform()
    made = examinemanager.ExamineManager(
        context, platform, context.examineCenter(None),
        _Button(point=point), gesture=gesture)
    return context, platform, made


class TestStartingAGesture:
    def test_a_right_drag_captures_the_mouse(self):
        context, _platform, made = _started()
        assert context.captured['mousemove'] is made
        assert context.captured['mousebutton'] is made

    def test_it_orbits_the_point_it_was_given(self):
        context, _platform, made = _started()
        assert np.allclose(made.orbit.centre[:3], [0.0, 0.0, 0.0])

    def test_the_gesture_is_the_one_asked_for(self):
        _context, _platform, made = _started(gesture=examinemanager.PAN)
        assert made.gesture == examinemanager.PAN

    def test_it_takes_the_field_of_view_from_the_platform(self):
        """Pan has to know how much world one pixel covers."""
        platform = _platform()
        platform.setFrustum(fieldOfView=np.pi / 4.0)
        _context, _platform_, made = _started(platform=platform)
        assert made.orbit.fieldOfView == pytest.approx(np.pi / 4.0)

    def test_a_dolly_cannot_reach_the_near_plane(self):
        platform = _platform()
        platform.setFrustum(near=2.0)
        _context, _platform_, made = _started(platform=platform)
        assert made.orbit.minimumRadius >= 2.0


class TestRotating:
    def test_a_movement_swings_the_camera(self):
        context, platform, made = _started()
        made.ProcessEvent(_Move((500, 300)))
        assert float(platform.position[0]) < 0.0
        assert context.redraws

    def test_the_distance_is_kept(self):
        _context, platform, made = _started()
        made.ProcessEvent(_Move((600, 450)))
        assert float(np.linalg.norm(np.asarray(platform.position, 'd')[:3])) \
            == pytest.approx(10.0)

    def test_the_horizon_stays_level(self):
        _context, platform, made = _started()
        made.ProcessEvent(_Move((600, 450)))
        right = np.asarray(platform.quaternion * np.array([1.0, 0.0, 0.0, 0.0]),
                           dtype='d')[:3]
        assert abs(float(np.dot(right, [0.0, 1.0, 0.0]))) < 1e-6


class TestPanning:
    def test_a_movement_slides_the_camera_across(self):
        _context, platform, made = _started(gesture=examinemanager.PAN)
        made.ProcessEvent(_Move((500, 300)))
        assert float(platform.position[0]) < 0.0

    def test_the_view_does_not_turn(self):
        _context, platform, made = _started(gesture=examinemanager.PAN)
        before = tuple(platform.quaternion)
        made.ProcessEvent(_Move((500, 380)))
        assert np.allclose(np.asarray(tuple(platform.quaternion), 'd'),
                           np.asarray(before, 'd'), atol=1e-9)


class TestTheWheelDuringADrag:
    """The notch that used to cancel the drag."""

    def test_a_notch_does_not_end_the_gesture(self):
        context, _platform, made = _started()
        made.ProcessEvent(_Button(button=WHEEL_UP, state=1))
        made.ProcessEvent(_Button(button=WHEEL_UP, state=0))
        assert context.captured['mousemove'] is made, 'the drag was cancelled'

    def test_a_notch_does_not_move_the_camera_back(self):
        _context, platform, made = _started()
        made.ProcessEvent(_Move((550, 300)))
        turned = np.asarray(platform.position, 'd')[:3].copy()
        made.ProcessEvent(_Button(button=WHEEL_UP, state=1))
        made.ProcessEvent(_Button(button=WHEEL_UP, state=0))
        assert np.linalg.norm(np.asarray(platform.position, 'd')[:3]) < \
            np.linalg.norm(turned) + 1e-9
        # ... and it is still on the same side of the model, not back at start
        assert float(platform.position[0]) < 0.0

    def test_scrolling_up_moves_closer(self):
        _context, platform, made = _started()
        made.ProcessEvent(_Button(button=WHEEL_UP, state=1))
        assert float(np.linalg.norm(np.asarray(platform.position, 'd')[:3])) < 10.0

    def test_scrolling_down_moves_away(self):
        _context, platform, made = _started()
        made.ProcessEvent(_Button(button=WHEEL_DOWN, state=1))
        assert float(np.linalg.norm(np.asarray(platform.position, 'd')[:3])) > 10.0

    def test_the_drag_continues_at_the_new_distance(self):
        _context, platform, made = _started()
        made.ProcessEvent(_Button(button=WHEEL_UP, state=1))
        closer = float(np.linalg.norm(np.asarray(platform.position, 'd')[:3]))
        made.ProcessEvent(_Move((500, 300)))
        assert float(np.linalg.norm(np.asarray(platform.position, 'd')[:3])) \
            == pytest.approx(closer)


class TestEndingAGesture:
    def test_letting_go_of_the_button_ends_it(self):
        context, _platform, made = _started()
        made.ProcessEvent(_Button(button=1, state=0))
        assert context.captured['mousemove'] is None
        assert context.captured['mousebutton'] is None

    def test_it_keeps_where_the_drag_left_the_camera(self):
        _context, platform, made = _started()
        made.ProcessEvent(_Move((500, 300)))
        moved = np.asarray(platform.position, 'd')[:3].copy()
        made.ProcessEvent(_Button(button=1, state=0))
        assert np.allclose(np.asarray(platform.position, 'd')[:3], moved)

    def test_another_button_coming_up_cancels_it(self):
        context, platform, made = _started()
        made.ProcessEvent(_Move((500, 300)))
        made.ProcessEvent(_Button(button=0, state=0))
        assert context.captured['mousemove'] is None
        assert np.allclose(np.asarray(platform.position, 'd')[:3],
                           [0.0, 0.0, 10.0])

    def test_a_cancel_puts_the_orientation_back_too(self):
        _context, platform, made = _started()
        before = tuple(platform.quaternion)
        made.ProcessEvent(_Move((700, 500)))
        made.ProcessEvent(_Button(button=0, state=0))
        assert np.allclose(np.asarray(tuple(platform.quaternion), 'd'),
                           np.asarray(before, 'd'))


class TestTheBindings:
    """Which button does what, as the default navigation declares it."""

    def _binding(self, key):
        from OpenGLContext.move.direct import Direct
        return Direct.commandBindings[key]

    def test_the_right_button_orbits(self):
        assert self._binding('examine')['button'] == 1

    def test_the_middle_button_pans(self):
        binding = self._binding('pan')
        assert binding['button'] == 2
        assert binding['eventType'] == 'mousebutton'

    def test_the_wheel_dollies(self):
        assert self._binding('zoomin')['button'] == WHEEL_UP
        assert self._binding('zoomout')['button'] == WHEEL_DOWN

    def test_every_command_names_a_method_that_exists(self):
        from OpenGLContext.move.smooth import Smooth
        for _title, _key, function in Smooth.commands:
            assert getattr(Smooth, function, None) is not None, function


class TestTheWheelOutsideADrag:
    """Scrolling with no button held dollies toward what is on screen."""

    def _manager(self, context=None, platform=None):
        manager = movementmanager.MovementManager(platform or _platform())
        manager.context = context or _Context()
        return manager

    def test_scrolling_up_moves_toward_the_scene(self):
        platform = _platform()
        manager = self._manager(platform=platform)
        manager.zoomIn(_Button(button=WHEEL_UP))
        assert float(np.linalg.norm(np.asarray(platform.position, 'd')[:3])) < 10.0

    def test_scrolling_down_moves_away(self):
        platform = _platform()
        manager = self._manager(platform=platform)
        manager.zoomOut(_Button(button=WHEEL_DOWN))
        assert float(np.linalg.norm(np.asarray(platform.position, 'd')[:3])) > 10.0

    def test_the_view_does_not_turn(self):
        platform = _platform()
        before = tuple(platform.quaternion)
        self._manager(platform=platform).zoomIn(_Button(button=WHEEL_UP))
        assert np.allclose(np.asarray(tuple(platform.quaternion), 'd'),
                           np.asarray(before, 'd'), atol=1e-9)

    def test_it_redraws(self):
        context = _Context()
        self._manager(context=context).zoomIn(_Button(button=WHEEL_UP))
        assert context.redraws

    def test_a_notch_in_and_a_notch_out_returns_to_the_same_distance(self):
        platform = _platform()
        manager = self._manager(platform=platform)
        manager.zoomIn(_Button(button=WHEEL_UP))
        manager.zoomOut(_Button(button=WHEEL_DOWN))
        assert float(np.linalg.norm(np.asarray(platform.position, 'd')[:3])) \
            == pytest.approx(10.0)

    def test_it_cannot_be_scrolled_through_the_thing_it_is_looking_at(self):
        platform = _platform()
        manager = self._manager(platform=platform)
        for _ in range(200):
            manager.zoomIn(_Button(button=WHEEL_UP))
        assert float(np.linalg.norm(np.asarray(platform.position, 'd')[:3])) > 0.0


class TestStartingFromTheBinding:
    """Through the callback the binding names, which is how a real click gets
    here."""

    def _manager(self, context, platform):
        manager = movementmanager.MovementManager(platform)
        manager.context = context
        return manager

    def test_the_examine_binding_starts_a_rotate(self):
        context, platform = _Context(), _platform()
        gesture = self._manager(context, platform).startExamineMode(_Button())
        assert gesture.gesture == examinemanager.ROTATE
        assert context.captured['mousemove'] is gesture

    def test_the_pan_binding_starts_a_pan(self):
        context, platform = _Context(), _platform()
        gesture = self._manager(context, platform).startPanMode(
            _Button(button=2))
        assert gesture.gesture == examinemanager.PAN

    def test_it_orbits_the_pivot_the_context_chose(self):
        context = _Context(centre=(3.0, 0.0, -1.0))
        gesture = self._manager(context, _platform()).startExamineMode(_Button())
        assert np.allclose(gesture.orbit.centre[:3], [3.0, 0.0, -1.0])


class TestABindingWithNoMethodIsReported:
    """A movement manager declaring a command it does not implement should say
    so rather than silently offer a control that does nothing."""

    def test_it_logs_a_warning(self, caplog):
        class _Missing(movementmanager.MovementManager):
            commands = [('Nowhere', 'nowhere', 'noSuchMethod')]
            commandBindings = dict(
                nowhere=dict(eventType='mousebutton', button=0, state=1,
                             modifiers=(0, 0, 0)))

        class _Host(_Context):
            def addEventHandler(self, **named):
                pass

        with caplog.at_level('WARNING'):
            _Missing(_platform()).bind(_Host())
        assert 'noSuchMethod' in caplog.text


class TestTheOrbitIsTheCustomisationPoint:
    def test_a_subclass_can_supply_its_own(self):
        marker = object()

        class _Mine(examinemanager.ExamineManager):
            def OnBuildOrbit(self, platform, centre, event, width, height):
                self.orbit = marker

        context = _Context()
        made = _Mine(context, _platform(), (0.0, 0.0, 0.0), _Button())
        assert made.orbit is marker

    def test_a_notch_over_an_orbit_that_cannot_dolly_is_ignored(self):
        """`rotate` and `cancel` are all the manager requires; a wheel notch
        must not become an error in the middle of somebody's drag."""
        class _TurnOnly:
            centre = np.zeros((4,), dtype='d')

            def rotate(self, x, y):
                return np.array([0.0, 0.0, 10.0, 1.0], 'd'), None

            def cancel(self):
                return self.rotate(0, 0)

        class _Mine(examinemanager.ExamineManager):
            def OnBuildOrbit(self, platform, centre, event, width, height):
                self.orbit = _TurnOnly()

        made = _Mine(_Context(), _platform(), (0.0, 0.0, 0.0), _Button())
        made.ProcessEvent(_Button(button=WHEEL_UP, state=1))

    def test_the_arcball_still_fits_the_slot(self):
        """`Trackball` answers `rotate` and `cancel`, which is the whole of what
        the manager asks of an orbit."""
        from OpenGLContext.move.trackball import Trackball

        class _Arcball(examinemanager.ExamineManager):
            def OnBuildOrbit(self, platform, centre, event, width, height):
                x, y = event.getPickPoint()
                self.orbit = Trackball(platform.position, platform.quaternion,
                                       centre, x, y, width, height)

        context = _Context()
        platform = _platform()
        made = _Arcball(context, platform, (0.0, 0.0, 0.0), _Button())
        made.ProcessEvent(_Move((500, 300)))
        assert not np.allclose(np.asarray(platform.position, 'd')[:3],
                               [0.0, 0.0, 10.0])


class TestTheOrientationSurvivesAsAQuaternion:
    def test_the_platform_is_given_a_quaternion_not_an_array(self):
        _context, platform, made = _started()
        made.ProcessEvent(_Move((500, 300)))
        assert isinstance(platform.quaternion, quaternion.Quaternion)
