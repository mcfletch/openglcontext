"""Rows, columns and label/control grids -- one top-down pass, no solver."""

import pytest

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.layout import Column, Grid, Row
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.widgets import Button, Label, Spacer


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
