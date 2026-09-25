"""Menus: a short list of things to do, opened at a point.

Headless. A menu is a panel, an item is a widget, and both are laid out against
a font metric and hit-tested against a rectangle -- none of which needs a
window. What is asserted here is where the menu ends up, what the pointer and
the keyboard reach, and that choosing something both does it and puts the menu
away.
"""
import pytest

from OpenGLContext.events import systemtime
from OpenGLContext.ui.menu import Menu, MenuBar, MenuItem
from OpenGLContext.ui.metrics import REFERENCE_METRICS, FontMetrics
from OpenGLContext.ui.widgets import Separator
from OpenGLContext.ui.overlay import OverlayStack

VIEWPORT = (1280, 720)

#: Long after anything a menu does over time has finished.
_LATER = 1e12


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

    def test_upwards_it_opens_over_what_was_clicked_not_across_it(self) -> None:
        """A control 30 pixels tall: the list sits on its top edge."""
        menu, _ = _menu(anchor=(300.0, 20.0), above=50.0)
        assert menu.rect.y == 50

    def test_one_with_room_neither_way_stays_inside_the_window(self) -> None:
        many = [MenuItem(text='Row %d' % index) for index in range(20)]
        menu, _ = _menu(many, anchor=(300.0, 300.0), above=330.0)
        assert menu.rect.y >= 0 and menu.rect.top <= VIEWPORT[1]

    def test_one_taller_than_the_window_starts_at_its_top(self) -> None:
        many = [MenuItem(text='Row %d' % index) for index in range(80)]
        menu, _ = _menu(many, anchor=(300.0, 300.0))
        assert menu.rect.top == VIEWPORT[1]

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
        menu.tick(_LATER)
        assert menu.closed

    def test_it_stays_up_long_enough_to_show_what_was_chosen(self) -> None:
        """The row's ripple is the answer to the click; a menu gone at once hides it."""
        menu, chosen = _menu(linger=0.2)
        row = _rows(menu)[0]
        menu.pointer_pressed(row.rect.x + 4, row.rect.y + 2)
        menu.pointer_released(row.rect.x + 4, row.rect.y + 2)
        assert chosen == ['Open']                 # done at once
        assert not menu.closed and menu.animating(systemtime.systemTime())
        menu.tick(systemtime.systemTime() + 0.5)
        assert menu.closed

    def test_while_it_lingers_nothing_more_can_be_chosen(self) -> None:
        menu, chosen = _menu(linger=0.2)
        first, second = _rows(menu)[0], _rows(menu)[1]
        menu.pointer_pressed(*first.rect.centre)
        menu.pointer_released(*first.rect.centre)
        menu.pointer_pressed(*second.rect.centre)
        menu.pointer_released(*second.rect.centre)
        menu.character('s')
        assert chosen == ['Open']

    def test_one_that_does_not_linger_goes_at_once(self) -> None:
        menu, _ = _menu(linger=0.0)
        row = _rows(menu)[0]
        menu.pointer_pressed(*row.rect.centre)
        menu.pointer_released(*row.rect.centre)
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
        assert row.hovered and row.highlighted()

    def test_the_keyboard_follows_the_pointer(self) -> None:
        """One highlight, not one for the pointer and another for the keys."""
        menu, _ = _menu()
        rows = _rows(menu)
        menu.pointer_moved(*rows[1].rect.centre)
        assert menu.focused_widget is rows[1]
        menu.key('<down>', (0, 0, 0))
        assert menu.focused_widget is rows[2]
        assert rows[2].highlighted() and not rows[1].highlighted()

    def test_a_row_the_pointer_left_for_the_keys_is_not_lit(self) -> None:
        menu, _ = _menu()
        rows = _rows(menu)
        menu.pointer_moved(*rows[0].rect.centre)
        menu.key('<down>', (0, 0, 0))
        assert not rows[0].highlighted()

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
        menu.tick(_LATER)
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
        stack.tick(_LATER)
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


