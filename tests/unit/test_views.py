"""Several cameras on one window: the layout arithmetic, with no GL.

What :mod:`OpenGLContext.multiview.views` decides is where each view goes and which view
a pointer is talking to. Both are questions about rectangles and events, so
they are answered here without a window.
"""
import pytest

from OpenGLContext.events.mouseevents import (
    MouseButtonEvent, MouseMoveEvent, WHEEL_UP,
)
from OpenGLContext.multiview.views import MAX_VIEWS, View, ViewLayout, ViewStyle


class Camera:
    """What a layout asks of a camera: to be told the size it is drawn at."""

    def __init__(self):
        self.sizes = []

    def setViewport(self, width, height):
        self.sizes.append((width, height))


def press(x, y, button=0, state=1):
    event = MouseButtonEvent()
    event.button = button
    event.state = state
    event.pickPoint = (x, y)
    return event


def move(x, y):
    event = MouseMoveEvent()
    event.pickPoint = (x, y)
    return event


class TestArrangement:
    def test_a_single_view_is_the_whole_window(self):
        layout = ViewLayout.single()
        (view,) = layout.arrange(640, 480)
        assert view.rect == (0, 0, 640, 480)
        assert view.camera is None

    def test_a_split_is_side_by_side_by_default(self):
        left, right = View(name='left'), View(name='right')
        layout = ViewLayout.split(left, right)
        assert layout.arrange(640, 480) == [left, right]
        assert left.rect == (0, 0, 320, 480)
        assert right.rect == (320, 0, 320, 480)

    def test_a_vertical_split_puts_the_first_view_on_top(self):
        top, bottom = View(), View()
        layout = ViewLayout.split(top, bottom, vertical=True, fraction=0.25)
        layout.arrange(640, 480)
        # GL rows count from the bottom, so the top view starts high.
        assert top.rect == (0, 360, 640, 120)
        assert bottom.rect == (0, 0, 640, 360)

    def test_the_tiles_of_an_odd_window_meet_without_a_gap(self):
        left, right = View(), View()
        layout = ViewLayout.split(left, right, fraction=1 / 3)
        layout.arrange(641, 101)
        assert left.rect[0] + left.rect[2] == right.rect[0]
        assert left.rect[2] + right.rect[2] == 641

    def test_a_quad_reads_like_the_page(self):
        tl, tr, bl, br = View(name='tl'), View(name='tr'), View(name='bl'), View(name='br')
        layout = ViewLayout.quad(tl, tr, bl, br)
        layout.arrange(800, 600)
        assert tl.rect == (0, 300, 400, 300)
        assert tr.rect == (400, 300, 400, 300)
        assert bl.rect == (0, 0, 400, 300)
        assert br.rect == (400, 0, 400, 300)

    def test_moving_the_split_moves_every_edge_that_shares_it(self):
        tl, tr, bl, br = View(), View(), View(), View()
        layout = ViewLayout.quad(tl, tr, bl, br)
        layout.split_at = (0.75, 0.25)
        layout.arrange(800, 600)
        # The height fraction is measured down from the top.
        assert tl.rect == (0, 450, 600, 150)
        assert br.rect == (600, 0, 200, 450)

    def test_a_split_fraction_is_held_inside_the_window(self):
        layout = ViewLayout.split(View(), View())
        layout.split_at = (1.5, -2.0)
        assert layout.split_at == (1.0, 0.0)

    def test_a_custom_arrangement_places_views_where_it_says(self):
        a, b = View(), View()

        def picture_in_picture(width, height):
            return [(0, 0, width, height), (width - 100, height - 80, 100, 80)]

        layout = ViewLayout([a, b], arrangement=picture_in_picture)
        layout.arrange(400, 300)
        assert b.rect == (300, 220, 100, 80)

    def test_an_arrangement_must_place_every_view(self):
        layout = ViewLayout([View(), View()], arrangement=lambda w, h: [(0, 0, w, h)])
        with pytest.raises(ValueError):
            layout.arrange(10, 10)

    def test_a_layout_holds_no_more_views_than_the_view_block(self):
        with pytest.raises(ValueError):
            ViewLayout([View() for _ in range(MAX_VIEWS + 1)])

    def test_a_layout_holds_at_least_one_view(self):
        with pytest.raises(ValueError):
            ViewLayout([])

    def test_a_view_appears_in_a_layout_once(self):
        view = View()
        with pytest.raises(ValueError):
            ViewLayout.split(view, view)

    def test_a_named_arrangement_must_fit_its_views(self):
        with pytest.raises(ValueError):
            ViewLayout([View(), View(), View()], arrangement='split')
        with pytest.raises(ValueError):
            ViewLayout([View()], arrangement='sideways')


