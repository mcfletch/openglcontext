"""X3D's Layering and Layout nodes as the engine's classes: read from a
document, walked by the render pass, and placed by a matrix -- no GL"""
import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.passes.flatcore import FlatPass
from OpenGLContext.scenegraph import layering
from OpenGLContext.scenegraph.basenodes import Box, Shape, Transform
from OpenGLContext.scenegraph.text.fontstyle3d import ScreenFontStyle

NAMES = ['Layer', 'LayerSet', 'LayoutLayer', 'LayoutGroup', 'ScreenGroup', 'Viewport',
         'ScreenFontStyle']


def document(body):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    return Loader.loads(b'<X3D version="4.0"><Scene>' + body + b'</Scene></X3D>', 'scene.x3d')


@pytest.mark.parametrize('name', NAMES)
def test_each_is_the_engines_class(name):
    found = prototypes()[name]
    assert issubclass(found, x3d.CONCRETE_NODES[name])
    assert found.__module__.startswith('OpenGLContext.')


def shapes_drawn(scene):
    from vrml.vrml97 import nodetypes  # noqa: PLC0415 kept with its use
    walked = FlatPass(scene, [])
    return [path[-1] for path in walked.paths.get(nodetypes.Rendering, ())]


class TestWalking:
    def test_the_shapes_of_every_layer_are_walked(self):
        scene = document(
            b'<LayerSet order="0 1 2"><Layer><Shape DEF="first"><Box/></Shape></Layer>'
            b'<LayoutLayer><LayoutGroup><Viewport containerField="children"><ScreenGroup><Shape DEF="second">'
            b'<Box/></Shape></ScreenGroup></Viewport></LayoutGroup></LayoutLayer>'
            b'</LayerSet><Shape DEF="zero"><Box/></Shape>')
        drawn = {shape.DEF for shape in shapes_drawn(scene)}
        assert drawn == {'first', 'second', 'zero'}

    def test_a_layer_set_offers_its_layers(self):
        made = layering.LayerSet(layers=[layering.Layer(), layering.LayoutLayer()])
        assert made.renderedChildren() == list(made.layers)

    def test_a_layer_offers_its_children(self):
        shape = Shape(geometry=Box())
        assert layering.Layer(children=[shape]).renderedChildren() == [shape]


class TestPlacement:
    @pytest.mark.parametrize('kind', [layering.LayoutGroup, layering.LayoutLayer,
                                      layering.ScreenGroup])
    def test_a_placed_nodes_children_are_drawn_in_its_placement(self, kind):
        shape = Shape(geometry=Box())
        placed = kind(children=[shape])
        scene = layering.LayerSet(layers=[layering.LayoutLayer(children=[placed])]) \
            if kind is not layering.LayoutLayer else layering.LayerSet(layers=[placed])
        from OpenGLContext.scenegraph.basenodes import sceneGraph  # noqa: PLC0415 kept with its use
        walked = FlatPass(sceneGraph(children=[Transform(translation=(1, 0, 0),
                                                         children=[scene])]), [])
        path = walked.nodePaths[shape][0]
        assert np.allclose(path.transformMatrix()[3, :3], (1, 0, 0))
        wanted = np.diag((2.0, 3.0, 1.0, 1.0))
        wanted[3, :3] = (5.0, 0.0, 0.0)
        assert placed.place(wanted)
        assert np.allclose(path.transformMatrix()[3, :3], (6, 0, 0))
        assert np.allclose(np.diag(path.transformMatrix())[:2], (2, 3))

    def test_placing_where_it_is_changes_nothing(self):
        placed = layering.ScreenGroup()
        assert placed.place(np.identity(4)) is False
        moved = np.identity(4)
        moved[3, 0] = 1.0
        assert placed.place(moved) is True
        assert placed.place(moved.copy()) is False

    def test_a_placement_that_cannot_be_inverted_is_not_taken(self):
        placed = layering.ScreenGroup()
        assert placed.place(np.zeros((4, 4))) is False
        assert np.allclose(placed.localMatrix(), np.identity(4))

    def test_a_viewport_does_not_move_its_children(self):
        port = layering.Viewport(children=[Shape()])
        assert not hasattr(port, 'place')


class TestScreenFontStyle:
    def test_its_size_is_its_point_size_in_pixels(self):
        style = ScreenFontStyle(pointSize=12)
        assert style.size == pytest.approx(16.0)

    def test_the_default_is_twelve_points(self):
        assert ScreenFontStyle().size == pytest.approx(12 * 96 / 72)

    def test_it_draws_with_the_first_format_that_has_a_font(self):
        assert ScreenFontStyle().format == ''


def test_new_layers_are_walked_at_the_next_frame():
    from OpenGLContext.scenegraph.basenodes import sceneGraph  # noqa: PLC0415 kept with its use
    from vrml.vrml97 import nodetypes  # noqa: PLC0415 kept with its use
    found = layering.LayerSet()
    walked = FlatPass(sceneGraph(children=[found]), [])
    shape = Shape(geometry=Box())
    found.layers = [layering.Layer(children=[shape])]
    walked.walkPending()
    assert [path[-1] for path in walked.paths.get(nodetypes.Rendering, ())] == [shape]


class TestThePassesTables:
    """What the pass keeps of the layers, made again as what it is made from changes"""

    def walk(self):
        from OpenGLContext.scenegraph.basenodes import sceneGraph  # noqa: PLC0415 kept with its use
        self.shape = Shape(geometry=Box())
        self.group = layering.LayoutGroup(children=[self.shape])
        self.layer = layering.Layer(children=[self.group])
        self.light = layering.Layer()
        self.found = layering.LayerSet(layers=[self.layer, self.light], order=[0, 1, 2])
        return FlatPass(sceneGraph(children=[self.found]), [])

    def test_a_layout_groups_viewport_reclips_its_paths(self):
        walked = self.walk()
        assert walked.layerTable().chains(self.layer) == []
        port = layering.Viewport(clipBoundary=[0, 0.5, 0, 1])
        self.group.viewport = port
        assert walked.layerTable().chains(self.layer) == [(port,)]

    def test_a_new_path_is_in_its_layers_paths(self):
        from OpenGLContext.scenegraph.basenodes import PointLight  # noqa: PLC0415 kept with its use
        from vrml.vrml97 import nodetypes  # noqa: PLC0415 kept with its use
        walked = self.walk()
        assert list(walked.layerPaths(nodetypes.Light, self.light)) == []
        lamp = PointLight()
        self.light.children = [lamp]
        walked.walkPending()
        assert [path[-1] for path in walked.layerPaths(nodetypes.Light, self.light)] == [lamp]
        assert list(walked.layerPaths(nodetypes.Light, None)) == []

    def test_the_active_layer_follows_the_layer_set(self):
        walked = self.walk()
        assert walked.activeLayer() is None
        self.found.activeLayer = 2
        assert walked.activeLayer() is self.light
        self.found.order = [0, 1]
        assert walked.activeLayer() is None
