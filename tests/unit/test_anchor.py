"""X3D's Anchor: a group whose geometry, clicked, follows its url.

The engine's Anchor draws its children as a group does, and is reached by the
pointer as the pointing-device sensors are (``scenegraph.x3dpointing``). A
click released over its geometry calls ``context.OnAnchor(anchor, url,
parameter)``; the context's own binds the viewpoint a ``#name`` url names and
leaves any other url to an application that overrides it.
"""
import numpy as np
import pytest

from OpenGLContext.context import ContextCore
from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.scenegraph import nodepath, x3dpointing
from OpenGLContext.scenegraph.anchor import Anchor
from OpenGLContext.scenegraph.basenodes import Box, Shape, Viewpoint, sceneGraph


def test_it_is_the_engines_and_draws_its_children():
    assert prototypes()['Anchor'] is Anchor
    shape = Shape(geometry=Box())
    assert Anchor(children=[shape]).renderedChildren() == [shape]


def anchored(url=('#V',)):
    shape = Shape(geometry=Box())
    anchor = Anchor(children=[shape], url=list(url), parameter=['target=_self'])
    graph = sceneGraph(children=[anchor])
    path = nodepath.NodePath([]) + graph + anchor + shape
    return graph, anchor, path


def test_the_anchor_is_reached_through_its_geometry():
    _graph, anchor, path = anchored()
    sensors, prefix = x3dpointing.sensors_for(path)
    assert sensors == [anchor]
    assert prefix[-1] is anchor


class Clicking:
    """A context that records what its anchors ask of it"""

    def __init__(self):
        self.followed = []

    def observeEvents(self, kind, function, stop=False):
        pass

    def OnAnchor(self, anchor, url, parameter):
        self.followed.append((anchor, url, parameter))
        return True


class Event:
    def __init__(self, kind, path, state=1):
        platform = ViewPlatform(position=(0, 0, 10), aspect=1.0, near=1.0, far=100.0)
        self.modelViewMatrix = platform.modelMatrix()
        self.projectionMatrix = platform.viewMatrix()
        self.viewport = (0, 0, 100, 100)
        self.type, self.button, self.state = kind, 0, state
        self.objectPaths = [path if path is not None else []]
        clip = np.array([0, 0, 1, 1.0]) @ self.modelViewMatrix @ self.projectionMatrix
        self.viewCoordinate = (50, 50, (clip[2] / clip[3] + 1) / 2)
        self.stopPropagation = 0

    def getObjectPaths(self):
        return self.objectPaths

    def getPickPoint(self):
        return self.viewCoordinate[:2]


def test_a_click_released_over_it_follows_the_url():
    _graph, anchor, path = anchored(('other.x3d', 'mirror.x3d'))
    context = Clicking()
    sensing = x3dpointing.sensing(context)
    sensing.observe(Event('mousebutton', path, state=1))
    assert context.followed == []
    sensing.observe(Event('mousebutton', path, state=0))
    assert context.followed == [(anchor, ['other.x3d', 'mirror.x3d'], ['target=_self'])]


def test_a_click_released_elsewhere_does_not():
    _graph, _anchor, path = anchored()
    context = Clicking()
    sensing = x3dpointing.sensing(context)
    sensing.observe(Event('mousebutton', path, state=1))
    sensing.observe(Event('mousebutton', None, state=0))
    assert context.followed == []


class Scene:
    def __init__(self, graph):
        self.graph = graph
        self.redraws = 0

    def getSceneGraph(self):
        return self.graph

    def triggerRedraw(self, force=0):
        self.redraws += 1


def test_the_context_binds_a_named_viewpoint():
    there = Viewpoint(DEF='V')
    graph = sceneGraph(children=[Viewpoint(), there])
    context = Scene(graph)
    assert ContextCore.OnAnchor(context, None, ['#V'], []) is True
    assert there.isBound is True
    assert context.redraws == 1


@pytest.mark.parametrize('url', [['other.x3d'], ['#missing'], []])
def test_the_context_leaves_other_urls(url):
    context = Scene(sceneGraph(children=[Viewpoint(DEF='V')]))
    assert ContextCore.OnAnchor(context, None, url, []) is False
