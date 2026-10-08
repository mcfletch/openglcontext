"""Packs snippets of drawn text into square atlas pages; no GL

Each snippet has a key (its face, pixel em and text) and a size in texels,
and is placed on a shelf of snippets of like height. A snippet is marked with
the frame it was last asked for (:meth:`SnippetAtlas.tick` advances the
frame). When no page has room, the least recently used page is cleared and
its snippets are placed again when next asked for; a page used in the
current frame is never cleared, and the atlas takes another page instead.
"""
from __future__ import annotations

from collections.abc import Hashable
from typing import Any, NamedTuple, Optional

__all__ = ['Placement', 'SnippetAtlas']

#: Shelf heights are this many texels apart, so a shelf takes snippets up to
#: this much shorter than itself.
SHELF_STEP = 8


class Placement(NamedTuple):
    """Where a snippet is in the atlas, in texels on its page"""

    page: int
    x: int
    y: int
    width: int
    height: int

    def texcoords(self, page_size: int) -> tuple[float, float, float, float]:
        """(u0, v0, u1, v1) of the snippet's corners on a page `page_size` texels wide"""
        return (self.x / page_size, self.y / page_size,
                (self.x + self.width) / page_size, (self.y + self.height) / page_size)


class _Shelf:
    """A row of a page holding snippets up to its height, filled left to right"""

    def __init__(self, y: int, height: int) -> None:
        self.y = y
        self.height = height
        self.used = 0


class _Page:
    """A page's shelves, the snippets on it, and the frame it was last used"""

    def __init__(self) -> None:
        self.shelves: list[_Shelf] = []
        self.keys: set[Hashable] = set()
        self.used = -1

    def top(self) -> int:
        return self.shelves[-1].y + self.shelves[-1].height if self.shelves else 0


class SnippetAtlas:
    """The places of snippets of drawn text on pages `page_size` texels square

    `pages` is how many pages are kept before the least recently used is
    cleared to make room.
    """

    def __init__(self, page_size: int = 2048, pages: int = 4) -> None:
        self.page_size = page_size
        self.limit = pages
        self.frame = 0
        self._pages: list[_Page] = []
        self._placed: dict[Hashable, Placement] = {}
        self._payloads: dict[Hashable, Any] = {}

    @property
    def pages(self) -> int:
        """How many pages the atlas has"""
        return len(self._pages)

    def tick(self) -> None:
        """Start the next frame"""
        self.frame += 1

    def find(self, key: Hashable) -> Optional[Placement]:
        """Where the snippet `key` is, marked as used this frame; None where it is not"""
        found = self._placed.get(key)
        if found is not None:
            self._pages[found.page].used = self.frame
        return found

    def payload(self, key: Hashable) -> Any:
        """What was placed with the snippet `key`; None where it is not placed"""
        return self._payloads.get(key)

    def place(self, key: Hashable, width: int, height: int, payload: Any = None) -> Placement:
        """A new place for the snippet `key`, `width` by `height` texels, kept
        with `payload` while it is placed

        Raises ValueError for a snippet larger than a page.
        """
        if width > self.page_size or height > self.page_size:
            raise ValueError('a %dx%d snippet does not fit a %d texel page'
                             % (width, height, self.page_size))
        shelf_height = -(-height // SHELF_STEP) * SHELF_STEP
        index, shelf = self._room(width, shelf_height)
        placed = Placement(index, shelf.used, shelf.y, width, height)
        shelf.used += width
        page = self._pages[index]
        page.keys.add(key)
        page.used = self.frame
        self._placed[key] = placed
        self._payloads[key] = payload
        return placed

    def _room(self, width: int, height: int) -> tuple[int, _Shelf]:
        """A page and a shelf with `width` free, of `height`"""
        for index, page in enumerate(self._pages):
            for shelf in page.shelves:
                if shelf.height == height and shelf.used + width <= self.page_size:
                    return index, shelf
        for index, page in enumerate(self._pages):
            if page.top() + height <= self.page_size:
                return index, self._shelve(page, height)
        if len(self._pages) < self.limit:
            return self._new_page(height)
        stale = min(range(len(self._pages)), key=lambda each: self._pages[each].used)
        if self._pages[stale].used >= self.frame:
            return self._new_page(height)
        self._clear(stale)
        return stale, self._shelve(self._pages[stale], height)

    def _new_page(self, height: int) -> tuple[int, _Shelf]:
        self._pages.append(_Page())
        return len(self._pages) - 1, self._shelve(self._pages[-1], height)

    @staticmethod
    def _shelve(page: _Page, height: int) -> _Shelf:
        shelf = _Shelf(page.top(), height)
        page.shelves.append(shelf)
        return shelf

    def _clear(self, index: int) -> None:
        page = self._pages[index]
        for key in page.keys:
            self._placed.pop(key, None)
            self._payloads.pop(key, None)
        self._pages[index] = _Page()
