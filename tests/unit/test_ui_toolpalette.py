"""The tool palette: which tool the pointer drives, chosen by clicking it.

Headless. A palette is a panel and a tool button is a widget, so what is
asserted here is what a designer would find out by using it -- that clicking a
button puts that tool in force, that the strip says which tool is in force
however the choice was made, and that a click on the strip is spent on the
strip rather than also landing on the world behind it.
"""
import pytest

from OpenGLContext.edit.tools import Pointer, ToolManager, ToolMode
from OpenGLContext.ui.metrics import REFERENCE_METRICS
from OpenGLContext.ui.toolpalette import ToolButton, ToolPalette

VIEWPORT = (1280, 720)


def _tools():
    return ToolManager([
        ToolMode(name='route', label='Draw route'),
        ToolMode(name='pan', label='Pan/zoom'),
        ToolMode(name='sculpt', label='Sculpt'),
    ])


def _palette(tools=None, **named):
    tools = tools if tools is not None else _tools()
    palette = ToolPalette(tools=tools, **named)
    palette.layout(VIEWPORT, REFERENCE_METRICS)
    return palette, tools


def _buttons(palette):
    return [widget for widget in palette.walk()
            if isinstance(widget, ToolButton)]


def _centre(widget):
    return (widget.rect.x + widget.rect.width / 2.0,
            widget.rect.y + widget.rect.height / 2.0)


def _click(palette, x, y):
    """A whole click, as the overlay stack delivers one."""
    took = palette.pointer_pressed(x, y, 0)
    released = palette.pointer_released(x, y, 0)
    return took or released


class TestWhatIsInIt:
    def test_one_button_per_tool(self) -> None:
        palette, tools = _palette()
        assert len(_buttons(palette)) == len(tools.tools)

    def test_each_button_says_what_its_tool_is_called(self) -> None:
        palette, _tools = _palette()
        assert [button.text for button in _buttons(palette)] \
            == ['Draw route', 'Pan/zoom', 'Sculpt']

    def test_it_is_as_wide_as_its_widest_label(self) -> None:
        narrow, _ = _palette(ToolManager([ToolMode(name='a', label='Go')]))
        wide, _ = _palette(ToolManager([
            ToolMode(name='a', label='A very much longer tool name')]))
        assert wide.rect.width > narrow.rect.width

    def test_an_empty_manager_makes_an_empty_strip(self) -> None:
        palette, _ = _palette(ToolManager([]))
        assert _buttons(palette) == []


class TestWhereItSits:
    def test_it_runs_down_the_left_of_the_window(self) -> None:
        palette, _ = _palette()
        assert palette.rect.x == 0

    def test_it_can_sit_on_the_right_instead(self) -> None:
        palette, _ = _palette(edge='right')
        assert palette.rect.right == VIEWPORT[0]

    def test_it_starts_below_whatever_is_reserved_above_it(self) -> None:
        """A menu bar takes the top of the window; the palette starts under it."""
        plain, _ = _palette()
        under, _ = _palette(reserved=40.0)
        assert under.rect.top < plain.rect.top

    def test_the_buttons_are_stacked_from_the_top_down(self) -> None:
        palette, _ = _palette()
        tops = [button.rect.top for button in _buttons(palette)]
        assert tops == sorted(tops, reverse=True)

    def test_every_button_is_the_same_width(self) -> None:
        palette, _ = _palette()
        assert len({button.rect.width for button in _buttons(palette)}) == 1


class TestTheRoomItTakes:
    def test_it_says_how_much_width_it_wants(self) -> None:
        """So a HUD beside it can keep that much clear of its read-outs."""
        palette, _tools = _palette()
        assert palette.room() > 0

    def test_a_longer_label_asks_for_more(self) -> None:
        narrow, _ = _palette(ToolManager([ToolMode(name='a', label='Go')]))
        wide, _ = _palette(ToolManager([
            ToolMode(name='a', label='A very much longer tool name')]))
        assert wide.room() > narrow.room()

    def test_an_empty_strip_still_answers(self) -> None:
        palette, _ = _palette(ToolManager([]))
        assert palette.room() >= 0

    def test_the_answer_is_in_reference_pixels_at_any_scale(self) -> None:
        """A HUD scales what it is told to keep clear, so this must not."""
        from OpenGLContext.ui.metrics import FontMetrics
        palette, _tools = _palette()
        doubled = FontMetrics(char_width=16, char_height=32, scale=2.0)
        assert palette.room(doubled) == pytest.approx(palette.room(), rel=0.15)


class TestChoosingATool:
    def test_clicking_a_button_puts_its_tool_in_force(self) -> None:
        palette, tools = _palette()
        sculpt = _buttons(palette)[2]
        _click(palette, *_centre(sculpt))
        assert tools.active is not None and tools.active.name == 'sculpt'

    def test_the_first_tool_is_in_force_to_begin_with(self) -> None:
        palette, tools = _palette()
        assert _buttons(palette)[0].active()
        assert not _buttons(palette)[1].active()

    def test_the_strip_follows_a_choice_made_elsewhere(self) -> None:
        """A keyboard shortcut or a menu can switch tools; the strip agrees."""
        palette, tools = _palette()
        tools.select('pan')
        assert _buttons(palette)[1].active()
        assert not _buttons(palette)[0].active()

    def test_a_tool_cannot_be_switched_out_of_a_gesture(self) -> None:
        """The manager refuses mid-drag, and the strip does not pretend."""
        palette, tools = _palette()

        class Holding(ToolMode):
            def on_press(self, pointer):
                return True

        tools.tools[0] = Holding(name='route', label='Draw route')
        tools.active = tools.tools[0]
        tools.press(Pointer())
        _click(palette, *_centre(_buttons(palette)[1]))
        assert tools.active.name == 'route'
        assert _buttons(palette)[0].active()


class TestWhatTheWorldBehindItHears:
    def test_a_click_on_a_button_is_taken(self) -> None:
        palette, _tools = _palette()
        assert _click(palette, *_centre(_buttons(palette)[0]))

    def test_a_click_on_the_strip_but_not_a_button_is_still_taken(self) -> None:
        """Otherwise it lands on the map underneath and draws something."""
        palette, _tools = _palette()
        bottom = palette.rect.y + 2
        assert palette.rect.contains(palette.rect.x + 2, bottom)
        assert _click(palette, palette.rect.x + 2, bottom)

    def test_a_click_beyond_the_strip_is_left_alone(self) -> None:
        palette, _tools = _palette()
        assert not _click(palette, palette.rect.right + 50, 300)

    def test_it_is_not_modal(self) -> None:
        """The map keeps working while the palette is on screen."""
        palette, _tools = _palette()
        assert not palette.modal
