"""Binding a viewpoint while an avatar is walked.

The avatar places the camera each frame it is stepped, and a newly bound
viewpoint moves the camera over a transition. While the transition runs the
avatar is held where the transition ends, so the camera has one mover at a
time and rests where the transition left it.
"""
import numpy as np
import pytest

from OpenGLContext.events import systemtime
from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.passes import viewpointbinding
from OpenGLContext.scenegraph.basenodes import NavigationInfo, Viewpoint, sceneGraph

from tests.unit.test_physicswalk import _Host, _quad
from tests.unit.test_viewpoint_transition import _Path

#: A turn about x by this much looks 0.5 radians below the horizon.
LOOKING_DOWN = (1, 0, 0, -0.5)


class _Walker(_Host):
    """A walking host drawn the way the main loop draws one"""

    def __init__(self, scene):
        super().__init__(scene)
        self.platform = ViewPlatform()
        self.marks = []

    def getSceneGraph(self):
        return self.sg

    def mark(self, name, /, **fields):
        self.marks.append((name, fields))

    def frame(self):
        """One pass of the loop: the idle step, then the draw's bind"""
        if self.physicsWalking:
            self.stepPhysics(0.0)
        viewpointbinding.bind_scene_viewpoint(self)
        return self.eye()

    def eye(self):
        return np.array(self.platform.position[:3], 'd')

    def looking(self):
        return np.array(self.platform.forward()[:3], 'd')


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(systemtime, 'systemTime', lambda: now[0])
    return now


def _walking(*viewpoints, info=None):
    """A host walking a floor, its camera at the first of `viewpoints`"""
    children = [_quad()] + ([info] if info is not None else []) + list(viewpoints)
    scene = sceneGraph(children=children)
    scene.viewpointPaths = tuple(_Path((scene, view)) for view in viewpoints)
    if info is not None:
        info.set_bind = True
    host = _Walker(scene)
    host.frame()
    host.setupPhysics()
    assert host.enablePhysics(True)
    host.frame()
    return host


def _views():
    return (Viewpoint(position=(0, 3, 5)),
            Viewpoint(position=(6, 4, -2), orientation=LOOKING_DOWN))


def _seat(host):
    """Where the avatar's eye is"""
    return np.array(host.physicsPlatform.camera_position(), 'd')


def _over(eye, viewpoint):
    """Whether `eye` is above or below where `viewpoint` stands"""
    return eye[0] == pytest.approx(viewpoint.position[0]) \
        and eye[2] == pytest.approx(viewpoint.position[2])


def test_the_camera_leaves_from_where_it_was(clock):
    first, second = _views()
    host = _walking(first, second)
    before, facing = host.eye(), host.looking()
    second.set_bind = True
    assert host.frame() == pytest.approx(before)
    assert host.looking() == pytest.approx(facing)


def test_the_camera_goes_straight_there(clock):
    first, second = _views()
    host = _walking(first, second)
    before = host.eye()
    second.set_bind = True
    host.frame()
    travelled = []
    for step in range(1, 11):
        clock[0] = step / 10.0
        travelled.append(np.linalg.norm(host.frame() - before))
    assert travelled == sorted(travelled)
    assert travelled[4] == pytest.approx(travelled[-1] / 2.0)
    assert _over(host.eye(), second)
    assert host.eye() == pytest.approx(_seat(host))


def test_it_rests_where_it_arrived_looking_the_way_the_viewpoint_looks(clock):
    first, second = _views()
    host = _walking(first, second)
    second.set_bind = True
    host.frame()
    clock[0] = 1.5
    arrived = host.frame()
    facing = host.looking()
    assert facing[1] == pytest.approx(-np.sin(0.5))
    assert not viewpointbinding.in_transition(host)
    for _ in range(3):
        assert host.frame() == pytest.approx(arrived)
        assert host.looking() == pytest.approx(facing)
    assert _seat(host) == pytest.approx(arrived)


def test_a_viewpoint_the_avatar_does_not_stand_at_is_reached_where_it_does(clock):
    """The transition ends at the avatar's eye, so arriving is not a jump"""
    first, second = _views()
    host = _walking(first, second)
    second.set_bind = True
    host.frame()
    clock[0] = 0.999
    nearly = host.frame()
    clock[0] = 1.5
    arrived = host.frame()
    assert arrived[1] != pytest.approx(second.position[1])
    assert arrived == pytest.approx(_seat(host))
    assert nearly == pytest.approx(arrived, abs=0.01)
    assert host.frame() == pytest.approx(arrived)


def test_a_teleport_seats_the_avatar_at_once(clock):
    first, second = _views()
    host = _walking(first, second, info=NavigationInfo(transitionType=['TELEPORT']))
    second.set_bind = True
    arrived = host.frame()
    assert _over(arrived, second)
    assert arrived == pytest.approx(_seat(host))
    assert host.frame() == pytest.approx(arrived)
    assert host.looking()[1] == pytest.approx(-np.sin(0.5))


def test_the_first_viewpoint_leaves_the_avatar_where_it_was_spawned(clock):
    first, second = _views()
    host = _walking(first, second)
    assert [name for name, _fields in host.marks] == ['viewpoint-bound']
    assert host.eye() == pytest.approx(host.physicsPlatform.camera_position())


def test_a_bind_and_its_arrival_are_marked(clock):
    first, second = _views()
    second.description = 'steps'
    host = _walking(first, second)
    del host.marks[:]
    start = host.eye()
    second.set_bind = True
    host.frame()
    clock[0] = 2.0
    host.frame()
    (bound, began), (arrived, ended) = host.marks
    assert (bound, arrived) == ('viewpoint-bound', 'viewpoint-arrived')
    assert began['viewpoint'] == ended['viewpoint'] == 'steps'
    assert began['index'] == 1
    assert began['transition'] == 'LINEAR' and began['seconds'] == 1.0
    assert began['start'] == pytest.approx(start)
    assert began['target'] == pytest.approx(_seat(host))
    assert ended['position'] == pytest.approx(_seat(host))


def test_free_flight_is_marked_too(clock):
    first, second = _views()
    scene = sceneGraph(children=[first, second])
    scene.viewpointPaths = (_Path((scene, first)), _Path((scene, second)))
    host = _Walker(scene)
    host.frame()
    second.set_bind = True
    host.frame()
    assert [name for name, _fields in host.marks] == ['viewpoint-bound', 'viewpoint-bound']
    assert host.marks[0][1]['transition'] == 'FIRST'


def test_a_transition_asks_for_its_first_frame(clock):
    """Nothing else draws a still scene, and the transition moves only when drawn"""
    first, second = _views()
    scene = sceneGraph(children=[first, second])
    scene.viewpointPaths = (_Path((scene, first)), _Path((scene, second)))
    host = _Walker(scene)
    host.frame()
    asked = host.redraws
    second.set_bind = True
    host.frame()
    assert host.redraws > asked
