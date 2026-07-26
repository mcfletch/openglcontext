"""Rows, columns and label/control grids -- one top-down pass, no solver."""

import pytest

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.layout import Column, Grid, Row
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import Button, Label, Select, Spacer


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


def box(width, height, **named):
    """A fixed-size child, so the arithmetic under test is the box's."""
    return Label(width=width, height=height, **named)


class TestRow:
    def test_children_run_left_to_right(self, metrics):
        a, b = box(20, 10), box(30, 10)
        row = Row(children=[a, b])
        row.arrange(Rect(0, 0, 100, 40), metrics)
        assert a.rect.x == 0
        assert b.rect.x == 20

    def test_spacing_separates_them(self, metrics):
        a, b = box(20, 10), box(30, 10)
        row = Row(children=[a, b], spacing=5)
        row.arrange(Rect(0, 0, 100, 40), metrics)
        assert b.rect.x == 25

    def test_a_row_asks_for_its_children_plus_the_gaps(self, metrics):
        row = Row(children=[box(20, 10), box(30, 12)], spacing=5)
        assert row.natural_size(metrics) == (55, 12)

    def test_padding_insets_the_children(self, metrics):
        child = box(20, 10)
        row = Row(children=[child], padding=8)
        row.arrange(Rect(0, 0, 100, 40), metrics)
        assert child.rect.x == 8
        assert child.rect.y == 8

    def test_a_flexible_child_takes_the_leftover(self, metrics):
        fixed, flexible = box(20, 10), box(20, 10, flex=1)
        row = Row(children=[fixed, flexible])
        row.arrange(Rect(0, 0, 100, 40), metrics)
        assert fixed.rect.width == 20
        assert flexible.rect.width == 80

    def test_two_flexible_children_share_in_proportion(self, metrics):
        one, two = box(0, 10, flex=1), box(0, 10, flex=3)
        row = Row(children=[one, two])
        row.arrange(Rect(0, 0, 100, 40), metrics)
        assert one.rect.width == 25
        assert two.rect.width == 75

    def test_a_row_with_nothing_flexible_starts_at_the_left(self, metrics):
        child = box(20, 10)
        row = Row(children=[child])
        row.arrange(Rect(0, 0, 100, 40), metrics)
        assert child.rect.x == 0

    def test_end_justification_pushes_to_the_right(self, metrics):
        child = box(20, 10)
        row = Row(children=[child], flexJustify='end')
        row.arrange(Rect(0, 0, 100, 40), metrics)
        assert child.rect.x == 80

    def test_centre_justification_centres_the_run(self, metrics):
        a, b = box(20, 10), box(20, 10)
        row = Row(children=[a, b], flexJustify='center')
        row.arrange(Rect(0, 0, 100, 40), metrics)
        assert a.rect.x == 30
        assert b.rect.x == 50

    def test_space_between_spreads_them_to_the_ends(self, metrics):
        a, b = box(20, 10), box(20, 10)
        row = Row(children=[a, b], flexJustify='space-between')
        row.arrange(Rect(0, 0, 100, 40), metrics)
        assert a.rect.x == 0
        assert b.rect.right == 100

    def test_children_stretch_across_by_default(self, metrics):
        child = box(20, 10)
        Row(children=[child]).arrange(Rect(0, 0, 100, 40), metrics)
        assert child.rect.height == 40

    def test_centre_alignment_keeps_the_natural_height(self, metrics):
        child = box(20, 10)
        Row(children=[child], align='center').arrange(Rect(0, 0, 100, 40), metrics)
        assert child.rect.height == 10
        assert child.rect.y == 15

    def test_an_invisible_child_takes_no_room(self, metrics):
        hidden, shown = box(20, 10, visible=False), box(30, 10)
        row = Row(children=[hidden, shown])
        row.arrange(Rect(0, 0, 100, 40), metrics)
        assert shown.rect.x == 0

    def test_an_empty_row_lays_out_without_complaint(self, metrics):
        row = Row()
        row.arrange(Rect(0, 0, 100, 40), metrics)
        assert row.natural_size(metrics) == (0, 0)

    def test_a_spacer_pushes_the_buttons_to_the_right(self, metrics):
        spacer, button = Spacer(), Button(text='Ok')
        row = Row(children=[spacer, button])
        row.arrange(Rect(0, 0, 300, 40), metrics)
        assert button.rect.right == 300


