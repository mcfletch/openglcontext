"""Which colour each vertex of an IndexedLineSet takes
(:func:`OpenGLContext.scenegraph.indexedlineset.polyline_color_indices`)."""
from OpenGLContext.scenegraph.indexedlineset import polyline_color_indices

POLYLINES = [[0, 1, 3, 2, 0], [1, 4]]


def test_per_polyline_by_color_index():
    assert polyline_color_indices(POLYLINES, [1, 0], False, 2) == [[1] * 5, [0] * 2]


def test_per_polyline_entries_past_the_polylines_are_not_read():
    """X3dForWebAuthors ElevationGridNonPlanarQuadrilaterals: four entries, one polyline"""
    assert polyline_color_indices(POLYLINES[:1], [0, 0, 0, 0], False, 1) == [[0] * 5]


def test_per_polyline_without_color_index_in_turn():
    assert polyline_color_indices(POLYLINES, [], False, 3) == [[0] * 5, [1] * 2]


def test_per_polyline_missing_an_entry_takes_its_own_number():
    assert polyline_color_indices(POLYLINES, [1], False, 3) == [[1] * 5, [1] * 2]


def test_per_vertex_by_color_index_read_as_coord_index():
    assert polyline_color_indices(POLYLINES, [0, 1, 2, 0, 1, -1, 2, 2, -1], True, 3) == [
        [0, 1, 2, 0, 1], [2, 2]]


def test_per_vertex_without_color_index_by_coord_index():
    assert polyline_color_indices(POLYLINES, [], True, 5) == POLYLINES


def test_per_vertex_short_entries_carry_the_last_on():
    assert polyline_color_indices(POLYLINES, [0, 1, -1], True, 5) == [[0, 1, 1, 1, 1], [1, 4]]


def test_an_index_past_the_colours_takes_the_last_colour():
    assert polyline_color_indices(POLYLINES, [], True, 2) == [[0, 1, 1, 1, 0], [1, 1]]
