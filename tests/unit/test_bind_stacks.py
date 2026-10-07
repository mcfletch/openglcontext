"""The engine's backgrounds, fogs and viewpoints are on X3D's bind stacks.

``set_bind`` decides which of a scene's bindable nodes the pass uses
(``vrml.x3d.binding``); with none bound, the first the scene draws is bound.
The engine's own backgrounds are bindable as X3D's are.
"""
import pytest
from vrml.vrml97 import nodetypes
from vrml.x3d import binding

from OpenGLContext.context import Context
from OpenGLContext.passes import viewpointbinding
from OpenGLContext.passes._flat import FlatPass
from OpenGLContext.scenegraph.background import Background
from OpenGLContext.scenegraph.basenodes import Fog, Viewpoint, sceneGraph
from OpenGLContext.scenegraph.cubebackground import CubeBackground
from OpenGLContext.scenegraph.fog import bound_fog
from OpenGLContext.scenegraph.hdrbackground import HDRBackground
from OpenGLContext.scenegraph.simplebackground import SimpleBackground
from OpenGLContext.scenegraph.spherebackground import SphereBackground

BACKGROUNDS = [Background, CubeBackground, HDRBackground, SimpleBackground, SphereBackground]


@pytest.mark.parametrize('kind', BACKGROUNDS + [Fog])
def test_each_is_bindable(kind):
    assert issubclass(kind, binding.Bindable)
    assert binding.kind_of(kind()) in (nodetypes.Background, nodetypes.Fog)


@pytest.mark.parametrize('kind', BACKGROUNDS + [Fog])
def test_binding_is_the_stacks_alone(kind):
    """No field of the node's own says it is bound"""
    assert not hasattr(kind, 'bound')


class Paths:
    """A pass's paths by node type, without a pass"""

    def __init__(self, scene, kind):
        self.paths = {kind: [(scene, child) for child in scene.children]}


def test_the_first_background_is_bound_where_none_is():
    first, second = SphereBackground(), SphereBackground()
    scene = sceneGraph(children=[first, second])
    path = FlatPass.currentBackground(Paths(scene, nodetypes.Background))
    assert path[-1] is first
    assert first.isBound is True


def test_set_bind_chooses_the_background():
    first, second = SphereBackground(), SphereBackground()
    scene = sceneGraph(children=[first, second])
    holder = Paths(scene, nodetypes.Background)
    FlatPass.currentBackground(holder)
    second.set_bind = True
    assert FlatPass.currentBackground(holder)[-1] is second
    assert first.isBound is False
    second.set_bind = False
    assert FlatPass.currentBackground(holder)[-1] is first


def test_set_bind_chooses_the_fog():
    first, second = Fog(), Fog()
    scene = sceneGraph(children=[first, second])
    paths = Paths(scene, nodetypes.Fog).paths[nodetypes.Fog]
    assert bound_fog(paths)[-1] is first
    second.set_bind = True
    assert bound_fog(paths)[-1] is second


class FakePlatform:
    def setPosition(self, position):
        self.position = tuple(position)

    def setOrientation(self, orientation):
        self.orientation = tuple(orientation)

    def setFrustum(self, *args, **named):
        pass


class Viewing:
    """A context's scene, platform and redraw requests, with no window"""

    def __init__(self, scene):
        self.scene = scene
        self.platform = FakePlatform()

    def getSceneGraph(self):
        return self.scene

    def getViewPlatform(self):
        return self.platform

    def triggerRedraw(self, force=0):
        pass


class _Path(tuple):
    def transformMatrix(self):
        import numpy  # noqa: PLC0415 kept with its use
        return numpy.identity(4)

    def quaternion(self):
        from OpenGLContext import quaternion  # noqa: PLC0415 kept with its use
        return quaternion.fromXYZR(0, 1, 0, 0)


def viewing(count=3):
    views = [Viewpoint(position=(index, 0, 0)) for index in range(count)]
    scene = sceneGraph(children=views)
    scene.viewpointPaths = tuple(_Path((scene, view)) for view in views)
    return Viewing(scene), views


def test_set_bind_moves_the_platform_to_the_viewpoint():
    context, views = viewing()
    viewpointbinding.bind_scene_viewpoint(context)
    assert context.platform.position[0] == 0.0
    views[2].set_bind = True
    viewpointbinding.bind_scene_viewpoint(context)
    assert context.platform.position[0] == 2.0
    assert views[0].isBound is False


def test_the_next_viewpoint_is_bound_in_turn():
    context, views = viewing()
    viewpointbinding.bind_scene_viewpoint(context)
    for expected in (1, 2, 0):
        Context.OnNextViewpoint(context)
        assert binding.bound(views[0]) is views[expected]
        viewpointbinding.bind_scene_viewpoint(context)
        assert context.platform.position[0] == float(expected)


DOCUMENT = b'''<X3D version="4.0"><Scene>
  <Background DEF="RED" skyColor="1 0 0"/>
  <Background DEF="BLUE" skyColor="0 0 1"/>
  <BooleanTrigger DEF="T"/>
  <ROUTE fromNode="T" fromField="triggerTrue" toNode="BLUE" toField="set_bind"/>
</Scene></X3D>'''


def test_a_documents_route_binds_the_sky(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(DOCUMENT, 'scene.x3d')
    with scene_context(scene) as context:
        red = drawn_image(context).reshape(-1, 3).mean(0)
        assert red[0] > red[2] + 100
        scene.getDEF('T').set_triggerTime = 1.0
        blue = drawn_image(context).reshape(-1, 3).mean(0)
        assert blue[2] > blue[0] + 100
        assert scene.getDEF('RED').isBound is False
