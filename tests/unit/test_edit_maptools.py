"""Moving the map as a tool in its own right.

Headless: a plan view is arithmetic, and a drag is two positions.
"""
import pytest

from OpenGLContext.edit.mapview import MapView
from OpenGLContext.edit.maptools import PanTool
from OpenGLContext.edit.tools import Pointer, ToolManager

VIEWPORT = (800, 600)


def _tool(**named):
    view = MapView(centre=(0.0, 0.0), span=600.0)
    moved = []
    tool = PanTool(view, lambda: VIEWPORT,
                   on_change=lambda: moved.append(1), **named)
    return tool, view, moved


class TestDraggingTheMap:
    def test_a_drag_takes_the_world_with_the_pointer(self) -> None:
        tool, view, _moved = _tool()
        tool.on_press(Pointer(x=400, y=300))
        tool.on_drag(Pointer(x=440, y=300))
        # 600 metres over 600 pixels: one metre a pixel, and the world follows
        # the pointer, so the centre goes the other way.
        assert view.centre[0] == pytest.approx(-40.0)

    def test_dragging_up_the_screen_moves_north(self) -> None:
        tool, view, _moved = _tool()
        tool.on_press(Pointer(x=400, y=300))
        tool.on_drag(Pointer(x=400, y=340))
        assert view.centre[1] == pytest.approx(40.0)

    def test_it_says_when_the_map_moved(self) -> None:
        tool, _view, moved = _tool()
        tool.on_press(Pointer(x=400, y=300))
        tool.on_drag(Pointer(x=410, y=300))
        assert moved == [1]

    def test_a_drag_is_measured_from_where_it_last_was(self) -> None:
        """Not from where it started, or the map runs away under the pointer."""
        tool, view, _moved = _tool()
        tool.on_press(Pointer(x=400, y=300))
        tool.on_drag(Pointer(x=410, y=300))
        tool.on_drag(Pointer(x=420, y=300))
        assert view.centre[0] == pytest.approx(-20.0)

    def test_a_move_with_nothing_held_does_nothing(self) -> None:
        tool, view, _moved = _tool()
        assert not tool.on_drag(Pointer(x=500, y=300))
        assert view.centre == (0.0, 0.0)


class TestWhatItLeavesAlone:
    def test_it_takes_the_left_button(self) -> None:
        tool, _view, _moved = _tool()
        assert tool.on_press(Pointer(x=400, y=300, button=0))

    def test_it_leaves_the_other_buttons_to_the_camera(self) -> None:
        tool, _view, _moved = _tool()
        assert not tool.on_press(Pointer(x=400, y=300, button=2))

    def test_the_release_ends_the_drag(self) -> None:
        tool, view, _moved = _tool()
        tool.on_press(Pointer(x=400, y=300))
        assert tool.on_release(Pointer(x=420, y=300))
        assert not tool.on_drag(Pointer(x=600, y=300))

    def test_escape_abandons_a_drag(self) -> None:
        tool, view, _moved = _tool()
        tools = ToolManager([tool])
        tools.press(Pointer(x=400, y=300))
        tools.key('<escape>', (0, 0, 0))
        where = view.centre
        tools.move(Pointer(x=600, y=300))
        assert view.centre == where


class TestHowItReads:
    def test_it_is_called_something_a_designer_recognises(self) -> None:
        tool, _view, _moved = _tool()
        assert tool.name == 'pan'
        assert tool.label
