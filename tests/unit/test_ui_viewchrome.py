"""The furniture of a window of views: names, axes, corner controls, splitters.

Headless. Where each piece goes, what a press on it does, and which way the
axes point -- rectangles, bindings and arithmetic, with no window and no GL.
"""
import numpy as np
import pytest

from OpenGLContext.edit.mapview import MapView, MapViewPlatform
from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform, view_kind
from OpenGLContext.multiview.views import View, ViewLayout
from OpenGLContext.ui.menu import Menu, MenuItem
from OpenGLContext.ui.metrics import REFERENCE_METRICS
from OpenGLContext.ui.viewchrome import (
    AxisTriad,
    ExpandButton,
    Splitter,
    ViewChrome,
    ViewLabel,
    axis_directions,
    fitted,
)
from OpenGLContext.multiview.viewpoints import SceneCamera
from OpenGLContext.ui.overlay import OverlayStack

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


def _sub(items, text):
    """The rows under the row that says ``text``."""
    found = [item for item in items if str(item.text) == text]
    assert found, '%r is not in the menu' % (text,)
    return list(found[0].submenu)


def _inside(widget, view):
    x, y, width, height = view.rect
    return (widget.rect.x >= x and widget.rect.y >= y
            and widget.rect.x + widget.rect.width <= x + width
            and widget.rect.y + widget.rect.height <= y + height)


class _RecordingStack:
    """An overlay stack that keeps what is pushed on it, for a menu to open on."""

    def __init__(self):
        self.pushed = []

    def push(self, panel):
        self.pushed.append(panel)
        return panel


