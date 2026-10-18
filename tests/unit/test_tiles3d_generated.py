"""Tiles made on demand: the tileset that grows as the camera moves.

A :class:`GeneratedTileset` holds no tile until the camera is near enough to
want it, asks its generator for the bounds of each, and drops the ones the
camera has left. The tests use a real generator, a track of equal segments along
-Z, and the engine's own traversal and runtime.
"""
import math
from collections import namedtuple

import numpy as np
import pytest

from OpenGLContext.loaders.tiles3d.boundingvolume import BoxBV
from OpenGLContext.loaders.tiles3d.generated import GeneratedTileset
from OpenGLContext.loaders.tiles3d.runtime import TilesetRuntime
from OpenGLContext.loaders.tiles3d.traversal import select_tiles
from OpenGLContext.scenegraph.basenodes import Group

SEGMENT = 100.0
Scene = namedtuple('Scene', 'group center radius')


class Track:
    """Segment ``i`` covers z in ``[-(i + 1) * 100, -i * 100]``, a box 20 m wide."""

    def __init__(self):
        self.generated = []

    def keys_near(self, point, radius):
        first = max(0, math.floor(-(point[2] + radius) / SEGMENT))
        last = math.floor(-(point[2] - radius) / SEGMENT)
        return range(first, last + 1)

    def bounds(self, key):
        centre = (0.0, 0.0, -(key + 0.5) * SEGMENT)
        return BoxBV(centre, [(10.0, 0, 0), (0, 5.0, 0), (0, 0, SEGMENT / 2)])

    def generate(self, key):
        self.generated.append(key)
        return Scene(group='segment-%d' % key, center=(0, 0, 0), radius=1.0), 1000


@pytest.fixture
def track():
    return Track()


@pytest.fixture
def tileset(track):
    return GeneratedTileset(track, reach=200.0, retain=350.0)


def keys(tileset):
    return sorted(tile.content_key for tile in tileset.root.children)


def test_no_tile_exists_before_the_camera_asks(tileset):
    assert tileset.root.children == []


def test_tiles_are_made_for_the_keys_near_the_camera(tileset):
    created, retired = tileset.ensure(np.array([0.0, 2.0, -50.0]))
    assert keys(tileset) == [0, 1, 2]
    assert sorted(tile.content_key for tile in created) == [0, 1, 2]
    assert retired == []


def test_a_tile_takes_the_bounds_its_generator_gives_the_key(tileset, track):
    tileset.ensure(np.array([0.0, 2.0, -50.0]))
    tile = next(t for t in tileset.root.children if t.content_key == 1)
    assert np.allclose(tile.bounding_volume.center, track.bounds(1).center)


def test_a_tile_is_made_once(tileset):
    camera = np.array([0.0, 2.0, -50.0])
    tileset.ensure(camera)
    first = {tile.content_key: tile for tile in tileset.root.children}
    created, _ = tileset.ensure(camera)
    assert created == []
    assert all(first[tile.content_key] is tile for tile in tileset.root.children)


def test_moving_forward_makes_tiles_ahead_and_retires_those_far_behind(tileset):
    tileset.ensure(np.array([0.0, 2.0, -50.0]))
    created, retired = tileset.ensure(np.array([0.0, 2.0, -650.0]))
    assert keys(tileset) == [4, 5, 6, 7, 8]
    assert sorted(tile.content_key for tile in retired) == [0, 1, 2]
    assert sorted(tile.content_key for tile in created) == [4, 5, 6, 7, 8]


def test_a_tile_just_behind_the_camera_is_kept_until_it_is_beyond_retain(tileset):
    tileset.ensure(np.array([0.0, 2.0, -50.0]))
    _, retired = tileset.ensure(np.array([0.0, 2.0, -250.0]))
    assert retired == []
    assert 0 in keys(tileset)


def test_a_retired_tile_is_detached_from_the_tree(tileset):
    tileset.ensure(np.array([0.0, 2.0, -50.0]))
    _, retired = tileset.ensure(np.array([0.0, 2.0, -2050.0]))
    assert all(tile.parent is None for tile in retired)


def test_the_root_bounds_every_tile_it_holds(tileset):
    tileset.ensure(np.array([0.0, 2.0, -650.0]))
    centre, radius = tileset.root.bounding_volume.bounding_sphere()
    for tile in tileset.root.children:
        c, r = tile.bounding_volume.bounding_sphere()
        assert np.linalg.norm(c - centre) + r <= radius + 1e-6


def test_the_tiles_have_content_the_traversal_selects(tileset):
    camera = np.array([0.0, 2.0, -50.0])
    tileset.ensure(camera)
    chosen = select_tiles(tileset, camera, 720, math.radians(45), 16.0)
    assert sorted(t.content_key for t in chosen.render) == [0, 1, 2]


def test_the_loader_asks_the_generator_for_the_tiles_key(tileset, track):
    tileset.ensure(np.array([0.0, 2.0, -50.0]))
    tile = next(t for t in tileset.root.children if t.content_key == 2)
    scene, nbytes = tileset.loader(tile)
    assert (scene.group, nbytes) == ('segment-2', 1000)
    assert track.generated == [2]


