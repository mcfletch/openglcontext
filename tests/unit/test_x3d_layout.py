"""X3D's Layout arithmetic: rectangles, units and pixel coordinates -- no GL"""
import numpy as np
import pytest
from vrml.vrml97 import transformmatrix
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import layout

#: An orthographic projection of a window 4 units wide and 2 high.
ORTHO = transformmatrix.orthoMatrix(-2.0, 2.0, -1.0, 1.0, 0.1, 100.0)
#: The viewport it is drawn into: 400 by 200 pixels, 0.01 units each.
PIXELS = (400, 200)
PIXEL = (0.01, 0.01)
ROOT = (4.0, 2.0)
EYE = np.identity(4)


def spec(**fields):
    return layout.spec_of(x3d.Layout(**fields))


def corners(modelview, local=((-0.5, -0.5), (0.5, 0.5))):
    """Where two local points land in eye space"""
    return [tuple(np.round((np.array((x, y, 0.0, 1.0)) @ modelview)[:2], 6)) for x, y in local]


class TestSpec:
    def test_defaults(self):
        found = spec()
        assert found == layout.LayoutSpec()

    def test_one_value_serves_both_axes(self):
        found = spec(size=[0.5], sizeUnits=['PIXEL'], align=['LEFT'], scaleMode=['PIXEL'])
        assert found.size == (0.5, 0.5)
        assert found.sizeUnits == ('PIXEL', 'PIXEL')
        assert found.scaleMode == ('PIXEL', 'PIXEL')

    def test_one_align_value_is_horizontal_with_its_vertical_alike_read(self):
        assert spec(align=['LEFT']).align == ('LEFT', 'CENTER')

    def test_unknown_words_and_numbers_take_the_defaults(self):
        found = spec(align=['UP', 'SIDEWAYS'], sizeUnits=['FURLONG', 'PIXEL'],
                     size=[float('nan'), 2.0], scaleMode=['BIG', 'NONE'])
        assert found.align == ('CENTER', 'CENTER')
        assert found.sizeUnits == ('WORLD', 'PIXEL')
        assert found.size == (1.0, 2.0)
        assert found.scaleMode == ('NONE', 'NONE')

    def test_lower_case_words_are_read(self):
        assert spec(align=['right', 'top']).align == ('RIGHT', 'TOP')


class TestExtent:
    def test_orthographic_extent_is_the_window(self):
        assert layout.view_extent(ORTHO, 5.0) == pytest.approx((4.0, 2.0))
        assert layout.view_extent(ORTHO, 500.0) == pytest.approx((4.0, 2.0))

    def test_perspective_extent_grows_with_depth(self):
        projection = transformmatrix.perspectiveMatrix(np.pi / 2, 2.0, 0.1, 100.0)
        near = layout.view_extent(projection, 1.0)
        assert near == pytest.approx((4.0, 2.0))
        assert layout.view_extent(projection, 3.0) == pytest.approx((12.0, 6.0))

    def test_an_origin_behind_the_eye_is_measured_close_to_it(self):
        projection = transformmatrix.perspectiveMatrix(np.pi / 2, 1.0, 0.1, 100.0)
        width, _height = layout.view_extent(projection, -4.0)
        assert 0.0 < width < 1e-3

    def test_a_degenerate_projection_spans_nothing(self):
        assert layout.view_extent(np.zeros((4, 4)), 1.0) == (0.0, 0.0)

    def test_eye_per_pixel(self):
        assert layout.eye_per_pixel(ORTHO, PIXELS, 1.0) == pytest.approx(PIXEL)

    def test_an_empty_viewport_counts_a_pixel(self):
        assert layout.eye_per_pixel(ORTHO, (0, 0), 1.0) == pytest.approx((4.0, 2.0))


