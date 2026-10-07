"""A viewpoint's centerOfRotation, viewAll and retainUserOffsets.

``centerOfRotation``, where the document sets it, is what the examine
gestures turn about when the pointer is on nothing. ``viewAll`` places the
camera, looking the viewpoint's way, where the whole scene is in view.
``retainUserOffsets`` returns to a viewpoint bound again where the user had
moved to from it, rather than to where it stands.
"""
import numpy as np
import pytest

from OpenGLContext import quaternion
from OpenGLContext.context import Context
from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.passes import viewpointbinding
from OpenGLContext.scenegraph.basenodes import NavigationInfo, Viewpoint, sceneGraph


class _Path(tuple):
    def transformMatrix(self):
        return np.identity(4)

    def quaternion(self):
        return quaternion.fromXYZR(0, 1, 0, 0)


class Viewing:
    def __init__(self, scene, bounds=None):
        self.scene = scene
        self.platform = ViewPlatform()
        self.bounds = bounds

    def getSceneGraph(self):
        return self.scene

    def getViewPlatform(self):
        return self.platform

    def sceneBounds(self):
        return self.bounds


def scene(*views):
    jump = NavigationInfo(transitionType=['TELEPORT'])
    graph = sceneGraph(children=[jump] + list(views))
    jump.set_bind = True
    graph.viewpointPaths = tuple(_Path((graph, view)) for view in views)
    return graph


def test_view_all_frames_the_scene_along_the_viewpoints_direction():
    view = Viewpoint(position=(0, 0, 1), viewAll=True, fieldOfView=np.pi / 2)
    context = Viewing(scene(view), bounds=((10.0, 0.0, 0.0), 2.0))
    viewpointbinding.bind_scene_viewpoint(context)
    position = context.platform.position[:3]
    assert position[0] == pytest.approx(10.0) and position[1] == pytest.approx(0.0)
    assert position[2] == pytest.approx(2.0 / np.sin(np.pi / 4))


def test_a_viewpoint_bound_again_returns_to_the_users_offset():
    first = Viewpoint(position=(0, 0, 0), retainUserOffsets=True)
    second = Viewpoint(position=(50, 0, 0))
    context = Viewing(scene(first, second))
    viewpointbinding.bind_scene_viewpoint(context)
    context.platform.setPosition((1, 2, 3))
    second.set_bind = True
    viewpointbinding.bind_scene_viewpoint(context)
    assert context.platform.position[0] == pytest.approx(50.0)
    first.set_bind = True
    viewpointbinding.bind_scene_viewpoint(context)
    assert tuple(context.platform.position[:3]) == pytest.approx((1, 2, 3))


def test_without_retain_a_viewpoint_bound_again_is_where_it_stands():
    first, second = Viewpoint(position=(0, 0, 0)), Viewpoint(position=(50, 0, 0))
    context = Viewing(scene(first, second))
    viewpointbinding.bind_scene_viewpoint(context)
    context.platform.setPosition((1, 2, 3))
    second.set_bind = True
    viewpointbinding.bind_scene_viewpoint(context)
    first.set_bind = True
    viewpointbinding.bind_scene_viewpoint(context)
    assert tuple(context.platform.position[:3]) == pytest.approx((0, 0, 0))


class Examining(Viewing):
    _withinScene = Context._withinScene
    examineCenter = Context.examineCenter


class NothingPicked:
    def unproject(self):
        raise ValueError('nothing under the pointer')


def test_an_authored_centre_of_rotation_is_the_pivot_with_nothing_picked():
    view = Viewpoint(position=(0, 0, 10), centerOfRotation=(3, 4, 5))
    graph = scene(view)
    graph.boundViewpoint = view
    context = Examining(graph, bounds=((0.0, 0.0, 0.0), 1.0))
    context.platform.setPosition((0, 0, 10))
    assert tuple(context.examineCenter(NothingPicked())[:3]) == pytest.approx((3, 4, 5))


def test_without_one_the_pivot_is_the_scenes_centre():
    view = Viewpoint(position=(0, 0, 10))
    graph = scene(view)
    graph.boundViewpoint = view
    context = Examining(graph, bounds=((1.0, 2.0, 3.0), 1.0))
    context.platform.setPosition((0, 0, 10))
    assert tuple(context.examineCenter(NothingPicked())[:3]) == pytest.approx((1, 2, 3))
