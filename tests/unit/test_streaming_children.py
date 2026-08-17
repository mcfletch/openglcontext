"""A streaming node's children have to reach the render pass.

The pass does not walk the scenegraph every frame; it keeps a flat set of paths
and updates it from the dispatcher signals a node's child list sends. A node
that swaps its whole list -- which is what a tileset streamer does, every frame
-- sends nothing, and the pass goes on drawing the tiles that were there when
it last looked.

A static camera never notices: the tiles resident at the start stay resident.
Drive across the world and the ground stops arriving.
"""
import numpy as np
import pytest

from OpenGLContext.passes._flat import SGObserver
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.shape import Shape


class _ShapeObserver(SGObserver):
    """An observer that tracks Shapes, as the render pass tracks renderables."""

    INTERESTING_TYPES = [Shape]


def _shape(x=0.0):
    return Shape(geometry=PBRMesh(
        positions=np.array([(x, 0, 0), (x + 1, 0, 0), (x, 1, 0)], 'f')))


def _tracked(observer):
    """The Shapes the observer currently has a live path to."""
    return {id(path[-1]) for path in observer.paths.get(Shape, [])
            if not path.broken}


class TestAGroupThatSwapsItsChildren:
    def test_a_new_child_reaches_the_observer(self) -> None:
        group = Group(children=[_shape(0)])
        observer = _ShapeObserver(group, [])
        arriving = _shape(10)
        group.children = list(group.children) + [arriving]
        assert id(arriving) in _tracked(observer)

    def test_a_departed_child_leaves_it(self) -> None:
        staying, going = _shape(0), _shape(10)
        group = Group(children=[staying, going])
        observer = _ShapeObserver(group, [])
        group.children = [staying]
        assert id(going) not in _tracked(observer)
        assert id(staying) in _tracked(observer)

    def test_a_whole_new_set_is_tracked(self) -> None:
        """What a streamer does: last frame's tiles out, this frame's in."""
        group = Group(children=[_shape(0), _shape(10)])
        observer = _ShapeObserver(group, [])
        arriving = [_shape(20), _shape(30), _shape(40)]
        group.children = arriving
        assert _tracked(observer) == {id(shape) for shape in arriving}

    def test_it_keeps_up_over_many_frames(self) -> None:
        """Twenty frames of paging, as a car driving across a world does."""
        group = Group(children=[])
        observer = _ShapeObserver(group, [])
        for frame in range(20):
            wanted = [_shape(frame + offset) for offset in range(4)]
            group.children = wanted
            assert _tracked(observer) == {id(shape) for shape in wanted}, (
                "frame %d: the pass is drawing the wrong tiles" % frame)

    def test_nothing_changes_when_nothing_changes(self) -> None:
        shapes = [_shape(0), _shape(10)]
        group = Group(children=shapes)
        observer = _ShapeObserver(group, [])
        before = _tracked(observer)
        group.children = list(shapes)
        assert _tracked(observer) == before


class TestTheStreamingTerrainNode:
    """The node this exists for: it swaps its children every frame."""

    def test_its_visible_tiles_reach_the_observer(self, tmp_path) -> None:
        pytest.importorskip('pygltflib')
        from OpenGLContext.loaders.tiles3d.procedural import build_terrain_tileset
        from OpenGLContext.scenegraph.tilesterrain import TilesTerrain

        path = build_terrain_tileset(str(tmp_path), extent=512, levels=2,
                                     tile_res=9)
        terrain = TilesTerrain(path, max_sse=8.0)
        scene = Group(children=[terrain])
        observer = _ShapeObserver(scene, [])
        try:
            for eye in ((0, 200, 0), (200, 120, 200), (-200, 120, -200)):
                for _ in range(6):
                    terrain.update_for_camera(eye, 720)
                    terrain.runtime.wait_for_loads(timeout=5.0)
                terrain.update_for_camera(eye, 720)
                drawn = _visible_shapes(terrain)
                assert drawn, "no tiles resident at %s" % (eye,)
                assert drawn <= _tracked(observer), (
                    "%d of the visible tiles are unknown to the pass"
                    % len(drawn - _tracked(observer)))
        finally:
            terrain.runtime.shutdown()


def _visible_shapes(node, out=None):
    out = set() if out is None else out
    if isinstance(node, Shape):
        out.add(id(node))
    for child in getattr(node, 'children', None) or []:
        _visible_shapes(child, out)
    return out
