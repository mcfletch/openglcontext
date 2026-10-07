"""Moving between bound viewpoints as the bound NavigationInfo's transition says.

The first viewpoint a scene binds is jumped to. Binding another moves the
camera to it over ``transitionTime`` -- straight for ``LINEAR``, easing in and
out for ``ANIMATE``, at once for ``TELEPORT`` -- and the NavigationInfo sends
``transitionComplete`` when it arrives (``viewpointbinding.ViewpointTransition``).
"""
import numpy as np
import pytest

from OpenGLContext import quaternion
from OpenGLContext.events import systemtime
from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.passes import viewpointbinding
from OpenGLContext.passes.viewpointbinding import ViewpointTransition
from OpenGLContext.scenegraph.basenodes import NavigationInfo, Viewpoint, sceneGraph


def test_a_linear_transition_is_halfway_at_half_its_time():
    move = ViewpointTransition((0, 0, 0), quaternion.fromXYZR(0, 1, 0, 0),
                               (10, 0, 0), quaternion.fromXYZR(0, 1, 0, 0),
                               start=5.0, duration=2.0, kind='LINEAR')
    position, _turn, done = move.at(6.0)
    assert position == pytest.approx((5, 0, 0))
    assert not done
    position, _turn, done = move.at(7.5)
    assert position == pytest.approx((10, 0, 0)) and done


def test_an_animated_transition_eases():
    move = ViewpointTransition((0, 0, 0), quaternion.fromXYZR(0, 1, 0, 0),
                               (10, 0, 0), quaternion.fromXYZR(0, 1, 0, 0),
                               start=0.0, duration=1.0, kind='ANIMATE')
    assert move.at(0.5)[0] == pytest.approx((5, 0, 0))
    assert move.at(0.25)[0][0] < 2.5


def test_the_orientation_turns_on_the_way():
    move = ViewpointTransition((0, 0, 0), quaternion.fromXYZR(0, 1, 0, 0),
                               (0, 0, 0), quaternion.fromXYZR(0, 1, 0, np.pi / 2),
                               start=0.0, duration=1.0, kind='LINEAR')
    x, y, z, angle = move.at(0.5)[1].XYZR()
    assert abs(angle) == pytest.approx(np.pi / 4, abs=1e-4)


class Viewing:
    def __init__(self, scene):
        self.scene = scene
        self.platform = ViewPlatform()

    def getSceneGraph(self):
        return self.scene

    def getViewPlatform(self):
        return self.platform


class _Path(tuple):
    def transformMatrix(self):
        return np.identity(4)

    def quaternion(self):
        return quaternion.fromXYZR(0, 1, 0, 0)


def test_rebinding_moves_over_the_transition_and_says_when_it_arrives(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(systemtime, 'systemTime', lambda: now[0])
    first, second = Viewpoint(position=(0, 0, 0)), Viewpoint(position=(10, 0, 0))
    info = NavigationInfo(transitionTime=2.0)
    scene = sceneGraph(children=[info, first, second])
    scene.viewpointPaths = (_Path((scene, first)), _Path((scene, second)))
    info.set_bind = True
    context = Viewing(scene)
    viewpointbinding.bind_scene_viewpoint(context)
    assert tuple(context.platform.position[:3]) == pytest.approx((0, 0, 0))
    second.set_bind = True
    viewpointbinding.bind_scene_viewpoint(context)
    assert tuple(context.platform.position[:3]) == pytest.approx((0, 0, 0))
    now[0] = 101.0
    viewpointbinding.bind_scene_viewpoint(context)
    assert tuple(context.platform.position[:3]) == pytest.approx((5, 0, 0))
    assert 'transitionComplete' not in info.__dict__
    now[0] = 102.5
    viewpointbinding.bind_scene_viewpoint(context)
    assert tuple(context.platform.position[:3]) == pytest.approx((10, 0, 0))
    assert info.transitionComplete is True


def test_with_no_navigation_info_a_rebinding_is_linear_over_a_second(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(systemtime, 'systemTime', lambda: now[0])
    first, second = Viewpoint(position=(0, 0, 0)), Viewpoint(position=(4, 0, 0))
    scene = sceneGraph(children=[first, second])
    scene.viewpointPaths = (_Path((scene, first)), _Path((scene, second)))
    context = Viewing(scene)
    viewpointbinding.bind_scene_viewpoint(context)
    second.set_bind = True
    viewpointbinding.bind_scene_viewpoint(context)
    now[0] = 0.5
    viewpointbinding.bind_scene_viewpoint(context)
    assert tuple(context.platform.position[:3]) == pytest.approx((2, 0, 0))