class TestWhatItPutsInEachView:
    def test_a_name_an_axis_triad_and_the_button(self):
        chrome = _chrome()
        assert len(_of(chrome, ViewLabel)) == 4
        assert len(_of(chrome, AxisTriad)) == 4
        assert len(_of(chrome, ExpandButton)) == 4

    def test_a_view_alone_in_the_window_has_no_single_tile_button(self):
        layout = ViewLayout.single()
        layout.arrange(*VIEWPORT)
        chrome = _chrome(layout)
        assert len(_of(chrome, ViewLabel)) == 1
        assert not _of(chrome, ExpandButton)

    def test_each_piece_sits_inside_the_view_it_belongs_to(self):
        chrome = _chrome()
        for widget in chrome.walk():
            if isinstance(widget, (ViewLabel, AxisTriad, ExpandButton)):
                assert _inside(widget, widget.view), widget

    def test_the_name_stops_where_the_buttons_begin(self):
        """A name that ran under them would be read through the buttons."""
        chrome = _chrome()
        for label in _of(chrome, ViewLabel):
            buttons = [widget for widget in chrome.walk()
                       if isinstance(widget, ExpandButton)
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

    def test_the_name_is_a_button_as_wide_as_what_it_says(self):
        """A face the size of the name, so it reads as the thing to click."""
        chrome = _chrome()
        for label in _of(chrome, ViewLabel):
            natural = label.content_size(REFERENCE_METRICS)[0]
            assert label.rect.width == natural
            assert natural > REFERENCE_METRICS.text_width(str(label.text))

    def test_the_name_is_drawn_on_the_buttons_face(self):
        chrome = _chrome()
        label = _of(chrome, ViewLabel)[0]
        renderer = _Recorder(label.activeSkin())
        label.paint(renderer)
        framed = [args for name, args in renderer.calls if name == 'frame']
        assert framed and framed[0][0] == label.rect
        assert [args[1] for name, args in renderer.calls if name == 'textIn'] \
            == [str(label.text)]

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

    def test_a_view_with_no_camera_has_no_axes_to_draw(self):
        layout = ViewLayout([View(name='plain')])
        layout.arrange(*VIEWPORT)
        chrome = _chrome(layout)
        assert _of(chrome, ViewLabel)
        assert not _of(chrome, AxisTriad)


class TestTheControlsCanBeTakenAway:
    @pytest.mark.parametrize('switch,kind', [
        ('labels', ViewLabel), ('axes', AxisTriad), ('expand', ExpandButton),
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

    @pytest.mark.parametrize('key', ['<up>', '<down>'])
    def test_the_arrows_go_past_it_to_the_camera(self, key):
        """Up and down walk the camera; the chrome is furniture over it."""
        chrome = _chrome()
        stack = OverlayStack()
        stack.push(chrome, viewport=VIEWPORT, metrics=REFERENCE_METRICS)
        assert not stack.key(key, (0, 0, 0))
        assert chrome.focused_widget is None

    def test_the_arrows_still_go_past_it_after_a_view_s_name_is_clicked(self):
        """Choosing from a view's menu leaves its name focused, not the keyboard."""
        chrome = _chrome()
        label = _of(chrome, ViewLabel)[0]
        chrome.pointer_pressed(*label.rect.centre)
        assert not chrome.key('<down>', (0, 0, 0))


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


class _Recorder:
    """Records the drawing calls a widget makes."""

    def __init__(self, skin):
        self.skin = skin
        self.metrics = REFERENCE_METRICS
        self.now = None
        self.calls = []

    def __getattr__(self, name):
        def record(*arguments, **_named):
            self.calls.append((name, arguments))
        return record


class TestTheMenuOnScreen:
    """What the name opens, as a real overlay stack puts it up."""

    def _opened(self):
        stack = OverlayStack()
        chrome = ViewChrome(layout=_layout(), stack=stack)
        stack.push(chrome, VIEWPORT, REFERENCE_METRICS)
        label = _of(chrome, ViewLabel)[0]
        stack.pointer_pressed(*label.rect.centre)
        stack.pointer_released(*label.rect.centre)
        menu = stack.top
        assert isinstance(menu, Menu)
        return stack, label, menu

    def test_the_frame_after_it_opens_lays_it_out(self):
        stack, _label, _menu = self._opened()
        assert stack.laidOutFor is None

    def test_it_hangs_below_the_name(self):
        stack, label, menu = self._opened()
        stack.layout(VIEWPORT, REFERENCE_METRICS)
        assert menu.rect.top == label.rect.y
        assert menu.rect.x == label.rect.x
        for row in menu.items():
            assert menu.rect.contains(*row.rect.centre)

    def test_the_ways_of_looking_open_beside_it(self):
        stack, _label, menu = self._opened()
        stack.layout(VIEWPORT, REFERENCE_METRICS)
        item = [row for row in menu.items() if str(row.text) == 'View'][0]
        item.activate()
        assert isinstance(stack.top, Menu) and stack.top is not menu
        assert stack.top.parentMenu is menu
        assert 'Front' in [str(row.text) for row in stack.top.items()]


class TestTheScenesCameras:
    """The cameras the scene carries, offered by name in a view's menu."""

    def _cameras(self):
        return [SceneCamera(name='Porch', position=(0.0, 2.0, 10.0),
                            forward=(0.0, 0.0, -1.0), up=(0.0, 1.0, 0.0), fov=0.8),
                SceneCamera(name='Roof', position=(5.0, 9.0, 5.0),
                            forward=(-0.5, -0.7, -0.5), up=(0.0, 1.0, 0.0), fov=0.8)]

    def _menu(self, cameras, layout=None):
        stack = _RecordingStack()
        chrome = _chrome(layout, stack=stack, cameras=cameras)
        label = _of(chrome, ViewLabel)[3]            # the angled view
        chrome.pointer_pressed(*label.rect.centre)
        chrome.pointer_released(*label.rect.centre)
        return chrome, label.view, _items(stack.pushed[0])

    def test_a_scene_with_cameras_offers_them(self):
        _chrome_, _view, items = self._menu(self._cameras())
        cameras = [one for one in items if str(one.text) == 'Cameras'][0]
        assert [str(one.text) for one in cameras.submenu] == ['Porch', 'Roof']

    def test_they_may_be_asked_for_each_time(self):
        asked = []
        self._menu(lambda: asked.append(True) or self._cameras())
        assert asked

    def test_a_scene_with_none_offers_no_cameras(self):
        _chrome_, _view, items = self._menu([])
        assert 'Cameras' not in [str(one.text) for one in items]

    def test_choosing_one_looks_through_it(self):
        changed = []
        stack = _RecordingStack()
        chrome = _chrome(stack=stack, cameras=self._cameras(),
                         on_arrange=lambda: changed.append(True))
        label = _of(chrome, ViewLabel)[3]
        chrome.pointer_pressed(*label.rect.centre)
        chrome.pointer_released(*label.rect.centre)
        cameras = [one for one in _items(stack.pushed[0])
                   if str(one.text) == 'Cameras'][0]
        porch = list(cameras.submenu)[0]
        porch.on_activate(porch)
        assert label.view.camera.view.position() == pytest.approx((0.0, 2.0, 10.0))
        assert changed


class TestTheViewsOwnMenu:
    """What a click on the view's name opens."""


    def _opened(self, layout=None, **named):
        layout = layout if layout is not None else _layout()
        stack = _RecordingStack()
        chrome = _chrome(layout, stack=stack, **named)
        label = _of(chrome, ViewLabel)[0]
        chrome.pointer_pressed(*label.rect.centre)
        chrome.pointer_released(*label.rect.centre)
        assert stack.pushed, 'the name opened no menu'
        return chrome, label.view, _items(stack.pushed[0])

    def test_the_name_opens_it(self):
        _chrome_, _view, items = self._opened()
        assert items

    def test_it_is_short(self):
        """The ways of looking and of drawing are a level down, not in the list."""
        _chrome_, _view, items = self._opened()
        assert [str(item.text) for item in items] == ['View', 'Rendering', 'Single tile']

    def test_it_offers_every_way_of_looking_under_view(self):
        _chrome_, _view, items = self._opened()
        texts = [str(item.text) for item in _sub(items, 'View')]
        assert texts == ['Front', 'Back', 'Right', 'Left', 'Top', 'Bottom',
                         'Perspective', 'Ortho']

    def test_the_way_this_view_looks_is_ticked(self):
        _chrome_, _view, items = self._opened()
        ticked = [str(item.text) for item in _sub(items, 'View') if item.checked]
        assert ticked == ['Top']          # the quad's first view

    def test_choosing_one_points_the_view_that_way(self):
        _chrome_, view, items = self._opened()
        item = [one for one in _sub(items, 'View') if str(one.text) == 'Left'][0]
        item.on_activate(item)
        assert view_kind(view) == 'left'

    def test_a_view_with_no_camera_of_its_own_has_no_ways_of_looking(self):
        layout = ViewLayout.single()
        layout.arrange(*VIEWPORT)
        _chrome_, _view, items = self._opened(layout)
        assert 'View' not in [str(item.text) for item in items]

    def test_it_offers_shaded_and_wireframe_under_rendering(self):
        _chrome_, view, items = self._opened()
        rendering = _sub(items, 'Rendering')
        assert [str(item.text) for item in rendering] == ['Shaded', 'Wireframe']
        wire = [one for one in rendering if str(one.text) == 'Wireframe'][0]
        assert not wire.checked
        wire.on_activate(wire)
        assert view.style.wireframe

    def test_it_maximises_and_gives_the_window_back(self):
        layout = _layout()
        _chrome_, view, items = self._opened(layout)
        item = [one for one in items if str(one.text) == 'Single tile'][0]
        item.on_activate(item)
        assert layout.maximised is view

    def test_a_view_alone_in_the_window_is_offered_neither(self):
        layout = ViewLayout.single()
        layout.arrange(*VIEWPORT)
        _chrome_, _view, items = self._opened(layout)
        texts = [str(item.text) for item in items]
        assert 'Single tile' not in texts and 'Four tiles' not in texts

    def test_a_maximised_view_is_offered_the_tiles_instead(self):
        layout = _layout()
        layout.maximise(layout.views[0])
        layout.arrange(*VIEWPORT)
        _chrome_, _view, items = self._opened(layout)
        texts = [str(item.text) for item in items]
        assert 'Four tiles' in texts and 'Single tile' not in texts

    def test_zooming_to_fit_needs_a_window_that_says_what_there_is(self):
        _chrome_, _view, items = self._opened()
        assert 'Zoom to fit' not in [str(item.text) for item in items]

    def test_zooming_to_fit_frames_what_the_window_says_there_is(self):
        layout = _layout()
        low, high = (-50.0, 0.0, -50.0), (50.0, 20.0, 50.0)
        _chrome_, view, items = self._opened(layout, bounds=lambda: (low, high))
        item = [one for one in items if str(one.text) == 'Zoom to fit'][0]
        item.on_activate(item)
        corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1])
                   for z in (low[2], high[2])]
        for corner in corners:
            clip = np.append(np.asarray(corner, 'd'), 1.0) @ view.camera.matrix()
            assert np.all(np.abs(clip[:3] / clip[3]) <= 1.0 + 1e-5), corner

    def test_what_the_pointer_does_is_not_offered(self):
        _chrome_, _view, items = self._opened()
        assert 'What the pointer does' not in [str(item.text) for item in items]


