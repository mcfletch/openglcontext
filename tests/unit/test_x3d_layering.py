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


class TestStackParts:
    """The rectangles a frame draws a layer stack in, bottom first"""

    def setup_method(self):
        self.port = x3d.Viewport(clipBoundary=[0.5, 1, 0, 0.5])
        self.inner = x3d.Viewport(clipBoundary=[0, 0.5, 0, 1])
        self.shape = x3d.Shape()
        self.layer = x3d.Layer(viewport=self.port)
        self.found = x3d.LayerSet(layers=[self.layer], order=[0, 1])
        self.paths = [(object(), self.shape),
                      (object(), self.found, self.layer, self.shape),
                      (object(), self.found, self.layer, self.inner, self.shape)]

    def parts(self, rect=(0, 0, 400, 200)):
        return layers.stack_parts(layers.drawn_layers(self.found),
                                  layers.Membership().of(self.paths, 1), rect)

    def test_each_layer_is_drawn_in_its_viewport(self):
        found = self.parts()
        assert [(part.plan.number, part.chain, part.rect) for part in found] == [
            (0, (), (0, 0, 400, 200)),
            (1, (), (200, 0, 200, 100)),
            (1, (self.inner,), (200, 0, 100, 100)),
        ]

    def test_a_layers_first_part_clears_and_the_bottom_layer_is_marked(self):
        found = self.parts()
        assert [part.first for part in found] == [True, True, False]
        assert [part.bottom for part in found] == [True, False, False]

    def test_the_parts_are_in_the_views_rectangle(self):
        found = self.parts((10, 20, 400, 200))
        assert found[1].rect == (210, 20, 200, 100)

    def test_a_layer_with_nothing_to_draw_in_is_left_out(self):
        self.port.clipBoundary = [0.5, 0.5, 0, 1]
        assert [part.plan.number for part in self.parts()] == [0]

    def test_a_part_with_nothing_to_draw_in_is_left_out(self):
        self.inner.clipBoundary = [0, 0, 0, 1]
        assert [part.chain for part in self.parts()] == [(), ()]

    def test_the_bottom_is_the_first_layer_drawn(self):
        self.found.order = [1, 0]
        found = self.parts()
        assert [(part.plan.number, part.bottom) for part in found] == [
            (1, True), (1, False), (0, False)]


class TestAfterwardsCleared:
    """Whether a part's depth is still in the buffer once the frame is drawn"""

    def parts(self):
        plan = layers.LayerPlan(0, None)
        upper = layers.LayerPlan(1, object())
        return [layers.LayerPart(plan, (), (0, 0, 400, 200), True, True),
                layers.LayerPart(upper, (), (200, 0, 200, 100), True, False),
                layers.LayerPart(upper, ('chain',), (200, 0, 100, 100), False, False)]

    def test_a_point_a_later_layer_clears_is_cleared(self):
        assert layers.cleared_after(self.parts(), 0, (250, 50))

    def test_a_point_outside_the_later_layers_is_not(self):
        assert not layers.cleared_after(self.parts(), 0, (50, 50))

    def test_a_layers_own_parts_do_not_clear_it(self):
        assert not layers.cleared_after(self.parts(), 1, (250, 50))

    def test_the_part_a_path_is_drawn_in(self):
        parts = self.parts()
        assert layers.part_of(parts, parts[1].plan.node, ('chain',)) == 2
        assert layers.part_of(parts, None, ()) == 0
        assert layers.part_of(parts, object(), ()) is None


class TestSized:
    def test_a_camera_is_told_a_size_within_the_block(self):
        from OpenGLContext.move.viewplatform import ViewPlatform  # noqa: PLC0415 kept with its use
        camera = ViewPlatform(aspect=2.0)
        with layers.sized(camera, (300, 100)):
            assert camera.frustum[1] == pytest.approx(3.0)
        assert camera.frustum[1] == pytest.approx(2.0)

    def test_an_empty_size_tells_nothing(self):
        from OpenGLContext.move.viewplatform import ViewPlatform  # noqa: PLC0415 kept with its use
        camera = ViewPlatform(aspect=2.0)
        with layers.sized(camera, (0, 100)):
            assert camera.frustum[1] == pytest.approx(2.0)


class TestLayerCameras:
    """The camera a layer navigation does not drive is drawn through"""

    def paths_to(self, viewpoint, *above):
        from OpenGLContext.scenegraph import nodepath  # noqa: PLC0415 kept with its use
        return [nodepath.NodePath(list(above) + [viewpoint])]

    def test_a_layer_binding_nothing_is_seen_from_x3ds_default_viewpoint(self):
        from OpenGLContext.scenegraph import layering  # noqa: PLC0415 kept with its use
        camera = layers.LayerCameras().camera(layering.Layer(), [])
        assert camera.position[:3] == pytest.approx((0, 0, 10))
        assert camera.window is None
        assert camera.fieldOfView == pytest.approx(0.7854)  # the declared default

    def test_a_layout_layer_binding_nothing_is_seen_through_an_orthoviewpoint(self):
        from OpenGLContext.scenegraph import layering  # noqa: PLC0415 kept with its use
        camera = layers.LayerCameras().camera(layering.LayoutLayer(), [])
        assert camera.window == pytest.approx((-1, -1, 1, 1))
        assert camera.position[:3] == pytest.approx((0, 0, 10))

    def test_a_layer_is_seen_from_the_viewpoint_it_binds(self):
        from OpenGLContext.scenegraph import layering  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph.basenodes import Transform, Viewpoint  # noqa: PLC0415 kept with its use
        layer = layering.Layer()
        view = Viewpoint(position=(0, 1, 5), fieldOfView=0.5)
        moved = Transform(translation=(2, 0, 0), children=[view])
        layer.children = [moved]
        cameras = layers.LayerCameras()
        camera = cameras.camera(layer, self.paths_to(view, layer, moved))
        assert camera.position[:3] == pytest.approx((2, 1, 5))
        assert camera.fieldOfView == pytest.approx(0.5)
        view.position = (0, 1, 7)
        assert cameras.camera(layer, self.paths_to(view, layer, moved)) is camera
        assert camera.position[:3] == pytest.approx((2, 1, 7))

    def test_each_layer_has_a_camera_of_its_own(self):
        from OpenGLContext.scenegraph import layering  # noqa: PLC0415 kept with its use
        cameras = layers.LayerCameras()
        first, second = layering.Layer(), layering.Layer()
        assert cameras.camera(first, []) is not cameras.camera(second, [])
        assert cameras.camera(None, []) is cameras.camera(None, [])