class TestColumn:
    def test_the_first_child_is_at_the_top(self, metrics):
        a, b = box(20, 10), box(20, 10)
        column = Column(children=[a, b])
        column.arrange(Rect(0, 0, 100, 100), metrics)
        assert a.rect.top == 100
        assert b.rect.top == 90

    def test_spacing_separates_the_rows(self, metrics):
        a, b = box(20, 10), box(20, 10)
        column = Column(children=[a, b], spacing=4)
        column.arrange(Rect(0, 0, 100, 100), metrics)
        assert b.rect.top == 86

    def test_a_column_asks_for_the_height_of_its_children(self, metrics):
        column = Column(children=[box(20, 10), box(30, 12)], spacing=4)
        assert column.natural_size(metrics) == (30, 26)

    def test_a_flexible_child_takes_the_leftover_height(self, metrics):
        fixed, flexible = box(20, 10), box(20, 10, flex=1)
        column = Column(children=[fixed, flexible])
        column.arrange(Rect(0, 0, 100, 100), metrics)
        assert flexible.rect.height == 90


class TestGrid:
    @pytest.fixture
    def grid(self, metrics):
        cells = [Label(text='Shadows'), Button(text='on'),
                 Label(text='Anti-aliasing'), Button(text='4x')]
        grid = Grid(children=cells, columns=2, spacing=4, columnSpacing=10)
        grid.arrange(Rect(0, 0, 400, 100), metrics)
        return grid

    def test_a_column_lines_up(self, grid):
        labels = [grid.children[0], grid.children[2]]
        assert labels[0].rect.x == labels[1].rect.x

    def test_the_second_column_clears_the_widest_label(self, grid, metrics):
        widest = metrics.text_width('Anti-aliasing')
        assert grid.children[1].rect.x >= widest

    def test_the_two_controls_line_up(self, grid):
        assert grid.children[1].rect.x == grid.children[3].rect.x

    def test_the_last_column_absorbs_the_leftover_width(self, grid):
        assert grid.children[1].rect.right == 400

    def test_the_second_row_is_below_the_first(self, grid):
        assert grid.children[2].rect.top < grid.children[0].rect.y + 1

    def test_a_grid_asks_for_its_columns_and_rows(self, metrics):
        grid = Grid(children=[box(20, 10), box(30, 12), box(25, 8), box(5, 20)],
                    columns=2, spacing=4, columnSpacing=6)
        assert grid.natural_size(metrics) == (25 + 6 + 30, 12 + 4 + 20)

    def test_a_short_last_row_is_allowed(self, metrics):
        grid = Grid(children=[box(20, 10), box(30, 12), box(25, 8)], columns=2)
        grid.arrange(Rect(0, 0, 200, 100), metrics)
        assert grid.children[2].rect.y < grid.children[0].rect.y

    def test_a_named_column_flex_overrides_the_default(self, metrics):
        cells = [box(20, 10), box(20, 10)]
        grid = Grid(children=cells, columns=2, columnSpacing=0, columnFlex=[1, 0])
        grid.arrange(Rect(0, 0, 200, 100), metrics)
        assert cells[0].rect.width == 180
        assert cells[1].rect.width == 20

    def test_an_empty_grid_lays_out_without_complaint(self, metrics):
        grid = Grid(columns=2)
        grid.arrange(Rect(0, 0, 100, 100), metrics)
        assert grid.natural_size(metrics) == (0, 0)

    def test_a_grid_of_one_column_still_works(self, metrics):
        cells = [box(20, 10), box(20, 10)]
        grid = Grid(children=cells, columns=1, spacing=0)
        grid.arrange(Rect(0, 0, 100, 100), metrics)
        assert cells[0].rect.top == 100
        assert cells[1].rect.top == 90

    def test_its_spacing_grows_with_the_interface_scale(self):
        cells = [box(20, 10), box(20, 10)]
        grid = Grid(children=cells, columns=1, spacing=6)
        grid.arrange(Rect(0, 0, 100, 200), FontMetrics(16, 32, 4, scale=2.0))
        assert cells[0].rect.y - cells[1].rect.top == 12


