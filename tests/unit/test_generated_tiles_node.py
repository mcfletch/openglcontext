"""GeneratedTiles: the scenegraph node that streams tiles made on demand.

Real tiles, built from the engine's surface geometry and drawn by the node's
runtime. The generator is the same segmented track the tileset tests use.
"""
import math
import types

import numpy as np
import pytest

from OpenGLContext.loaders.tiles3d import gltf_uploader
from OpenGLContext.loaders.tiles3d.boundingvolume import BoxBV
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.generatedtiles import GeneratedTiles
from OpenGLContext.scenegraph.group import Group

SEGMENT = 100.0
FOVY = math.radians(45)


class Track:
    def __init__(self):
        self.material = surfaces.pbr_material(surfaces.sandstone(size=32))

    def keys_near(self, point, radius):
        first = max(0, math.floor(-(point[2] + radius) / SEGMENT))
        return range(first, math.floor(-(point[2] - radius) / SEGMENT) + 1)

    def bounds(self, key):
        return BoxBV((0.0, 0.0, -(key + 0.5) * SEGMENT),
                     [(10.0, 0, 0), (0, 5.0, 0), (0, 0, SEGMENT / 2)])

    def generate(self, key):
        slab = surfaces.shape(surfaces.block((20.0, 1.0, SEGMENT)), self.material,
                              translation=(0.0, 0.0, -(key + 0.5) * SEGMENT))
        return types.SimpleNamespace(group=Group(children=[slab]),
                                     center=(0, 0, 0), radius=SEGMENT), 4096


@pytest.fixture
def node():
    node = GeneratedTiles(Track(), reach=200.0, fovy=FOVY, workers=1)
    yield node
    node.shutdown()


def stream(node, z):
    camera = np.array([0.0, 2.0, z])
    node.update_for_camera(camera, 720)
    assert node.wait_for_loads()
    drawn = node.update_for_camera(camera, 720)
    while node.runtime.pending_uploads:
        drawn = node.update_for_camera(camera, 720)
    return drawn


def test_the_node_is_a_group_of_the_tiles_drawn(node, gl_context):
    stream(node, -50.0)
    assert len(node.children) == 3


def test_driving_on_swaps_the_tiles_behind_for_those_ahead(node, gl_context):
    stream(node, -50.0)
    first = list(node.children)
    stream(node, -650.0)
    assert len(node.children) == 5
    assert not set(map(id, first)) & set(map(id, node.children))


def test_a_tile_left_behind_is_disposed(node, gl_context, monkeypatch):
    disposed = []
    real = gltf_uploader._make_dispose

    def recording(drawable, *named):
        dispose = real(drawable, *named)
        return lambda: (disposed.append(drawable), dispose())[1]

    monkeypatch.setattr(gltf_uploader, '_make_dispose', recording)
    stream(node, -50.0)
    stream(node, -650.0)
    assert len(disposed) == 3


def test_tile_memory_is_the_generators_count(node, gl_context):
    stream(node, -50.0)
    assert node.runtime.residency.resident_bytes == 3 * 4096


def test_priming_loads_the_opening_view_before_the_first_frame(node, gl_context):
    node.prime(np.array([0.0, 2.0, -50.0]), 720)
    assert len(node.children) == 3


class Recorder:
    """A context cache that has nothing cached, so disposal has nothing to delete."""

    def getData(self, *args, **named):
        return None

    def getHolder(self, *args, **named):
        return None


@pytest.mark.parametrize('own_materials, deleted', [(True, 1), (False, 0)])
def test_materials_are_deleted_with_a_tile_only_when_the_tile_owns_them(
        monkeypatch, own_materials, deleted):
    from OpenGLContext import context as context_module
    texture_deletions = []
    monkeypatch.setattr(context_module, 'getCurrentContext',
                        lambda: types.SimpleNamespace(cache=Recorder()))
    monkeypatch.setattr(gltf_uploader, '_dispose_material_textures',
                        lambda material, cache: texture_deletions.append(material))
    track = Track()
    scene, _ = track.generate(0)
    uploader = gltf_uploader.GLTileUploader(own_materials=own_materials)
    tile = types.SimpleNamespace(content_transform=np.identity(4))
    drawable, nbytes = uploader.upload(tile, (scene, 4096))
    uploader.release(drawable)
    assert len(texture_deletions) == deleted


def test_a_node_that_is_disposed_streams_again_when_it_is_asked_to(node, gl_context):
    stream(node, -50.0)
    node.dispose()
    assert list(node.children) == []
    stream(node, -50.0)
    assert len(node.children) == 3
