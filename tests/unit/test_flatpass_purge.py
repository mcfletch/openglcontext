"""Letting go of paths whose subtree has left the scenegraph.

A pass keeps two records of the paths it walks: ``paths``, the draw set it
iterates each frame, and ``nodePaths``, keyed by node, which is how a change
somewhere in the graph is turned back into the paths that run through it.
``nodePaths`` holds a path for *every* integrated node, not only the ones the
pass finds interesting, so the two records are not maintainable from one
another.

Both have to let go. A path left behind keeps alive every transform matrix
cached against it, and each of those caches is registered for the fields it
depends on, so content streaming in and out of a world grows the set of
receivers every sender has to notify -- a cost that rises with how long the
session has run rather than with what is on screen.
"""
import gc
import weakref

import pytest
from OpenGLContext.scenegraph.box import Box
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.shape import Shape


@pytest.fixture
def watched():
    """A pass watching a graph of three separately-removable subtrees."""
    from OpenGLContext.passes.flatcore import FlatPass
    subtrees = [Group(children=[Shape(geometry=Box())]) for _ in range(3)]
    scene = Group(children=list(subtrees))
    watcher = FlatPass.__new__(FlatPass)
    watcher.nodePaths = {}
    watcher.paths = {}
    watcher.contexts = []
    watcher.integrate(scene)
    return watcher, scene, subtrees


def held_paths(watcher):
    """Every path the pass still holds, by either record."""
    held = []
    for paths in watcher.nodePaths.values():
        held.extend(paths)
    for paths in watcher.paths.values():
        held.extend(paths)
    return held


def paths_through(watcher, node):
    return list(watcher.nodePaths.get(id(node), ()))


class TestPurgingInvalidatedPaths:
    def test_the_draw_set_drops_it(self, watched) -> None:
        watcher, scene, subtrees = watched
        for path in paths_through(watcher, subtrees[0]):
            path.invalidate()
        watcher.purge()
        drawn = [p for paths in watcher.paths.values() for p in paths]
        assert [p for p in drawn if p.broken] == []

    def test_the_node_index_drops_it_too(self, watched) -> None:
        watcher, scene, subtrees = watched
        for path in paths_through(watcher, subtrees[0]):
            path.invalidate()
        watcher.purge()
        assert [p for p in held_paths(watcher) if p.broken] == []

    def test_a_node_left_with_no_paths_is_forgotten(self, watched) -> None:
        watcher, scene, subtrees = watched
        gone = subtrees[0]
        for path in paths_through(watcher, gone):
            path.invalidate()
        watcher.purge()
        assert id(gone) not in watcher.nodePaths

    def test_the_subtrees_still_there_are_untouched(self, watched) -> None:
        watcher, scene, subtrees = watched
        for path in paths_through(watcher, subtrees[0]):
            path.invalidate()
        watcher.purge()
        for survivor in subtrees[1:]:
            assert paths_through(watcher, survivor), (
                'a sibling that was never invalidated lost its path')

    def test_nothing_holds_the_path_alive_afterwards(self, watched) -> None:
        watcher, scene, subtrees = watched
        watching = [weakref.ref(p) for p in paths_through(watcher, subtrees[0])]
        assert watching, 'fixture produced no path to watch'
        for ref in watching:
            ref().invalidate()
        watcher.purge()
        gc.collect()
        assert all(ref() is None for ref in watching), (
            'a purged path is still referenced somewhere')