class TestTheButtonsGlyph:
    def test_it_draws_an_outline_where_the_view_is_not_maximised(self):
        layout = _layout()
        chrome = _chrome(layout)
        button = _of(chrome, ExpandButton)[0]
        assert not button.maximised()

    def test_it_draws_the_tiles_where_the_view_has_the_window(self):
        layout = _layout()
        chrome = _chrome(layout)
        button = _of(chrome, ExpandButton)[0]
        layout.maximise(button.view)
        assert button.maximised()

    def test_the_button_is_a_square(self):
        chrome = _chrome()
        for button in _of(chrome, ExpandButton):
            assert abs(button.rect.width - button.rect.height) <= 2


class TestWhatTheExpandButtonSays:
    def test_its_tip_follows_what_it_would_do_without_being_drawn(self):
        layout = _layout()
        chrome = _chrome(layout)
        button = _of(chrome, ExpandButton)[0]
        alone = button.tooltip
        assert alone
        layout.maximise(button.view)
        assert button.tooltip and button.tooltip != alone


class TestWhatTheSplittersAskThePointerFor:
    def test_each_line_asks_for_the_arrows_that_drag_it(self):
        assert Splitter(vertical=True).cursor == 'resize-x'
        assert Splitter(vertical=False).cursor == 'resize-y'

    def test_the_quads_crossing_asks_for_either(self):
        assert Splitter(vertical=None).cursor == 'resize'


