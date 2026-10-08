"""Tests for snippetatlas, which packs drawn text into atlas pages."""
import itertools

import pytest

from OpenGLContext.scenegraph.text.snippetatlas import SnippetAtlas


def overlaps(a, b):
    return (a.page == b.page and a.x < b.x + b.width and b.x < a.x + a.width
            and a.y < b.y + b.height and b.y < a.y + a.height)


def test_a_placed_snippet_is_found_again():
    atlas = SnippetAtlas(page_size=256, pages=2)
    placed = atlas.place('hello', 40, 12)
    assert atlas.find('hello') == placed
    assert atlas.find('other') is None


def test_snippets_never_overlap():
    atlas = SnippetAtlas(page_size=256, pages=4)
    placed = [atlas.place(index, 10 + (index * 37) % 90, 6 + (index * 13) % 30)
              for index in range(120)]
    for a, b in itertools.combinations(placed, 2):
        assert not overlaps(a, b), (a, b)
    for each in placed:
        assert each.x + each.width <= 256 and each.y + each.height <= 256


def test_snippets_of_like_height_share_a_shelf():
    atlas = SnippetAtlas(page_size=256, pages=1)
    first, second = atlas.place('a', 30, 14), atlas.place('b', 30, 15)
    assert first.y == second.y and second.x >= first.x + first.width


def test_the_least_recently_used_page_is_cleared_when_full():
    atlas = SnippetAtlas(page_size=64, pages=2)
    atlas.place('old', 60, 60)
    atlas.tick()
    atlas.place('kept', 60, 60)
    atlas.tick()
    assert atlas.find('kept') is not None
    newest = atlas.place('new', 60, 60)
    assert atlas.find('old') is None
    assert atlas.find('kept') is not None
    assert newest.page == 0


def test_a_page_in_use_this_frame_is_not_cleared():
    """Everything on screen keeps its place; the atlas takes another page"""
    atlas = SnippetAtlas(page_size=64, pages=1)
    atlas.place('shown', 60, 60)
    other = atlas.place('also shown', 60, 60)
    assert atlas.find('shown') is not None and other.page == 1
    assert atlas.pages == 2


def test_a_snippet_larger_than_a_page_is_refused():
    with pytest.raises(ValueError):
        SnippetAtlas(page_size=64, pages=1).place('wide', 65, 10)


def test_texture_coordinates_cover_the_snippet():
    atlas = SnippetAtlas(page_size=128, pages=1)
    placed = atlas.place('x', 32, 16)
    u0, v0, u1, v1 = placed.texcoords(128)
    assert (u1 - u0, v1 - v0) == (0.25, 0.125)
    assert (u0, v0) == (placed.x / 128, placed.y / 128)


def test_a_payload_is_kept_while_the_snippet_is_placed():
    atlas = SnippetAtlas(page_size=64, pages=1)
    atlas.place('old', 60, 60, payload=(1, 2))
    assert atlas.payload('old') == (1, 2)
    atlas.tick()
    atlas.place('new', 60, 60)
    assert atlas.payload('old') is None