class TestPlace:
    def test_the_default_layout_fills_the_viewport_a_unit_across(self):
        placed, region = layout.place(spec(), EYE, None, PIXEL, ROOT)
        assert region.size == pytest.approx(ROOT)
        assert corners(placed) == [(-2.0, -1.0), (2.0, 1.0)]

    def test_a_fraction_aligned_to_the_bottom_left(self):
        placed, region = layout.place(
            spec(size=[0.5, 0.5], sizeUnits=['FRACTION'], align=['LEFT', 'BOTTOM']),
            EYE, None, PIXEL, ROOT)
        assert region.size == pytest.approx((2.0, 1.0))
        assert corners(placed) == [(-2.0, -1.0), (0.0, 0.0)]

    def test_a_pixel_rectangle_at_the_top_right_in_pixel_units(self):
        placed, region = layout.place(
            spec(size=[100, 50], sizeUnits=['PIXEL'], align=['RIGHT', 'TOP'],
                 scaleMode=['PIXEL']), EYE, None, PIXEL, ROOT)
        assert region.size == pytest.approx((1.0, 0.5))
        # The rectangle's centre is 50 and 25 pixels in from the corner
        assert corners(placed, ((0, 0), (50, 25))) == [(1.5, 0.75), (2.0, 1.0)]

    def test_an_offset_in_pixels_and_fractions(self):
        placed, _region = layout.place(
            spec(size=[0.5, 0.5], sizeUnits=['FRACTION'], offset=[10, 0.25],
                 offsetUnits=['PIXEL', 'FRACTION']), EYE, None, PIXEL, ROOT)
        assert corners(placed, ((0, 0),)) == [(0.1, 0.5)]

    def test_stretch_keeps_the_other_axis_scale(self):
        placed, _region = layout.place(
            spec(size=[0.5, 0.5], sizeUnits=['FRACTION'], scaleMode=['STRETCH', 'FRACTION']),
            EYE, None, PIXEL, ROOT)
        assert placed[0, 0] == pytest.approx(1.0)
        assert placed[1, 1] == pytest.approx(1.0)

    def test_stretch_on_y_follows_x(self):
        placed, _region = layout.place(
            spec(scaleMode=['PIXEL', 'STRETCH']), EYE, None, PIXEL, ROOT)
        assert placed[1, 1] == pytest.approx(0.01)

    def test_both_stretched_take_the_longer_side(self):
        placed, _region = layout.place(
            spec(scaleMode=['STRETCH', 'STRETCH']), EYE, None, PIXEL, ROOT)
        assert placed[0, 0] == placed[1, 1] == pytest.approx(4.0)

    def test_none_inside_a_layout_keeps_the_parents_scale(self):
        outer, region = layout.place(spec(scaleMode=['PIXEL']), EYE, None, PIXEL, ROOT)
        inner, _ = layout.place(spec(size=[0.5], sizeUnits=['FRACTION']), outer, region,
                                PIXEL, ROOT)
        assert inner[0, 0] == pytest.approx(0.01)

    def test_world_units_inside_a_layout_are_the_parents(self):
        outer, region = layout.place(
            spec(size=[200, 100], sizeUnits=['PIXEL'], align=['LEFT', 'BOTTOM'],
                 scaleMode=['PIXEL']), EYE, None, PIXEL, ROOT)
        assert region.sizeUnits == ('PIXEL', 'PIXEL')
        inner, inner_region = layout.place(
            spec(size=[50, 50], align=['RIGHT', 'TOP']), outer, region, PIXEL, ROOT)
        assert inner_region.size == pytest.approx((0.5, 0.5))
        # The outer rectangle's top right corner is at (0, 0) in eye space
        assert corners(inner, ((0, 0),)) == [(-0.25, -0.25)]

    def test_world_units_outermost_are_fractions(self):
        _placed, region = layout.place(spec(size=[0.25, 0.5]), EYE, None, PIXEL, ROOT)
        assert region.size == pytest.approx((1.0, 1.0))
        assert region.sizeUnits == ('FRACTION', 'FRACTION')

    def test_the_parents_rotation_and_place_are_kept_and_its_scale_dropped(self):
        parent = transformmatrix.transMatrix((1.0, 2.0, -5.0))[0]
        turn = transformmatrix.rotMatrix((0.0, 0.0, 1.0, np.pi / 2))[0]
        parent = np.diag((3.0, 3.0, 3.0, 1.0)) @ turn @ parent
        placed, _region = layout.place(spec(scaleMode=['PIXEL']), parent, None, PIXEL, ROOT)
        origin = np.array((0.0, 0.0, 0.0, 1.0)) @ placed
        assert origin[:3] == pytest.approx((1.0, 2.0, -5.0))
        along = np.array((1.0, 0.0, 0.0, 0.0)) @ placed
        assert along[:3] == pytest.approx((0.0, 0.01, 0.0))


