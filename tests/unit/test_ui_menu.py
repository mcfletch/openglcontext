"""Menus: a short list of things to do, opened at a point.

Headless. A menu is a panel, an item is a widget, and both are laid out against
a font metric and hit-tested against a rectangle -- none of which needs a
window. What is asserted here is where the menu ends up, what the pointer and
the keyboard reach, and that choosing something both does it and puts the menu
away.
"""
import pytest

from OpenGLContext.ui.menu import Menu, MenuBar, MenuItem
from OpenGLContext.ui.metrics import REFERENCE_METRICS
from OpenGLContext.ui.overlay import OverlayStack

VIEWPORT = (1280, 720)


def _menu(items=None, **named):
    chosen = []
    items = items if items is not None else [
        MenuItem(text='Open', shortcut='<ctrl-o>'),
        MenuItem(text='Save'),
        MenuItem(text='Quit'),
    ]
    for item in items:
        if isinstance(item, MenuItem):
            item.on_activate = lambda widget: chosen.append(widget.text)
    menu = Menu(items=items, **named)
    menu.layout(VIEWPORT, REFERENCE_METRICS)
    return menu, chosen


def _rows(menu):
    return [widget for widget in menu.walk() if isinstance(widget, MenuItem)]


class TestWhereItOpens:
    def test_its_corner_is_where_it_was_asked_for(self) -> None:
        menu, _ = _menu(anchor=(300.0, 500.0))
        assert menu.rect.x == 300
        assert menu.rect.top == 500

    def test_it_hangs_down_from_the_anchor(self) -> None:
        menu, _ = _menu(anchor=(300.0, 500.0))
        assert menu.rect.y < 500

    def test_it_stays_inside_the_window_on_the_right(self) -> None:
        menu, _ = _menu(anchor=(VIEWPORT[0] - 10.0, 500.0))
        assert menu.rect.x + menu.rect.width <= VIEWPORT[0]

    def test_a_menu_that_would_run_off_the_bottom_opens_upwards(self) -> None:
        """Rather than being pushed up and covering what was clicked."""
        menu, _ = _menu(anchor=(300.0, 20.0))
        assert menu.rect.y >= 0
        assert menu.rect.y >= 20 - 1

    def test_it_is_as_wide_as_its_widest_item(self) -> None:
        narrow, _ = _menu([MenuItem(text='Go')])
        wide, _ = _menu([MenuItem(text='A very much longer thing to do')])
        assert wide.rect.width > narrow.rect.width

    def test_a_shortcut_makes_room_for_itself(self) -> None:
        bare, _ = _menu([MenuItem(text='Save')])
        keyed, _ = _menu([MenuItem(text='Save', shortcut='<ctrl-s>')])
        assert keyed.rect.width > bare.rect.width

    def test_every_item_is_the_same_width(self) -> None:
        menu, _ = _menu([MenuItem(text='Go'), MenuItem(text='Somewhere else')])
        widths = {row.rect.width for row in _rows(menu)}
        assert len(widths) == 1

    def test_the_items_are_in_order_down_the_screen(self) -> None:
        menu, _ = _menu()
        tops = [row.rect.top for row in _rows(menu)]
        assert tops == sorted(tops, reverse=True)