def test_a_reach_beyond_the_retain_distance_is_refused(track):
    with pytest.raises(ValueError, match='retain'):
        GeneratedTileset(track, reach=500.0, retain=100.0)


class Uploader:
    def __init__(self):
        self.uploaded = []
        self.released = []

    def upload(self, tile, payload):
        scene, nbytes = payload
        self.uploaded.append(tile.content_key)
        return scene.group, nbytes

    def release(self, drawable):
        self.released.append(drawable)


@pytest.fixture
def runtime(tileset):
    uploader = Uploader()
    runtime = TilesetRuntime(tileset, tileset.loader, uploader,
                             memory_budget=10 ** 9, fovy=math.radians(45), workers=1)
    yield runtime
    runtime.shutdown()


def stream(tileset, runtime, camera):
    tileset.ensure(camera)
    runtime.update(camera, 720)
    assert runtime.wait_for_loads()
    return runtime.update(camera, 720)


def test_the_runtime_loads_and_draws_the_generated_tiles(tileset, runtime):
    drawn = stream(tileset, runtime, np.array([0.0, 2.0, -50.0]))
    assert sorted(drawn) == ['segment-0', 'segment-1', 'segment-2']


def test_discarding_a_tile_releases_what_it_drew(tileset, runtime):
    camera = np.array([0.0, 2.0, -50.0])
    stream(tileset, runtime, camera)
    tile = next(t for t in tileset.root.children if t.content_key == 0)
    runtime.discard(tile)
    assert runtime.uploader.released == ['segment-0']
    assert runtime.residency.resident_bytes == 2000


def test_discarding_a_tile_not_yet_drawn_is_harmless(tileset, runtime):
    tileset.ensure(np.array([0.0, 2.0, -50.0]))
    tile = tileset.root.children[0]
    runtime.discard(tile)
    assert runtime.uploader.released == []


def test_a_tile_discarded_while_loading_is_not_drawn_when_it_arrives(tileset):
    import threading
    gate, started = threading.Event(), threading.Event()

    def slow(tile):
        started.set()
        gate.wait(5.0)
        return tileset.loader(tile)

    uploader = Uploader()
    runtime = TilesetRuntime(tileset, slow, uploader, memory_budget=10 ** 9,
                             fovy=math.radians(45), workers=1)
    try:
        camera = np.array([0.0, 2.0, -50.0])
        tileset.ensure(camera)
        runtime.update(camera, 720)
        assert started.wait(5.0)
        for tile in list(tileset.root.children):
            runtime.discard(tile)
        gate.set()
        assert runtime.wait_for_loads()
        runtime.update(camera, 720)
        assert uploader.uploaded == []
        assert runtime.residency.resident_bytes == 0
    finally:
        gate.set()
        runtime.shutdown()


def test_a_cleared_tileset_makes_its_tiles_again(tileset):
    camera = np.array([0.0, 2.0, -50.0])
    tileset.ensure(camera)
    cleared = list(tileset.root.children)
    tileset.clear()
    assert tileset.root.children == [] and all(tile.parent is None for tile in cleared)
    created, _ = tileset.ensure(camera)
    assert sorted(tile.content_key for tile in created) == [0, 1, 2]


class PlacedTrack(Track):
    """A track whose segments are made around their own centres."""

    def origin(self, key):
        return (0.0, 0.0, -(key + 0.5) * SEGMENT)


def test_a_tile_is_placed_at_the_origin_its_generator_names():
    tileset = GeneratedTileset(PlacedTrack(), reach=200.0)
    tileset.ensure((0.0, 0.0, -450.0))
    tile = next(t for t in tileset.root.children if t.content_key == 4)
    assert tile.world_transform[:3, 3] == pytest.approx((0.0, 0.0, -450.0))
    assert tile.content_transform[:3, 3] == pytest.approx((0.0, 0.0, -450.0))


def test_a_generator_with_no_origin_leaves_its_tiles_where_they_are(tileset):
    tileset.ensure((0.0, 0.0, -450.0))
    assert all(np.allclose(t.world_transform, np.identity(4)) for t in tileset.root.children)


def test_a_placed_tile_is_drawn_through_a_transform_that_moves_it_to_its_origin():
    from OpenGLContext.loaders.tiles3d.gltf_uploader import GLTileUploader

    tileset = GeneratedTileset(PlacedTrack(), reach=200.0)
    tileset.ensure((0.0, 0.0, -450.0))
    tile = next(t for t in tileset.root.children if t.content_key == 4)
    scene = Scene(group=Group(), center=(0, 0, 0), radius=1.0)
    drawable, _ = GLTileUploader().upload(tile, (scene, 10))
    assert drawable.children == [scene.group]
    point = np.array([0.0, 0.0, 0.0, 1.0]) @ drawable.localMatrix()
    assert point[:3] == pytest.approx((0.0, 0.0, -450.0))