class TestScreen:
    def test_a_unit_is_a_pixel_facing_the_screen(self):
        turned = transformmatrix.rotMatrix((0.0, 1.0, 0.0, 0.7))[0] @ \
            transformmatrix.transMatrix((0.0, 0.0, -5.0))[0]
        placed = layout.screen_modelview(turned, ORTHO, PIXELS, snap=False)
        assert placed[:3, :3] == pytest.approx(np.diag((0.01, 0.01, 0.01)))
        assert placed[3, :3] == pytest.approx((0.0, 0.0, -5.0))

    def test_the_origin_is_snapped_to_a_pixel_corner(self):
        moved = transformmatrix.transMatrix((0.013, -0.0071, -5.0))[0]
        placed = layout.screen_modelview(moved, ORTHO, PIXELS)
        assert placed[3, :2] == pytest.approx((0.01, -0.01))

    def test_an_odd_viewport_snaps_to_half_pixels_about_the_centre(self):
        # 401 pixels of 0.01 units: the window is 4.01 units across, and the
        # centre is in the middle of pixel 200, half a pixel from its corners.
        projection = transformmatrix.orthoMatrix(-2.005, 2.005, -1.0, 1.0, 0.1, 100.0)
        moved = transformmatrix.transMatrix((0.001, 0.0, -5.0))[0]
        placed = layout.screen_modelview(moved, projection, (401, 200))
        assert placed[0, 0] == pytest.approx(0.01)
        assert placed[3, 0] == pytest.approx(0.005)
        # Pixel 201's left edge, counted from the window's left at -2.005
        assert (placed[3, 0] + 2.005) / 0.01 == pytest.approx(201.0)

    def test_perspective_pixels_are_measured_at_the_origins_depth(self):
        projection = transformmatrix.perspectiveMatrix(np.pi / 2, 2.0, 0.1, 100.0)
        moved = transformmatrix.transMatrix((0.0, 0.0, -3.0))[0]
        placed = layout.screen_modelview(moved, projection, PIXELS, snap=False)
        assert placed[0, 0] == pytest.approx(12.0 / 400)


class TestLocalMatrix:
    def test_the_local_matrix_takes_the_parent_to_the_wanted(self):
        parent = transformmatrix.transMatrix((1.0, 2.0, 3.0))[0]
        wanted = np.diag((0.5, 0.5, 1.0, 1.0)) @ parent
        forward, inverse = layout.local_matrix(wanted, parent)
        assert forward @ parent == pytest.approx(wanted)
        assert forward @ inverse == pytest.approx(np.identity(4))

    def test_a_singular_parent_has_no_local_matrix(self):
        assert layout.local_matrix(np.identity(4), np.zeros((4, 4))) is None

    def test_a_singular_wanted_has_no_local_matrix(self):
        assert layout.local_matrix(np.zeros((4, 4)), np.identity(4)) is None


