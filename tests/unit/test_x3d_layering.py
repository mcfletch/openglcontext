"""X3D's Layering component as the frame plans it: which layers draw, in what
order and where -- no GL"""
import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.multiview import layers


def layer_set(count=2, **fields):
    made = [x3d.Layer() for _ in range(count)]
    fields.setdefault('order', list(range(count + 1)))
    return x3d.LayerSet(layers=made, **fields), made


class TestDrawnLayers:
    def test_layers_draw_in_their_order(self):
        found, made = layer_set(order=[2, 0, 1])
        drawn = layers.drawn_layers(found)
        assert [plan.number for plan in drawn] == [2, 0, 1]
        assert [plan.node for plan in drawn] == [made[1], None, made[0]]

    def test_a_layer_left_out_of_the_order_is_not_drawn(self):
        found, made = layer_set(order=[1])
        assert [plan.node for plan in layers.drawn_layers(found)] == [made[0]]

    def test_numbers_past_the_layers_are_passed_over(self):
        found, _made = layer_set(order=[0, 7, -1, 1])
        assert [plan.number for plan in layers.drawn_layers(found)] == [0, 1]

    def test_a_layer_is_drawn_once(self):
        found, _made = layer_set(order=[1, 0, 1])
        assert [plan.number for plan in layers.drawn_layers(found)] == [1, 0]

    def test_a_hidden_layer_is_not_drawn(self):
        found, made = layer_set()
        made[0].visible = False
        assert [plan.number for plan in layers.drawn_layers(found)] == [0, 2]

    def test_a_layer_says_whether_it_is_picked(self):
        found, made = layer_set()
        made[1].pickable = False
        assert [plan.pickable for plan in layers.drawn_layers(found)] == [True, True, False]

    def test_the_default_order_is_layer_0_alone(self):
        found = x3d.LayerSet(layers=[x3d.Layer()])
        assert [plan.number for plan in layers.drawn_layers(found)] == [0]

    def test_a_layer_carries_its_viewport(self):
        port = x3d.Viewport(clipBoundary=[0, 0.5, 0, 0.5])
        found = x3d.LayerSet(layers=[x3d.Layer(viewport=port)], order=[0, 1])
        assert layers.drawn_layers(found)[1].viewport is port
        assert layers.drawn_layers(found)[0].viewport is None


class TestActiveLayer:
    def test_the_active_layer_is_the_one_named(self):
        found, _made = layer_set(activeLayer=2)
        assert layers.active_number(found, layers.drawn_layers(found)) == 2

    def test_layer_0_is_active_by_default(self):
        found, _made = layer_set()
        assert layers.active_number(found, layers.drawn_layers(found)) == 0

    @pytest.mark.parametrize('named', [5, -1])
    def test_a_layer_not_drawn_gives_way_to_the_lowest_drawn(self, named):
        found, _made = layer_set(activeLayer=named, order=[2, 1])
        assert layers.active_number(found, layers.drawn_layers(found)) == 2

    def test_nothing_drawn_is_no_active_layer(self):
        found, _made = layer_set(order=[])
        assert layers.active_number(found, []) is None


class TestClipping:
    def test_the_default_boundary_is_the_whole_rectangle(self):
        assert layers.clip_rect((0, 1, 0, 1), (10, 20, 300, 200)) == (10, 20, 300, 200)

    def test_a_boundary_is_fractions_of_the_rectangle(self):
        assert layers.clip_rect((0.5, 1, 0, 0.25), (0, 0, 400, 200)) == (200, 0, 200, 50)

    def test_fractions_are_held_to_the_rectangle(self):
        assert layers.clip_rect((-1, 2, -1, 2), (0, 0, 40, 20)) == (0, 0, 40, 20)

    def test_a_short_boundary_takes_the_defaults_it_lacks(self):
        assert layers.clip_rect((0.5,), (0, 0, 40, 20)) == (20, 0, 20, 20)

    def test_a_boundary_turned_inside_out_is_empty(self):
        assert layers.clip_rect((0.75, 0.25, 0, 1), (0, 0, 40, 20))[2] == 0

    def test_non_finite_fractions_take_the_defaults(self):
        assert layers.clip_rect((float('nan'), float('inf'), 0, 1),
                                (0, 0, 40, 20)) == (0, 0, 40, 20)

    def test_nested_viewports_clip_within_each_other(self):
        outer = x3d.Viewport(clipBoundary=[0.5, 1, 0, 1])
        inner = x3d.Viewport(clipBoundary=[0, 0.5, 0.5, 1])
        assert layers.chain_rect((outer, inner), (0, 0, 400, 200)) == (200, 100, 100, 100)

    def test_intersection_of_rectangles(self):
        assert layers.intersect((0, 0, 100, 100), (50, 60, 100, 100)) == (50, 60, 50, 40)
        assert layers.intersect((0, 0, 10, 10), (20, 20, 5, 5))[2:] == (0, 0)


class TestPathMembership:
    def setup_method(self):
        self.shape = x3d.Shape()
        self.port = x3d.Viewport()
        self.group = x3d.LayoutGroup(viewport=x3d.Viewport(clipBoundary=[0, 0.5, 0, 1]))
        self.layer = x3d.Layer()
        self.found = x3d.LayerSet(layers=[self.layer], order=[0, 1])

    def test_a_path_through_no_layer_is_layer_0s(self):
        assert layers.layer_of((object(), self.shape)) is None

    def test_a_path_through_a_layer_is_that_layers(self):
        assert layers.layer_of((object(), self.found, self.layer, self.shape)) is self.layer

    def test_the_viewports_a_path_is_clipped_by(self):
        path = (object(), self.found, self.layer, self.port, self.group, self.shape)
        assert layers.clip_chain(path) == (self.port, self.group.viewport)

    def test_a_layout_group_without_a_viewport_does_not_clip(self):
        path = (object(), self.found, self.layer, x3d.LayoutGroup(), self.shape)
        assert layers.clip_chain(path) == ()

    def test_membership_is_kept_while_the_paths_are_the_same(self):
        paths = [(object(), self.shape), (object(), self.found, self.layer, self.shape)]
        table = layers.Membership()
        first = table.of(paths, 1)
        assert first.layers == [None, self.layer]
        assert table.of(paths, 1) is first
        assert table.of(paths, 2) is not first

    def test_a_layers_mask(self):
        paths = [(object(), self.shape), (object(), self.found, self.layer, self.shape),
                 (object(), self.found, self.layer, self.port, self.shape)]
        found = layers.Membership().of(paths, 1)
        assert found.mask(self.layer, ()).tolist() == [False, True, False]
        assert found.mask(self.layer, (self.port,)).tolist() == [False, False, True]
        assert found.mask(None, ()).tolist() == [True, False, False]
        assert found.chains(self.layer) == [(self.port,)]
        assert isinstance(found.mask(None, ()), np.ndarray)
