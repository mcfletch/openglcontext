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


@pytest.mark.parametrize('url', [['#missing'], []])
def test_the_context_follows_nothing_for_no_viewpoint_or_no_url(url):
    context = Scene(sceneGraph(children=[Viewpoint(DEF='V')]))
    assert ContextCore.OnAnchor(context, None, url, []) is False


# -- where a url leads (anchor.anchor_targets), as X_ITE follows one --------

def document_anchor(tmp_path, url, parameter=()):
    """An Anchor read from a document in `tmp_path`"""
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    document = tmp_path / 'scene.x3d'
    document.write_text('<X3D version="4.0"><Scene><Viewpoint DEF="V"/>'
                        '<Anchor DEF="A"><Shape><Box/></Shape></Anchor></Scene></X3D>')
    scene = Loader.load(str(document))
    anchor = scene.getDEF('A')
    anchor.url = list(url)
    anchor.parameter = list(parameter)
    return scene, anchor


def kinds(found):
    return [(target.kind, target.url, target.viewpoint, target.target) for target in found]


def test_a_fragment_is_a_viewpoint_of_the_scene(tmp_path):
    from OpenGLContext.scenegraph.anchor import anchor_targets  # noqa: PLC0415 kept with its use
    _scene, anchor = document_anchor(tmp_path, ['#V', 'scene.x3d#V'])
    assert kinds(anchor_targets(anchor, anchor.url, anchor.parameter)) == [
        ('viewpoint', '', 'V', ''), ('viewpoint', '', 'V', '')]


def test_another_document_is_a_world_with_its_viewpoint(tmp_path):
    from OpenGLContext.scenegraph.anchor import anchor_targets  # noqa: PLC0415 kept with its use
    _scene, anchor = document_anchor(tmp_path, ['other.x3d#Top', 'more/third.wrl'])
    assert kinds(anchor_targets(anchor, anchor.url, anchor.parameter)) == [
        ('world', str(tmp_path / 'other.x3d'), 'Top', ''),
        ('world', str(tmp_path / 'more' / 'third.wrl'), '', '')]


@pytest.mark.parametrize('url, parameter', [
    (['page.html'], ()),
    (['page.XHTML'], ()),
    (['other.x3d'], ['description=x', 'target=_blank']),
    (['../outside.x3d'], ()),
    (['https://example.com/world.x3d'], ()),
])
def test_what_the_document_may_not_open_goes_elsewhere(tmp_path, url, parameter):
    from OpenGLContext.scenegraph.anchor import anchor_targets  # noqa: PLC0415 kept with its use
    _scene, anchor = document_anchor(tmp_path, url, parameter)
    found = anchor_targets(anchor, anchor.url, anchor.parameter)
    assert [target.kind for target in found] == ['elsewhere']
    assert found[0].url == url[0]
    assert found[0].target == ('_blank' if parameter else '')


class Following(Scene):
    """A context following its anchors' urls through a scene loader it records"""

    def __init__(self, graph):
        super().__init__(graph)
        self.loads = []
        self.elsewhere = []
        self.sceneLoader = self

    def load(self, source, on_loaded=None, on_failed=None, **named):
        self.loads.append((source, on_loaded, on_failed))

    def OnAnchorElsewhere(self, anchor, url, target):
        self.elsewhere.append((url, target))
        return True


class Request:
    def __init__(self, result=None):
        self.result = result


def test_the_context_loads_another_world_in_place(tmp_path):
    scene, anchor = document_anchor(tmp_path, ['missing.x3d', 'other.x3d#Top'])
    context = Following(scene)
    assert ContextCore.OnAnchor(context, anchor, anchor.url, anchor.parameter) is True
    source, loaded, failed = context.loads[0]
    assert source == str(tmp_path / 'missing.x3d')
    failed(Request())
    source, loaded, failed = context.loads[1]
    assert source == str(tmp_path / 'other.x3d')
    top = Viewpoint(DEF='Top')
    world = sceneGraph(children=[Viewpoint(), top])
    loaded(Request(world))
    assert context.sg is world
    assert top.isBound is True


def test_the_context_hands_other_urls_to_the_application(tmp_path):
    scene, anchor = document_anchor(tmp_path, ['page.html'], ['target=_blank'])
    context = Following(scene)
    assert ContextCore.OnAnchor(context, anchor, anchor.url, anchor.parameter) is True
    assert context.elsewhere == [('page.html', '_blank')]
    assert context.loads == []


def test_the_contexts_own_hook_follows_nothing_elsewhere():
    assert ContextCore.OnAnchorElsewhere(Scene(None), None, 'page.html', '') is False


def test_a_window_follows_an_anchor_to_another_world(gl_context, tmp_path):
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    (tmp_path / 'other.x3d').write_text(
        '<X3D version="4.0"><Scene><Viewpoint DEF="Front"/>'
        '<Viewpoint DEF="Top" position="0 10 0"/></Scene></X3D>')
    scene, anchor = document_anchor(tmp_path, ['other.x3d#Top'])
    with scene_context(scene, size=(32, 32)) as context:
        context.OnDraw(force=1)
        assert context.OnAnchor(anchor, list(anchor.url), []) is True
        for request in context.sceneLoader.pending:
            request.wait(10.0)
        context.renderQueue.run()
        world = context.getSceneGraph()
        context.OnDraw(force=1)
    assert world is not scene
    assert world.getDEF('Top').isBound is True