class TestPlacingLayouts:
    """Layout nodes placed in a scene, as the render pass places them each frame"""

    CAMERA = transformmatrix.transMatrix((0.0, 0.0, -10.0))[0]

    def walk(self, *layers_):
        from OpenGLContext.passes.flatcore import FlatPass  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph import layering  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph.basenodes import sceneGraph  # noqa: PLC0415 kept with its use
        scene = sceneGraph(children=[layering.LayerSet(layers=list(layers_))])
        walked = FlatPass(scene, [])
        placed = [path for path in walked.paths.get(layering.Placed, ())]
        return walked, placed

    def eye(self, path):
        return layout.LayoutEye(self.CAMERA, ORTHO, PIXELS)

    def at(self, walked, node, local=(0.0, 0.0)):
        """Where `local` in `node`'s coordinates is in eye space"""
        path = walked.nodePaths[node][0]
        point = np.array((local[0], local[1], 0.0, 1.0)) @ path.transformMatrix() @ self.CAMERA
        return tuple(np.round(point[:2], 6))

    def test_a_layout_layer_puts_its_children_in_its_rectangle(self):
        from OpenGLContext.scenegraph import layering  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph.basenodes import Shape  # noqa: PLC0415 kept with its use
        shape = Shape()
        top = layering.LayoutLayer(
            layout=x3d.Layout(size=[100, 50], sizeUnits=['PIXEL'], align=['RIGHT', 'TOP'],
                              scaleMode=['PIXEL']),
            children=[shape])
        walked, placed = self.walk(top)
        assert layout.place_layouts(placed, self.eye) == 1
        assert self.at(walked, shape) == (1.5, 0.75)
        assert self.at(walked, shape, (50, 25)) == (2.0, 1.0)

    def test_a_second_frame_with_nothing_moved_places_nothing(self):
        from OpenGLContext.scenegraph import layering  # noqa: PLC0415 kept with its use
        top = layering.LayoutLayer(layout=x3d.Layout(size=[0.5], sizeUnits=['FRACTION']))
        _walked, placed = self.walk(top)
        assert layout.place_layouts(placed, self.eye) == 1
        assert layout.place_layouts(placed, self.eye) == 0

    def test_a_group_in_a_layout_measures_world_units_in_its_parents(self):
        from OpenGLContext.scenegraph import layering  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph.basenodes import Shape  # noqa: PLC0415 kept with its use
        shape = Shape()
        inner = layering.LayoutGroup(layout=x3d.Layout(size=[50, 50], align=['RIGHT', 'TOP']),
                                     children=[shape])
        top = layering.LayoutLayer(
            layout=x3d.Layout(size=[200, 100], sizeUnits=['PIXEL'], align=['LEFT', 'BOTTOM'],
                              scaleMode=['PIXEL']),
            children=[inner])
        walked, placed = self.walk(top)
        layout.place_layouts(placed, self.eye)
        assert self.at(walked, shape) == (-0.25, -0.25)

    def test_a_group_with_no_layout_is_drawn_in_its_parents_coordinates(self):
        from OpenGLContext.scenegraph import layering  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph.basenodes import Shape  # noqa: PLC0415 kept with its use
        shape = Shape()
        top = layering.LayoutLayer(
            layout=x3d.Layout(size=[100, 50], sizeUnits=['PIXEL'], align=['RIGHT', 'TOP'],
                              scaleMode=['PIXEL']),
            children=[layering.LayoutGroup(children=[shape])])
        walked, placed = self.walk(top)
        layout.place_layouts(placed, self.eye)
        assert self.at(walked, shape, (50, 25)) == (2.0, 1.0)

    def test_a_screen_group_counts_pixels(self):
        from OpenGLContext.scenegraph import layering  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph.basenodes import Shape, Transform  # noqa: PLC0415 kept with its use
        shape = Shape()
        screen = layering.ScreenGroup(children=[shape])
        layer = layering.Layer(children=[Transform(translation=(0.5, 0.25, 0),
                                                   scale=(3, 3, 3), children=[screen])])
        walked, placed = self.walk(layer)
        layout.place_layouts(placed, self.eye)
        assert self.at(walked, shape) == (0.5, 0.25)
        assert self.at(walked, shape, (10, 20)) == (0.6, 0.45)

    def test_a_path_with_no_eye_is_left_where_it_is(self):
        from OpenGLContext.scenegraph import layering  # noqa: PLC0415 kept with its use
        top = layering.LayoutLayer(layout=x3d.Layout(size=[0.5], sizeUnits=['FRACTION']))
        _walked, placed = self.walk(top)
        assert layout.place_layouts(placed, lambda path: None) == 0
        assert np.allclose(top.localMatrix(), np.identity(4))