class TestItsAccessKeys:
    """A letter per row, typed while the menu is up."""

    def _keyed(self, texts, **named):
        return _menu([MenuItem(text=text) for text in texts], **named)

    def test_each_row_is_given_a_letter_of_its_own(self) -> None:
        menu, _ = self._keyed(['Top', 'Front', 'Left', 'Four tiles', 'Fit'])
        keys = [row.accessKey() for row in _rows(menu)]
        assert all(keys) and len(set(keys)) == len(keys)
        for row, key in zip(_rows(menu), keys, strict=True):
            assert key in str(row.text).lower()

    def test_the_first_letter_of_a_word_is_preferred(self) -> None:
        menu, _ = self._keyed(['Front', 'Four tiles'])
        assert [row.accessKey() for row in _rows(menu)] == ['f', 't']

    def test_typing_it_runs_the_row(self) -> None:
        menu, chosen = self._keyed(['Open', 'Save', 'Quit'], linger=0.0)
        assert menu.character('s') is True
        assert chosen == ['Save'] and menu.closed

    def test_it_is_the_same_letter_in_capitals(self) -> None:
        menu, chosen = self._keyed(['Open', 'Save', 'Quit'])
        menu.character('Q')
        assert chosen == ['Quit']

    def test_a_letter_no_row_has_does_nothing(self) -> None:
        menu, chosen = self._keyed(['Open', 'Save'])
        assert menu.character('z') is False
        assert chosen == [] and not menu.closed

    def test_a_row_can_name_its_own(self) -> None:
        menu, chosen = _menu([MenuItem(text='Open', mnemonic='p'),
                              MenuItem(text='Print')])
        assert [row.accessKey() for row in _rows(menu)] == ['p', 'r']
        menu.character('p')
        assert chosen == ['Open']

    def test_a_disabled_row_is_not_run(self) -> None:
        menu, chosen = _menu([MenuItem(text='Undo', enabled=False)])
        assert menu.character('u') is False
        assert chosen == []

    def test_a_menu_can_go_without(self) -> None:
        menu, chosen = self._keyed(['Open', 'Save'], mnemonics=False)
        assert [row.accessKey() for row in _rows(menu)] == ['', '']
        assert menu.character('o') is False

    def test_the_letter_is_where_the_row_draws_its_underline(self) -> None:
        menu, _ = self._keyed(['Four tiles', 'Front'])
        row = _rows(menu)[0]
        assert row.accessIndex() == str(row.text).lower().index(row.accessKey())


class TestAPopUpMenu:
    """Opened at a point by one call, with nothing else to wire."""

    def test_the_stack_it_is_pushed_on_is_where_its_submenus_open(self) -> None:
        stack = OverlayStack()
        item = MenuItem(text='Recent', submenu=[MenuItem(text='a.wrl')])
        menu = Menu(anchor=(100.0, 400.0), items=[item])
        stack.push(menu, VIEWPORT, REFERENCE_METRICS)
        item.activate()
        assert isinstance(stack.top, Menu) and stack.top is not menu

    def test_a_stack_it_was_given_is_kept(self) -> None:
        mine, other = OverlayStack(), OverlayStack()
        menu = Menu(items=[MenuItem(text='Go')], stack=mine)
        other.push(menu)
        assert menu.stack is mine


class _Recorder:
    """Records the drawing calls a widget makes."""

    def __init__(self, skin, metrics):
        self.skin = skin
        self.metrics = metrics
        self.now = None
        self.calls = []

    def __getattr__(self, name):
        def record(*arguments, **_named):
            self.calls.append((name, arguments))
        return record

    def named(self, name):
        return [arguments for called, arguments in self.calls if called == name]


class TestHowARowIsDrawn:
    """The text in the middle of its row, whatever the padding."""

    #: The size-16 atlas: a 21-pixel cell whose baseline is 16 down from its top.
    METRICS = FontMetrics(12, 21, 2, scale=21 / 16, baseline=16)

    def _row(self, **named):
        menu = Menu(items=[MenuItem(text='Wireframe', **named),
                           Separator(), MenuItem(text='Maximise')])
        menu.layout(VIEWPORT, self.METRICS)
        row = menu.items()[0]
        renderer = _Recorder(row.activeSkin(), self.METRICS)
        row.paint(renderer)
        return menu, row, renderer

    def test_the_text_is_centred_in_the_row(self) -> None:
        _menu_, row, renderer = self._row()
        body = [args[0] for args in renderer.named('textIn')
                if args[1] == 'Wireframe'][0]
        assert body.y == row.rect.y and body.height == row.rect.height

    def test_the_access_key_is_underlined_just_under_the_letters(self) -> None:
        _menu_, row, renderer = self._row()
        cell_bottom = row.rect.y + (row.rect.height - self.METRICS.char_height) // 2
        underline = renderer.named('rect')[-1][0]
        assert underline.height == 1
        # One pixel of gap under the baseline, which is five above the cell's bottom.
        assert underline.y == cell_bottom + 3

    def test_a_separator_has_room_either_side_of_its_line(self) -> None:
        menu, row, _renderer = self._row()
        separator = [child for child in menu.layoutChildren()
                     if isinstance(child, Separator)][0]
        assert separator.rect.height > 3
        assert separator.rect.top == row.rect.y
        renderer = _Recorder(menu.activeSkin(), self.METRICS)
        separator.paint(renderer)
        line = renderer.named('rect')[0][0]
        assert line.height == 1
        assert abs(line.centre[1] - separator.rect.centre[1]) <= 1
