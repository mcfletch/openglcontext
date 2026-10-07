"""X3D's ViewpointGroup, and a NavigationInfo's visibilityLimit.

A ViewpointGroup's viewpoints are the scene's as any others are. The
next-viewpoint key passes over those of a group not ``displayed``, and of a
group with a ``size`` the viewer is outside. A bound NavigationInfo's
positive ``visibilityLimit`` is the far clip distance.
"""
import numpy as np
import pytest

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.move import navigationinfo
from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.passes import viewpointbinding
from OpenGLContext.scenegraph import nodepath
from OpenGLContext.scenegraph.basenodes import NavigationInfo, Viewpoint, sceneGraph
from OpenGLContext.scenegraph.viewpointgroup import ViewpointGroup


def test_it_is_the_engines_and_holds_its_viewpoints():
    assert prototypes()['ViewpointGroup'] is ViewpointGroup
    view = Viewpoint()
    assert ViewpointGroup(children=[view]).renderedChildren() == [view]


class Context:
    def __init__(self, graph, position=(0, 0, 0)):
        self.graph = graph
        self.platform = ViewPlatform(position=position)

    def getSceneGraph(self):
        return self.graph

    def getViewPlatform(self):
        return self.platform


def scene(**group):
    first, grouped, last = Viewpoint(), Viewpoint(), Viewpoint()
    holder = ViewpointGroup(children=[grouped], **group)
    graph = sceneGraph(children=[first, holder, last])
    root = nodepath.NodePath([]) + graph
    graph.viewpointPaths = (root + first, root + holder + grouped, root + last)
    return graph, (first, grouped, last)


def cycle(graph, position=(0, 0, 0), steps=3):
    context = Context(graph, position)
    return [viewpointbinding.next_viewpoint(context) for _ in range(steps)]


def test_a_displayed_group_is_cycled_through():
    graph, (first, grouped, last) = scene()
    assert cycle(graph) == [first, grouped, last]


def test_a_group_not_displayed_is_passed_over():
    graph, (first, _grouped, last) = scene(displayed=False)
    assert cycle(graph) == [first, last, first]


def test_a_sized_group_is_cycled_through_from_inside_it():
    graph, (first, grouped, last) = scene(center=(10, 0, 0), size=(4, 4, 4))
    assert cycle(graph, position=(0, 0, 0)) == [first, last, first]
    graph, (first, grouped, last) = scene(center=(10, 0, 0), size=(4, 4, 4))
    assert cycle(graph, position=(11, 0, 0)) == [first, grouped, last]


def test_the_visibility_limit_is_the_far_plane():
    platform = ViewPlatform(far=50000.0)
    navigationinfo.clip(platform, NavigationInfo(visibilityLimit=300.0))
    assert platform.frustum[3] == 300.0
    navigationinfo.clip(platform, NavigationInfo())
    assert platform.frustum[3] == 300.0


def test_the_visibility_limit_keeps_an_orthographic_window():
    platform = ViewPlatform()
    platform.setOrthographic((-1, -1, 1, 1))
    navigationinfo.clip(platform, NavigationInfo(visibilityLimit=20.0))
    assert platform.window == (-1.0, -1.0, 1.0, 1.0)
    assert np.isclose(platform.frustum[3], 20.0)


@pytest.mark.parametrize('near, far, expected', [
    (None, 9.0, (0.3, 9.0)), (0.5, None, (0.5, 50000)), (None, None, (0.3, 50000)),
])
def test_set_clipping_leaves_what_it_is_not_given(near, far, expected):
    platform = ViewPlatform(near=0.3, far=50000)
    platform.setClipping(near, far)
    assert platform.frustum[2:] == pytest.approx(expected)
