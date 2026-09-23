"""The furniture of a window of views: names, axes, corner controls, splitters.

Headless. Where each piece goes, what a press on it does, and which way the
axes point -- rectangles, bindings and arithmetic, with no window and no GL.
"""
import numpy as np
import pytest

from OpenGLContext.edit.mapview import MapView, MapViewPlatform
from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform
from OpenGLContext.multiview.navigation import PAN, ZOOM_DRAG, navigation_for
from OpenGLContext.multiview.views import View, ViewLayout
from OpenGLContext.ui.menu import MenuItem
from OpenGLContext.ui.metrics import REFERENCE_METRICS
from OpenGLContext.ui.viewchrome import (
    AxisTriad,
    ExpandButton,
    NavigationButton,
    Splitter,
    ViewChrome,
    ViewLabel,
    axis_directions,
    fitted,
)

VIEWPORT = (800, 600)


def _layout():
    plan = View(MapViewPlatform(MapView(span=400.0)), name='top')
    front = View(OrthoViewPlatform(OrthoView('front')), name='front')
    left = View(OrthoViewPlatform(OrthoView('left')), name='left')
    angled = View(OrbitViewPlatform(OrbitView()), name='angled')
    layout = ViewLayout.quad(plan, front, left, angled)
    layout.arrange(*VIEWPORT)
    return layout


def _chrome(layout=None, **named):
    layout = layout if layout is not None else _layout()
    chrome = ViewChrome(layout=layout, **named)
    chrome.layout(VIEWPORT, REFERENCE_METRICS)
    return chrome


def _of(chrome, kind):
    return [widget for widget in chrome.walk() if isinstance(widget, kind)]


def _items(menu):
    return [widget for widget in menu.walk() if isinstance(widget, MenuItem)]


def _inside(widget, view):
    x, y, width, height = view.rect
    return (widget.rect.x >= x and widget.rect.y >= y
            and widget.rect.x + widget.rect.width <= x + width
            and widget.rect.y + widget.rect.height <= y + height)


class TestWhatItPutsInEachView:
    def test_a_name_an_axis_triad_and_the_controls(self):
        chrome = _chrome()
        assert len(_of(chrome, ViewLabel)) == 4
        assert len(_of(chrome, AxisTriad)) == 4
        assert len(_of(chrome, ExpandButton)) == 4
        assert len(_of(chrome, NavigationButton)) == 4

    def test_each_piece_sits_inside_the_view_it_belongs_to(self):
        chrome = _chrome()
        for widget in chrome.walk():
            if isinstance(widget, (ViewLabel, AxisTriad, ExpandButton,
                                   NavigationButton)):
                assert _inside(widget, widget.view), widget

    def test_the_name_stops_where_the_buttons_begin(self):
        """A name that ran under them would be read through the buttons."""
        chrome = _chrome()
        for label in _of(chrome, ViewLabel):
            buttons = [widget for widget in chrome.walk()
                       if isinstance(widget, (ExpandButton, NavigationButton))
                       and widget.view is label.view]
            assert buttons
            for button in buttons:
                assert label.rect.right <= button.rect.x

    def test_a_narrow_view_still_places_its_buttons(self):
        layout = _layout()
        layout.arrange(320, 240)
        chrome = _chrome(layout)
        for button in _of(chrome, ExpandButton):
            assert _inside(button, button.view)

    def test_the_name_is_the_views(self):
        chrome = _chrome()
        assert sorted(str(label.text) for label in _of(chrome, ViewLabel)) \
            == ['angled', 'front', 'left', 'top']

    def test_a_view_the_arrangement_hides_gets_nothing(self):
        layout = _layout()
        layout.maximise(layout.views[1])
        layout.arrange(*VIEWPORT)
        chrome = _chrome(layout)
        assert [label.view.name for label in _of(chrome, ViewLabel)] == ['front']

    def test_a_view_with_no_camera_has_no_axes_and_nothing_to_navigate(self):
        layout = ViewLayout([View(name='plain')])
        layout.arrange(*VIEWPORT)
        chrome = _chrome(layout)
        assert _of(chrome, ViewLabel)
        assert not _of(chrome, AxisTriad)
        assert not _of(chrome, NavigationButton)


