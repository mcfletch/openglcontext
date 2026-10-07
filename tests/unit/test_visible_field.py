"""X3D's `visible`: a node set false is not drawn, nor is anything under it.

The pass keeps a path to every node it might draw. A node whose `visible` is
false is not walked, and setting the field drops its paths or walks it again
under the parents it was hidden from.
"""
import pytest
from pydispatch import dispatcher

from OpenGLContext.passes.flatcore import FlatPass
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.scenes import drawn_image, scene_context


@pytest.fixture
def watched():
    """A pass watching a Transform holding a Shape."""
    shape = basenodes.Shape(geometry=basenodes.Box())
    holder = basenodes.Transform(children=[shape])
    scene = basenodes.Group(children=[holder])
    watcher = FlatPass.__new__(FlatPass)
    watcher.nodePaths = {}
    watcher.paths = {}
    watcher.contexts = []
    watcher.integrate(scene)
    dispatcher.connect(watcher.onVisibleChange, signal=FlatPass.VISIBLE_SIGNAL)
    yield watcher, holder, shape
    dispatcher.disconnect(watcher.onVisibleChange, signal=FlatPass.VISIBLE_SIGNAL)


def live(watcher, node):
    return [path for path in watcher.npFor(node) if not path.broken]


class TestThePaths:
    def test_a_hidden_node_and_what_is_under_it_have_no_live_path(self, watched):
        watcher, holder, shape = watched
        holder.visible = False
        assert live(watcher, holder) == [] and live(watcher, shape) == []

    def test_shown_again_it_is_walked_under_its_parent(self, watched):
        watcher, holder, shape = watched
        holder.visible = False
        holder.visible = True
        assert len(live(watcher, holder)) == 1 and len(live(watcher, shape)) == 1

    def test_a_node_hidden_before_it_is_walked_is_not_walked(self):
        shape = basenodes.Shape(geometry=basenodes.Box(), visible=False)
        watcher = FlatPass.__new__(FlatPass)
        watcher.nodePaths, watcher.paths, watcher.contexts = {}, {}, []
        watcher.integrate(basenodes.Group(children=[shape]))
        assert live(watcher, shape) == []

    def test_saying_true_twice_walks_it_once(self, watched):
        watcher, holder, shape = watched
        holder.visible = False
        holder.visible = True
        holder.visible = True
        assert len(live(watcher, shape)) == 1


def _centre(context):
    image = drawn_image(context)
    h, w = image.shape[:2]
    return image[h // 2, w // 2]


def test_a_hidden_shape_is_not_drawn(gl_context):
    shape = basenodes.Shape(
        geometry=basenodes.Box(size=(3, 3, 3)),
        appearance=basenodes.Appearance(material=basenodes.Material(
            diffuseColor=(1, 0, 0), emissiveColor=(1, 0, 0))))
    holder = basenodes.Transform(children=[shape])
    with scene_context([basenodes.Viewpoint(position=(0, 0, 8)), holder]) as context:
        context.OnDraw(force=1)
        assert _centre(context)[0] > 100
        holder.visible = False
        context.OnDraw(force=1)
        assert _centre(context).sum() < 60
        holder.visible = True
        context.OnDraw(force=1)
        assert _centre(context)[0] > 100