class TestChoosingWithThePointer:
    def test_a_click_runs_the_item(self) -> None:
        menu, chosen = _menu()
        row = _rows(menu)[1]
        menu.pointer_pressed(row.rect.x + 4, row.rect.y + 2)
        menu.pointer_released(row.rect.x + 4, row.rect.y + 2)
        assert chosen == ['Save']

    def test_choosing_puts_the_menu_away(self) -> None:
        menu, _ = _menu()
        row = _rows(menu)[0]
        menu.pointer_pressed(row.rect.x + 4, row.rect.y + 2)
        menu.pointer_released(row.rect.x + 4, row.rect.y + 2)
        assert menu.closed

    def test_a_click_outside_puts_it_away_without_choosing(self) -> None:
        """Looking away is how a menu is dismissed."""
        menu, chosen = _menu(anchor=(300.0, 500.0))
        assert menu.pointer_pressed(10.0, 10.0) is True   # taken, not passed on
        assert menu.closed and chosen == []

    def test_hovering_lights_the_row_under_the_pointer(self) -> None:
        menu, _ = _menu()
        row = _rows(menu)[2]
        menu.pointer_moved(row.rect.x + 4, row.rect.y + 2)
        assert row.hovered

    def test_a_disabled_item_does_nothing(self) -> None:
        menu, chosen = _menu([MenuItem(text='Undo', enabled=False),
                              MenuItem(text='Redo')])
        row = _rows(menu)[0]
        menu.pointer_pressed(row.rect.x + 4, row.rect.y + 2)
        menu.pointer_released(row.rect.x + 4, row.rect.y + 2)
        assert chosen == [] and not menu.closed


class TestChoosingWithTheKeyboard:
    def test_down_walks_to_the_first_item(self) -> None:
        menu, _ = _menu()
        menu.key('<down>', (0, 0, 0))
        assert menu.focused_widget is _rows(menu)[0]

    def test_down_again_walks_on(self) -> None:
        menu, _ = _menu()
        menu.key('<down>', (0, 0, 0))
        menu.key('<down>', (0, 0, 0))
        assert menu.focused_widget is _rows(menu)[1]

    def test_return_runs_what_is_highlighted(self) -> None:
        menu, chosen = _menu()
        menu.key('<down>', (0, 0, 0))
        menu.key('<return>', (0, 0, 0))
        assert chosen == ['Open'] and menu.closed

    def test_escape_puts_it_away(self) -> None:
        menu, chosen = _menu()
        menu.key('<escape>', (0, 0, 0))
        assert menu.closed and chosen == []

    def test_a_shortcut_runs_its_item_from_anywhere_in_the_menu(self) -> None:
        menu, chosen = _menu()
        menu.key('<ctrl-o>', (0, 0, 0))
        assert chosen == ['Open']

    def test_a_separator_is_stepped_over(self) -> None:
        from OpenGLContext.ui.widgets import Separator
        menu, _ = _menu([MenuItem(text='Cut'), Separator(),
                         MenuItem(text='Paste')])
        menu.key('<down>', (0, 0, 0))
        menu.key('<down>', (0, 0, 0))
        assert menu.focused_widget is _rows(menu)[1]


class TestAnItemThatSaysSomethingAboutItself:
    def test_a_check_shows_when_it_is_on(self) -> None:
        item = MenuItem(text='Wireframe', checkable=True, checked=True)
        assert item.mark() == MenuItem.CHECKED

    def test_a_check_shows_as_empty_when_it_is_off(self) -> None:
        item = MenuItem(text='Wireframe', checkable=True, checked=False)
        assert item.mark() == MenuItem.UNCHECKED

    def test_an_ordinary_item_has_no_mark(self) -> None:
        assert MenuItem(text='Save').mark() == ''

    def test_a_checkable_item_toggles_when_chosen(self) -> None:
        item = MenuItem(text='Wireframe', checkable=True, checked=False)
        menu, _ = _menu([item])
        item.activate()
        assert item.checked

    def test_a_submenu_says_there_is_more(self) -> None:
        item = MenuItem(text='Recent', submenu=[MenuItem(text='a.wrl')])
        assert item.mark() == MenuItem.SUBMENU