class TestTheControlsCanBeTakenAway:
    @pytest.mark.parametrize('switch,kind', [
        ('labels', ViewLabel), ('axes', AxisTriad),
        ('expand', ExpandButton), ('navigation', NavigationButton),
    ])
    def test_each_kind_can_be_switched_off(self, switch, kind):
        chrome = _chrome(**{switch: False})
        assert not _of(chrome, kind)
        assert _of(chrome, ViewLabel) or switch == 'labels'

    def test_one_view_can_be_given_its_own_set(self):
        """A view whose controls are not the window's says so by name."""
        layout = _layout()
        chrome = _chrome(layout, only={'front': ('label',)})
        front = [widget for widget in chrome.walk()
                 if getattr(widget, 'view', None) is layout.views[1]]
        assert [type(widget) for widget in front] == [ViewLabel]
        assert len(_of(chrome, ExpandButton)) == 3


class TestThroughTheOverlayStack:
    """What a window routes a press through, rather than the panel directly."""

    def _stacked(self, layout):
        from OpenGLContext.ui.overlay import OverlayStack
        chrome = ViewChrome(layout=layout)
        stack = OverlayStack()
        stack.push(chrome)
        stack.layout(VIEWPORT, REFERENCE_METRICS)
        return stack, chrome

    def test_a_press_on_a_button_reaches_it(self):
        layout = _layout()
        stack, chrome = self._stacked(layout)
        button = _of(chrome, ExpandButton)[1]
        assert stack.pointer_pressed(*button.rect.centre)
        assert stack.pointer_released(*button.rect.centre)
        assert layout.maximised is button.view

    def test_a_press_in_a_view_goes_past_the_stack(self):
        """So the window hands it to the views, and a camera moves."""
        layout = _layout()
        stack, _chrome = self._stacked(layout)
        middle = layout.views[3].rect
        assert not stack.pointer_pressed(middle[0] + middle[2] // 2,
                                         middle[1] + middle[3] // 2)

    def test_a_splitter_drag_reaches_the_splitter(self):
        layout = _layout()
        stack, chrome = self._stacked(layout)
        splitter = [one for one in _of(chrome, Splitter) if one.vertical is True][0]
        assert stack.pointer_pressed(splitter.rect.centre[0], 120)
        stack.pointer_moved(splitter.rect.centre[0] + 80, 120)
        assert layout.split_at[0] == pytest.approx(0.6, abs=0.02)


class TestWhatTheSceneUnderneathStillHears:
    def test_a_press_on_no_control_is_not_the_chromes(self):
        """It stands over the whole window; a click in a view is the view's."""
        layout = _layout()
        chrome = _chrome(layout)
        middle = layout.views[3].rect
        assert not chrome.pointer_pressed(middle[0] + middle[2] // 2,
                                          middle[1] + middle[3] // 2)

    def test_it_is_not_modal(self):
        assert not _chrome().modal


class TestRoomSomethingElseHasTaken:
    """Told as a HUD layer is told: top, right, bottom, left."""

    def test_furniture_at_the_top_of_the_window_starts_below_what_is_reserved(self):
        layout = _layout()
        plain = _of(_chrome(layout), ViewLabel)
        reserved = _of(_chrome(layout, reserved=(30.0, 0.0, 0.0, 0.0)), ViewLabel)
        top_row = [label for label in plain
                   if label.view.rect[1] + label.view.rect[3] >= VIEWPORT[1]]
        assert top_row
        for label in top_row:
            moved = [one for one in reserved if one.view is label.view][0]
            assert moved.rect.y == label.rect.y - 30

    def test_room_at_the_left_moves_what_is_drawn_there(self):
        layout = _layout()
        plain = _of(_chrome(layout), ViewLabel)
        reserved = _of(_chrome(layout, reserved=(0.0, 0.0, 0.0, 120.0)),
                       ViewLabel)
        left_edge = [label for label in plain if label.view.rect[0] == 0]
        assert left_edge
        for label in left_edge:
            moved = [one for one in reserved if one.view is label.view][0]
            assert moved.rect.x == label.rect.x + 120

    def test_a_view_that_does_not_reach_the_top_is_left_alone(self):
        layout = _layout()
        plain = _of(_chrome(layout), ViewLabel)
        reserved = _of(_chrome(layout, reserved=(30.0, 0.0, 0.0, 0.0)), ViewLabel)
        lower = [label for label in plain
                 if label.view.rect[1] + label.view.rect[3] < VIEWPORT[1]]
        assert lower
        for label in lower:
            same = [one for one in reserved if one.view is label.view][0]
            assert same.rect.y == label.rect.y


class TestExpandingAView:
    def test_a_press_gives_the_view_the_window(self):
        layout = _layout()
        chrome = _chrome(layout)
        button = _of(chrome, ExpandButton)[1]
        chrome.pointer_pressed(*button.rect.centre)
        chrome.pointer_released(*button.rect.centre)
        assert layout.maximised is button.view

    def test_pressing_it_again_gives_the_arrangement_back(self):
        layout = _layout()
        chrome = _chrome(layout)
        button = _of(chrome, ExpandButton)[0]
        for _once in range(2):
            chrome.pointer_pressed(*button.rect.centre)
            chrome.pointer_released(*button.rect.centre)
        assert layout.maximised is None

    def test_the_window_is_told_to_place_the_views_again(self):
        placed = []
        layout = _layout()
        chrome = _chrome(layout, on_arrange=lambda: placed.append(1))
        button = _of(chrome, ExpandButton)[0]
        chrome.pointer_pressed(*button.rect.centre)
        chrome.pointer_released(*button.rect.centre)
        assert placed == [1]


class TestDraggingASplitter:
    def test_a_quad_has_a_splitter_each_way_and_a_cross(self):
        chrome = _chrome()
        assert sorted(str(one.vertical) for one in _of(chrome, Splitter)) \
            == ['False', 'None', 'True']

    def test_a_split_has_one_and_a_single_view_none(self):
        first, second = View(name='a'), View(name='b')
        assert len(_of(_chrome(ViewLayout.split(first, second)), Splitter)) == 1
        assert not _of(_chrome(ViewLayout([View(name='only')])), Splitter)

    def test_dragging_it_moves_the_line(self):
        layout = _layout()
        chrome = _chrome(layout)
        splitter = [one for one in _of(chrome, Splitter)
                    if one.vertical is True][0]
        # Away from the middle, where the two lines cross.
        chrome.pointer_pressed(splitter.rect.centre[0], 120)
        chrome.pointer_moved(splitter.rect.centre[0] + 80, 120)
        assert layout.split_at[0] == pytest.approx(0.6, abs=0.02)

    def test_the_line_stays_inside_the_window(self):
        layout = _layout()
        chrome = _chrome(layout)
        splitter = [one for one in _of(chrome, Splitter) if one.vertical is True][0]
        chrome.pointer_pressed(splitter.rect.centre[0], 120)
        chrome.pointer_moved(VIEWPORT[0] * 4, 120)
        assert 0.0 <= layout.split_at[0] <= 1.0

    def test_dragging_the_other_one_moves_the_other_line(self):
        layout = _layout()
        chrome = _chrome(layout)
        splitter = [one for one in _of(chrome, Splitter)
                    if one.vertical is False][0]
        across = layout.split_at[0]
        chrome.pointer_pressed(120, splitter.rect.centre[1])
        chrome.pointer_moved(120, splitter.rect.centre[1] - 60)
        assert layout.split_at[1] == pytest.approx(0.6, abs=0.02)
        assert layout.split_at[0] == across

    def test_the_crossing_moves_both_lines(self):
        layout = _layout()
        chrome = _chrome(layout)
        cross = [one for one in _of(chrome, Splitter) if one.vertical is None][0]
        chrome.pointer_pressed(*cross.rect.centre)
        chrome.pointer_moved(cross.rect.centre[0] + 80, cross.rect.centre[1] - 60)
        assert layout.split_at[0] == pytest.approx(0.6, abs=0.02)
        assert layout.split_at[1] == pytest.approx(0.6, abs=0.02)


class TestTheAxes:
    def test_a_plan_view_puts_east_right_and_north_up(self):
        layout = _layout()
        directions = axis_directions(layout.views[0])
        assert directions['x'][0] > 0.9
        assert directions['z'][1] < -0.9

    def test_the_front_elevation_puts_up_up(self):
        layout = _layout()
        directions = axis_directions(layout.views[1])
        assert directions['y'][1] > 0.9
        assert directions['x'][0] > 0.9

    def test_the_view_from_the_left_looks_along_x(self):
        layout = _layout()
        directions = axis_directions(layout.views[2])
        assert abs(directions['x'][0]) < 0.1
        assert directions['y'][1] > 0.9

    def test_turning_the_camera_turns_the_triad(self):
        layout = _layout()
        angled = layout.views[3]
        before = axis_directions(angled)['x']
        angled.camera.view.orbit(90.0, 0.0)
        assert not np.allclose(before, axis_directions(angled)['x'], atol=0.05)

    def test_a_view_with_no_camera_has_no_axes_to_draw(self):
        assert axis_directions(View(name='plain')) is None


class TestTheNavigationControl:
    def _stack(self):
        class _Stack:
            def __init__(self):
                self.pushed = []

            def push(self, panel):
                self.pushed.append(panel)
                return panel
        return _Stack()

    def test_pressing_it_offers_what_this_view_can_be_moved_by(self):
        layout = _layout()
        stack = self._stack()
        chrome = _chrome(layout, stack=stack)
        button = _of(chrome, NavigationButton)[0]
        chrome.pointer_pressed(*button.rect.centre)
        chrome.pointer_released(*button.rect.centre)
        assert stack.pushed
        texts = [str(item.text) for item in _items(stack.pushed[0])]
        assert 'Pan' in texts and 'Zoom by dragging' in texts
        assert 'Rotate' not in texts        # a plan view does not turn

    def test_a_camera_that_turns_offers_rotating(self):
        layout = _layout()
        stack = self._stack()
        chrome = _chrome(layout, stack=stack)
        button = [one for one in _of(chrome, NavigationButton)
                  if one.view is layout.views[3]][0]
        chrome.pointer_pressed(*button.rect.centre)
        chrome.pointer_released(*button.rect.centre)
        assert 'Rotate' in [str(item.text) for item in _items(stack.pushed[0])]

    def test_choosing_one_binds_it_to_the_button_that_opened_the_menu(self):
        layout = _layout()
        stack = self._stack()
        chrome = _chrome(layout, stack=stack)
        button = _of(chrome, NavigationButton)[0]
        chrome.pointer_pressed(*button.rect.centre)
        chrome.pointer_released(*button.rect.centre)
        navigation = navigation_for(button.view)
        item = [one for one in _items(stack.pushed[0])
                if str(one.text) == 'Zoom by dragging'][0]
        item.checked = True
        item.on_activate(item)
        assert navigation.keys_for(ZOOM_DRAG)
        assert navigation.command_for(navigation.keys_for(ZOOM_DRAG)[0]) == ZOOM_DRAG

    def test_switching_it_off_again_unbinds_it(self):
        layout = _layout()
        stack = self._stack()
        chrome = _chrome(layout, stack=stack)
        button = _of(chrome, NavigationButton)[0]
        navigation = navigation_for(button.view)
        navigation.rebind(ZOOM_DRAG, ['<mouse-1>'])
        chrome.pointer_pressed(*button.rect.centre)
        chrome.pointer_released(*button.rect.centre)
        item = [one for one in _items(stack.pushed[0])
                if str(one.text) == 'Zoom by dragging'][0]
        assert item.checked
        item.checked = False
        item.on_activate(item)
        assert navigation.keys_for(ZOOM_DRAG) == ()

    def test_a_gesture_can_be_taken_off_a_view(self):
        layout = _layout()
        stack = self._stack()
        chrome = _chrome(layout, stack=stack)
        button = _of(chrome, NavigationButton)[0]
        navigation = navigation_for(button.view)
        chrome.pointer_pressed(*button.rect.centre)
        chrome.pointer_released(*button.rect.centre)
        item = [one for one in _items(stack.pushed[0]) if str(one.text) == 'Pan'][0]
        item.checked = False
        item.on_activate(item)
        assert navigation.keys_for(PAN) == ()


class TestANameTooLongForItsCorner:
    """Nothing clips what the overlay draws, so a name is cut before it is."""

    def _width(self, text):
        return REFERENCE_METRICS.text_width(text)

    def test_a_name_that_fits_is_drawn_whole(self):
        assert fitted('front', self._width('front'), REFERENCE_METRICS) == 'front'

    def test_a_name_that_does_not_fit_is_cut_and_says_so(self):
        cut = fitted('perspective', self._width('perspec'), REFERENCE_METRICS)
        assert cut.endswith('...')
        assert self._width(cut) <= self._width('perspec')
        assert 'perspective'.startswith(cut[:-3])

    def test_a_corner_with_no_room_draws_nothing(self):
        assert fitted('perspective', 2, REFERENCE_METRICS) == ''

    def test_nothing_to_draw_stays_nothing(self):
        assert fitted('', 100, REFERENCE_METRICS) == ''