class TestCameras:
    def test_each_camera_is_told_the_size_of_its_own_tile(self):
        a, b = Camera(), Camera()
        layout = ViewLayout.split(View(a), View(b), fraction=0.25)
        layout.arrange(800, 600)
        assert a.sizes == [(200, 600)]
        assert b.sizes == [(600, 600)]

    def test_a_camera_is_told_again_only_when_its_tile_changes(self):
        a = Camera()
        layout = ViewLayout.split(View(a), View())
        layout.arrange(800, 600)
        layout.arrange(800, 600)
        layout.arrange(1000, 600)
        assert a.sizes == [(400, 600), (500, 600)]

    def test_the_context_camera_is_left_to_the_context(self):
        # A view with no camera of its own draws through the context's view
        # platform, whose aspect the context already keeps.
        layout = ViewLayout.single()
        layout.arrange(640, 480)
        assert layout.views[0].camera is None

    def test_a_camera_that_takes_no_size_is_left_alone(self):
        layout = ViewLayout.single(camera=object())
        layout.arrange(64, 64)

    def test_the_cameras_are_listed_once_each(self):
        shared = Camera()
        layout = ViewLayout.split(View(shared), View(shared))
        assert layout.cameras() == [shared]
        assert ViewLayout.single().cameras(default='ctx') == ['ctx']


class TestMaximise:
    def test_a_maximised_view_has_the_window_to_itself(self):
        a, b = View(), View()
        layout = ViewLayout.split(a, b)
        layout.maximise(b)
        assert layout.arrange(640, 480) == [b]
        assert b.rect == (0, 0, 640, 480)
        assert a.rect == (0, 0, 0, 0)
        assert not a.visible

    def test_maximising_the_maximised_view_restores_the_layout(self):
        a, b = View(), View()
        layout = ViewLayout.split(a, b)
        layout.maximise(b)
        layout.maximise(b)
        assert layout.arrange(640, 480) == [a, b]
        assert layout.maximised is None

    def test_maximise_with_no_view_takes_the_active_one(self):
        a, b = View(), View()
        layout = ViewLayout.split(a, b)
        layout.activate(b)
        layout.maximise()
        assert layout.maximised is b

    def test_a_layout_of_one_view_has_nothing_to_maximise(self):
        layout = ViewLayout.single()
        assert not layout.can_maximise
        layout.maximise(layout.views[0])
        assert layout.maximised is None

    def test_a_layout_of_several_views_can_maximise_one(self):
        assert ViewLayout.split(View(), View()).can_maximise

    def test_only_a_view_of_this_layout_can_be_maximised(self):
        with pytest.raises(ValueError):
            ViewLayout.single().maximise(View())


class TestPointer:
    def layout(self):
        left, right = View(name='left'), View(name='right')
        layout = ViewLayout.split(left, right)
        layout.arrange(200, 100)
        return layout, left, right

    def test_the_view_under_a_point_is_the_tile_containing_it(self):
        layout, left, right = self.layout()
        assert layout.view_at(0, 0) is left
        assert layout.view_at(99, 99) is left
        assert layout.view_at(100, 0) is right
        assert layout.view_at(199, 50) is right

    def test_a_point_outside_every_tile_is_under_no_view(self):
        layout, _left, _right = self.layout()
        assert layout.view_at(200, 50) is None
        assert layout.view_at(-1, 50) is None

    def test_a_view_gives_a_point_in_its_own_pixels(self):
        _layout, _left, right = self.layout()
        assert right.local(150, 40) == (50, 40)

    def test_the_first_view_starts_active(self):
        layout, left, _right = self.layout()
        assert layout.active is left

    def test_a_press_activates_the_view_under_it(self):
        layout, _left, right = self.layout()
        assert layout.route(press(150, 50)) is right
        assert layout.active is right

    def test_a_drag_stays_with_the_view_it_began_in(self):
        layout, left, _right = self.layout()
        assert layout.route(press(50, 50)) is left
        assert layout.route(move(150, 50)) is left
        assert layout.route(press(160, 50, state=0)) is left
        # Released: the pointer belongs to whatever it is over again.
        assert layout.route(move(150, 50)) is layout.view_at(150, 50)

    def test_a_drag_with_two_buttons_ends_with_the_last_release(self):
        layout, left, _right = self.layout()
        layout.route(press(50, 50, button=0))
        layout.route(press(50, 50, button=2))
        layout.route(press(150, 50, button=0, state=0))
        assert layout.route(move(150, 50)) is left
        layout.route(press(150, 50, button=2, state=0))
        assert layout.route(move(150, 50)).name == 'right'

    def test_a_wheel_notch_goes_to_the_view_under_it_and_holds_nothing(self):
        layout, left, right = self.layout()
        assert layout.route(press(150, 50, button=WHEEL_UP)) is right
        assert layout.active is left
        assert layout.route(move(50, 50)) is left

    def test_an_event_with_no_point_goes_to_the_active_view(self):
        layout, _left, right = self.layout()
        layout.activate(right)

        class Key:
            type = 'keypress'

        assert layout.route(Key()) is right

    def test_a_maximised_view_takes_every_point(self):
        layout, left, _right = self.layout()
        layout.maximise(left)
        layout.arrange(200, 100)
        assert layout.view_at(150, 50) is left

    def test_only_a_view_of_this_layout_can_be_activated(self):
        layout, _left, _right = self.layout()
        with pytest.raises(ValueError):
            layout.activate(View())