class TestASubmenu:
    def _with_submenu(self):
        stack = OverlayStack()
        inner = [MenuItem(text='a.wrl'), MenuItem(text='b.wrl')]
        item = MenuItem(text='Recent', submenu=inner)
        menu = Menu(items=[MenuItem(text='Open'), item], stack=stack)
        stack.push(menu, VIEWPORT, REFERENCE_METRICS)
        return stack, menu, item

    def test_choosing_it_opens_the_second_menu(self) -> None:
        stack, _menu, item = self._with_submenu()
        item.activate()
        assert isinstance(stack.top, Menu)
        assert [row.text for row in _rows(stack.top)] == ['a.wrl', 'b.wrl']

    def test_the_parent_stays_open_behind_it(self) -> None:
        stack, menu, item = self._with_submenu()
        item.activate()
        assert not menu.closed
        assert len(stack.panels) == 2

    def test_it_opens_beside_the_item_not_over_it(self) -> None:
        stack, menu, item = self._with_submenu()
        item.activate()
        assert stack.top.rect.x >= menu.rect.x + menu.rect.width - 1

    def test_choosing_in_the_submenu_closes_the_whole_stack(self) -> None:
        """A menu that stays up after the thing was done is in the way."""
        stack, menu, item = self._with_submenu()
        item.activate()
        _rows(stack.top)[0].activate()
        assert menu.closed
        assert not [p for p in stack.panels if isinstance(p, Menu)]


class TestTheMenuBar:
    def _bar(self):
        stack = OverlayStack()
        bar = MenuBar(menus=[
            ('File', [MenuItem(text='Open'), MenuItem(text='Quit')]),
            ('Edit', [MenuItem(text='Undo')]),
        ], stack=stack)
        bar.layout(VIEWPORT, REFERENCE_METRICS)
        return stack, bar

    def test_it_runs_along_the_top_of_the_window(self) -> None:
        _stack, bar = self._bar()
        assert bar.rect.top == VIEWPORT[1]
        assert bar.rect.width == VIEWPORT[0]

    def test_it_is_one_row_tall(self) -> None:
        _stack, bar = self._bar()
        assert bar.rect.height < REFERENCE_METRICS.line_height * 3

    def test_the_titles_are_in_order_across_it(self) -> None:
        _stack, bar = self._bar()
        titles = [w for w in bar.walk() if isinstance(w, MenuItem)]
        assert [t.text for t in titles] == ['File', 'Edit']
        assert titles[0].rect.x < titles[1].rect.x

    def test_clicking_a_title_opens_its_menu_under_it(self) -> None:
        stack, bar = self._bar()
        title = [w for w in bar.walk() if isinstance(w, MenuItem)][0]
        title.activate()
        opened = stack.top
        assert isinstance(opened, Menu)
        assert opened.rect.top <= title.rect.y + 1
        assert [row.text for row in _rows(opened)] == ['Open', 'Quit']

    def test_it_lets_the_world_have_a_click_that_missed_it(self) -> None:
        """A bar across the top is not a wall across the window."""
        _stack, bar = self._bar()
        assert bar.pointer_pressed(400.0, 300.0) is False

    def test_it_is_not_modal(self) -> None:
        _stack, bar = self._bar()
        assert not bar.modal


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestReachingEveryItem:
    """A key and a menu item often do the same thing, and the tick has to
    follow either of them. A bar title's list is its ``submenu``, which is not
    among its children until the list is opened -- by which time the tick is
    already wrong."""

    def _bar(self):
        return MenuBar(menus=[
            ('File', [MenuItem(text='Open'), MenuItem(text='Quit')]),
            ('View', [MenuItem(text='Shaded relief', checkable=True),
                      MenuItem(text='Contours', submenu=[
                          MenuItem(text='10 m'), MenuItem(text='25 m')])]),
        ])

    def test_it_reaches_the_titles(self) -> None:
        found = [item.text for item in self._bar().allItems()]
        assert 'File' in found and 'View' in found

    def test_it_reaches_the_lists_under_them(self) -> None:
        found = [item.text for item in self._bar().allItems()]
        assert 'Shaded relief' in found

    def test_it_reaches_a_list_under_a_list(self) -> None:
        found = [item.text for item in self._bar().allItems()]
        assert '25 m' in found

    def test_a_bar_with_nothing_in_it_reaches_nothing(self) -> None:
        assert list(MenuBar(menus=[]).allItems()) == []

    def test_what_it_finds_can_be_ticked(self) -> None:
        bar = self._bar()
        for item in bar.allItems():
            if item.text == 'Shaded relief':
                item.checked = True
        assert [item.checked for item in bar.allItems()
                if item.text == 'Shaded relief'] == [True]