class TestGridRowsAreTargets:
    """A settings row has to read as one thing and be easy to hit."""

    @pytest.fixture
    def grid(self, metrics):
        cells = [Label(text='Shadows'), Button(text='on'),
                 Label(text='Bloom'), Button(text='off')]
        grid = Grid(children=cells, columns=2, spacing=6, rowPadding=8)
        grid.arrange(Rect(0, 0, 400, 300), metrics)
        return grid

    def test_padding_makes_each_row_taller_than_its_contents(self, grid):
        row = grid.rowRects()[0]
        assert row.height > grid.children[0].rect.height

    def test_a_row_spans_the_whole_grid(self, grid):
        row = grid.rowRects()[0]
        assert row.x == grid.rect.x and row.width == grid.rect.width

    def test_there_is_one_row_rectangle_per_row(self, grid):
        assert len(grid.rowRects()) == 2

    def test_the_rows_do_not_overlap(self, grid):
        first, second = grid.rowRects()
        assert second.top <= first.y

    def test_padding_is_asked_for_when_the_grid_is_measured(self, metrics):
        cells = [Label(text='a'), Label(text='b')]
        plain = Grid(children=list(cells), columns=2, spacing=0)
        padded = Grid(children=list(cells), columns=2, spacing=0, rowPadding=8)
        assert (padded.natural_size(metrics)[1]
                == plain.natural_size(metrics)[1] + 16)

    def test_a_hairline_is_drawn_between_the_rows(self, grid):
        painted = _Recorder()
        grid.paint(painted)
        assert len(painted.calls('rect')) == 1

    def test_none_is_drawn_above_the_first_row(self, metrics):
        """A rule at the very top reads as the edge of a table nobody drew."""
        grid = Grid(children=[Label(text='a'), Label(text='b')], columns=2)
        grid.arrange(Rect(0, 0, 400, 300), metrics)
        painted = _Recorder()
        grid.paint(painted)
        assert not painted.calls('rect')

    def test_the_row_the_pointer_is_on_is_washed(self, metrics):
        button = Button(text='on')
        grid = Grid(children=[Label(text='Shadows'), button,
                              Label(text='Bloom'), Button(text='off')],
                    columns=2)
        panel = Panel(children=[grid])
        panel.layout((400, 300), metrics)
        panel.pointer_moved(*button.rect.centre)
        painted = _Recorder()
        grid.paint(painted)
        # The wash over the hovered row, plus the hairline above the second.
        assert len(painted.calls('rect')) == 2

    def test_the_row_the_keyboard_is_in_is_washed(self, metrics):
        from OpenGLContext.ui.panel import Panel
        button = Button(text='on')
        grid = Grid(children=[Label(text='Shadows'), button], columns=2)
        panel = Panel(children=[grid])
        panel.layout((400, 300), metrics)
        panel.focus(button)
        painted = _Recorder()
        grid.paint(painted)
        assert painted.calls('rect')

    def test_an_untouched_grid_washes_nothing(self, metrics):
        grid = Grid(children=[Label(text='a'), Label(text='b')], columns=2)
        grid.arrange(Rect(0, 0, 400, 300), metrics)
        painted = _Recorder()
        grid.paint(painted)
        assert not painted.calls('rect')

    def test_the_rows_move_with_the_content_when_it_scrolls(self, grid):
        """Row rectangles come from the cells, which a scroll has already moved."""
        from OpenGLContext.ui.scroll import _offsetTree
        before = grid.rowRects()[0].y
        _offsetTree(grid, 0, 37)
        assert grid.rowRects()[0].y == before + 37


class _Recorder:
    """A renderer that records what it was asked to draw."""

    def __init__(self):
        from OpenGLContext.ui.skin import DEFAULT_SKIN
        self.metrics = FontMetrics(8, 16, 2)
        self.skin = DEFAULT_SKIN
        self.recorded = []

    def calls(self, name):
        return [arguments for called, arguments in self.recorded
                if called == name]

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)

        def record(*arguments, **named):
            self.recorded.append((name, arguments))
        return record


class TestAGridFitsTheRoomItHas:
    """Controls stay inside the grid when the natural columns do not fit.

    Overflowing puts a control over the scrollbar or outside the panel, where
    it can still be clicked but cannot be seen.  A grid has slack a box does
    not: the label column is the one that can give.
    """

    def _grid(self, width, metrics):
        grid = Grid(children=[Label(text='A very long setting name indeed'),
                              Button(text='Change'),
                              Label(text='Another long setting name'),
                              Button(text='Change')],
                    columns=2, columnSpacing=8.0)
        grid.arrange(Rect(0, 0, width, 200), metrics)
        return grid

    def test_cells_stay_inside_a_narrow_grid(self, metrics):
        grid = self._grid(120, metrics)
        for cell in grid.layoutChildren():
            assert cell.rect.right <= grid.rect.right, cell.text

    def test_the_control_column_keeps_a_usable_width(self, metrics):
        grid = self._grid(120, metrics)
        buttons = [c for c in grid.layoutChildren() if isinstance(c, Button)]
        assert all(b.rect.width > 0 for b in buttons)

    def test_a_roomy_grid_is_unchanged(self, metrics):
        grid = self._grid(900, metrics)
        for cell in grid.layoutChildren():
            assert cell.rect.right <= grid.rect.right