class TestLayingOutAgain:
    """A splitter drag relays the chrome out on every move; what is there stays."""

    def test_the_controls_are_the_same_ones_after_a_relayout(self):
        layout = _layout()
        chrome = _chrome(layout)
        before = list(chrome.walk())
        layout.split_at = (0.3, 0.6)
        layout.arrange(*VIEWPORT)
        chrome.layout(VIEWPORT, REFERENCE_METRICS)
        assert all(any(widget is now for now in chrome.walk()) for widget in before)

    def test_a_splitter_being_dragged_stays_the_one_drawn(self):
        layout = _layout()
        chrome = _chrome(layout)
        line = [splitter for splitter in _of(chrome, Splitter) if splitter.vertical][0]
        line.press(*line.rect.centre)
        line.drag(300, 300)
        layout.arrange(*VIEWPORT)
        chrome.layout(VIEWPORT, REFERENCE_METRICS)
        assert any(line is splitter for splitter in _of(chrome, Splitter))
        assert line.armed
        assert line.rect.centre[0] == pytest.approx(300, abs=2)

    def test_another_arrangement_gets_its_own_controls(self):
        layout = _layout()
        chrome = _chrome(layout)
        layout.maximise(layout.views[0])
        layout.arrange(*VIEWPORT)
        chrome.layout(VIEWPORT, REFERENCE_METRICS)
        assert not _of(chrome, Splitter)
        assert len(_of(chrome, ViewLabel)) == 1