class TestACaptureThatLostItsRelease:
    """A release that never arrives -- focus lost mid-drag -- must not keep the pointer."""

    def layout(self):
        left, right = View(name='left'), View(name='right')
        layout = ViewLayout.split(left, right)
        layout.arrange(200, 100)
        return layout, left, right

    def test_pressing_the_held_button_again_starts_a_new_capture(self):
        layout, _left, right = self.layout()
        layout.route(press(50, 50, button=2))
        assert layout.route(press(150, 50, button=2)) is right
        assert layout.active is right
        layout.route(press(150, 50, button=2, state=0))
        assert layout.route(move(60, 50)).name == 'left'

    def test_letting_go_of_everything_frees_the_pointer(self):
        layout, left, right = self.layout()
        layout.route(press(50, 50, button=2))
        layout.release_all()
        assert layout.route(move(150, 50)) is right
        assert layout.route(press(150, 50, button=0)) is right


class TestStyle:
    def test_a_view_draws_the_scene_background_by_default(self):
        assert View().style == ViewStyle()
        assert ViewStyle().background is True
        assert ViewStyle().wireframe is False

    def test_a_flat_background_is_four_channels(self):
        assert ViewStyle(background=(0.1, 0.2, 0.3)).clear_colour() == (0.1, 0.2, 0.3, 1.0)
        assert ViewStyle(background=(0, 0, 0, 0.5)).clear_colour() == (0.0, 0.0, 0.0, 0.5)
        assert ViewStyle().clear_colour() is None

    def test_a_background_is_the_scene_or_a_colour(self):
        with pytest.raises(ValueError):
            ViewStyle(background=(1, 2))


class TestWhetherTheViewsCoverTheWindow:
    """What the frame asks before it clears: a layout need not tile the window."""

    def test_one_view_filling_it_does(self):
        from OpenGLContext.multiview.views import covers
        assert covers([(0, 0, 800, 600)], 800, 600)

    def test_a_split_and_a_quad_do(self):
        from OpenGLContext.multiview.views import covers
        assert covers([(0, 0, 400, 600), (400, 0, 400, 600)], 800, 600)
        assert covers([(0, 300, 400, 300), (400, 300, 400, 300),
                       (0, 0, 400, 300), (400, 0, 400, 300)], 800, 600)

    def test_a_band_left_for_a_toolbar_does_not(self):
        from OpenGLContext.multiview.views import covers
        assert not covers([(60, 0, 740, 600)], 800, 600)

    def test_a_gap_between_two_views_does_not(self):
        from OpenGLContext.multiview.views import covers
        assert not covers([(0, 0, 390, 600), (410, 0, 390, 600)], 800, 600)

    def test_a_band_across_the_bottom_does_not(self):
        from OpenGLContext.multiview.views import covers
        assert not covers([(0, 40, 800, 560)], 800, 600)

    def test_views_that_overlap_can_still_cover_it(self):
        from OpenGLContext.multiview.views import covers
        assert covers([(0, 0, 500, 600), (300, 0, 500, 600)], 800, 600)

    def test_a_view_placed_nowhere_covers_nothing(self):
        from OpenGLContext.multiview.views import covers
        assert not covers([(0, 0, 0, 0)], 800, 600)

    def test_a_window_with_no_pixels_is_covered_by_anything(self):
        from OpenGLContext.multiview.views import covers
        assert covers([], 0, 0)


class TestLosingFocus:
    def test_a_context_losing_focus_frees_its_layouts_pointer(self):
        from OpenGLContext.events.eventhandlermixin import HeldKeyMixin

        class Window(HeldKeyMixin):
            def emitKey(self, key, state, modifiers):
                pass

        left, right = View(name='left'), View(name='right')
        window = Window()
        window.viewLayout = ViewLayout.split(left, right)
        window.viewLayout.arrange(200, 100)
        window.viewLayout.route(press(50, 50, button=2))
        window.clearHeldKeys()
        assert window.viewLayout.route(move(150, 50)) is right