class TestRowHighlightsAreNotRecomputedPerFrame:
    """Hover and focus change at one point each; paint should read, not search.

    A grid that walked every widget in every cell on every frame would be
    doing, per frame, work the layout deliberately does only on a change.
    """

    def test_the_hovered_row_is_known_without_walking_the_tree(self, metrics):
        panel = Panel(children=[Grid(children=[Label(text='a'),
                                              Button(text='b'),
                                              Label(text='c'),
                                              Button(text='d')], columns=2)])
        panel.layout((400, 300), metrics)
        grid = panel.children[0]
        second = grid.layoutChildren()[3]
        panel.pointer_moved(*second.rect.centre)
        assert grid.activeRows()[0] == 1

    def test_nothing_is_highlighted_before_the_pointer_arrives(self, metrics):
        panel = Panel(children=[Grid(children=[Label(text='a'),
                                              Button(text='b')], columns=2)])
        panel.layout((400, 300), metrics)
        assert panel.children[0].activeRows() == (None, None)

    def test_the_focused_row_follows_the_keyboard(self, metrics):
        panel = Panel(children=[Grid(children=[Label(text='a'),
                                              Button(text='b'),
                                              Label(text='c'),
                                              Button(text='d')], columns=2)])
        panel.layout((400, 300), metrics)
        grid = panel.children[0]
        panel.focus(grid.layoutChildren()[3])
        assert grid.activeRows()[1] == 1


class TestWrappedTextInARow:
    """A row can offer its children a width to measure against.

    A row cannot hand its width down before the flexible shares are settled,
    so wrapped text used to measure against a stale rectangle -- zero on the
    first layout -- and report a height for one very long line.  Two passes fix
    it: measure to settle the shares, then re-measure the wrapping children
    against the widths they actually got.
    """

    def test_a_wrapped_label_in_a_row_gets_a_real_height(self, metrics):
        label = Label(text='a wrapped label with a good many words in it',
                      wrap=True)
        row = Row(children=[label])
        row.arrange(Rect(0, 0, 160, 200), metrics)
        assert label.rect.width <= 160
        lines = metrics.wrap(label.text, label.rect.width)
        assert len(lines) > 1
        assert label.natural_size(metrics, label.rect.width)[1] \
            == metrics.lines_size(lines)[1]

    def test_the_row_is_tall_enough_for_the_wrapped_text(self, metrics):
        label = Label(text='a wrapped label with a good many words in it',
                      wrap=True)
        row = Row(children=[label])
        wanted = row.natural_size(metrics, 160)[1]
        assert wanted >= metrics.lines_size(metrics.wrap(label.text, 160))[1]

    def test_an_unwrapped_row_is_unchanged(self, metrics):
        row = Row(children=[Label(text='abc'), Label(text='defg')])
        row.arrange(Rect(0, 0, 400, 100), metrics)
        assert row.natural_size(metrics)[0] == 7 * metrics.char_width


class TestDistributeLeavesItsArgumentAlone:
    """The sizes a caller measured are still the sizes it measured."""

    def test_the_caller_s_list_is_not_written_through(self):
        from OpenGLContext.hud import distribute
        row = Row(children=[Spacer(), Spacer()])
        measured = [10, 10]
        distribute(row.layoutChildren(), measured, 80)
        assert measured == [10, 10]

    def test_the_shares_still_come_back(self):
        from OpenGLContext.hud import distribute
        row = Row(children=[Spacer(), Spacer()])
        assert sum(distribute(row.layoutChildren(), [10, 10], 80)) == 100

    def test_nothing_flexible_gives_the_sizes_back_unchanged(self):
        from OpenGLContext.hud import distribute
        row = Row(children=[Label(text='a'), Label(text='b')])
        measured = [10, 20]
        assert distribute(row.layoutChildren(), measured, 80) == [10, 20]
        assert measured == [10, 20]


class TestSelectActivatesItself:
    def test_releasing_runs_the_widget_s_own_activate(self, metrics):
        """A subclass adding an activate() must not be silently bypassed."""
        seen = []

        class Counting(Select):
            PROTO = 'UITestCountingSelect'

            def activate(self):
                seen.append(1)
                super().activate()

        select = Counting(options=['a', 'b'])
        select.arrange(Rect(0, 0, 120, 24), metrics)
        select.press(*select.rect.centre)
        select.release(*select.rect.centre)
        assert seen == [1]
