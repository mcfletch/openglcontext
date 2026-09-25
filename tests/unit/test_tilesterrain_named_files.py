"""The files a streamed world names beside its tileset.

A world's extras name its zones document, its trees' meshes and textures, and
its ground cover's cards and clumps. Those names come out of the tileset, so
they are held to the tileset's own containment: under its directory for a
world on disk, on its origin for a world served over http(s). A world served
over http(s) has its files fetched, since nothing downstream opens a URL.
"""
import functools
import http.server
import json
import logging
import os
import shutil
import sys
import threading

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.tiles3d import fetch
from OpenGLContext.scenegraph.tilesterrain import TilesTerrain

sys.path.insert(0, os.path.dirname(__file__))
from test_clump_glb import _glb_bytes, _ribbon

ZONES = os.path.join(os.path.dirname(__file__), '..', '..', 'docs', 'extensions',
                     'examples', 'OGLC_zone-2.0.gltf')


@pytest.fixture
def served(tmp_path):
    """``tmp_path/world`` served over http on localhost; yields (directory, url)."""
    world = tmp_path / 'world'
    world.mkdir()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(world))
    handler.log_message = lambda *args: None       # type: ignore[attr-defined]
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield world, 'http://%s:%d/' % (host, port)
    finally:
        server.shutdown()
        server.server_close()


class TestAFileBesideATileset:
    def test_a_local_name_resolves_under_the_directory(self, tmp_path):
        assert fetch.beside(str(tmp_path) + os.sep, 'zones.gltf') == str(
            tmp_path / 'zones.gltf')

    @pytest.mark.parametrize('name', ['../outside.gltf', '/etc/hostname',
                                      'file:///etc/hostname',
                                      'http://169.254.169.254/x'])
    def test_a_local_world_reaches_nothing_outside_its_directory(
            self, tmp_path, name):
        with pytest.raises(IOError):
            fetch.beside(str(tmp_path) + os.sep, name)

    def test_a_remote_name_stays_on_the_origin(self):
        base = 'https://worlds.example.invalid/one/'
        assert fetch.beside(base, 'cover/grass.glb') == (
            'https://worlds.example.invalid/one/cover/grass.glb')
        with pytest.raises(IOError):
            fetch.beside(base, 'https://elsewhere.example.invalid/grass.glb')
        with pytest.raises(IOError):
            fetch.beside(base, 'file:///etc/hostname')

    def test_a_name_needs_a_tileset_to_be_beside(self):
        with pytest.raises(ValueError):
            fetch.beside('', 'zones.gltf')

    def test_a_local_file_is_its_own_copy(self, tmp_path):
        path = str(tmp_path / 'a.png')
        assert fetch.local_copy(path) == path

    def test_a_remote_file_is_fetched_to_the_cache(self, served, tmp_path):
        world, url = served
        (world / 'a.bin').write_bytes(b'payload')
        copy = fetch.local_copy(url + 'a.bin', cache_dir=str(tmp_path / 'cache'))
        assert not fetch.is_url(copy)
        with open(copy, 'rb') as handle:
            assert handle.read() == b'payload'


def _landscape(world, extras):
    """A sample tileset in ``world`` with a flat field terrain and ``extras``."""
    from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset
    from OpenGLContext.scenegraph.terrain import (
        HeightField, LayerRule, control_map,
    )
    path = build_sample_tileset(str(world))
    document = json.load(open(path))
    field = HeightField.from_function(
        lambda x, z: np.zeros(np.shape(np.asarray(x))), res=33, extent=2048.0)
    field.save_image(os.path.join(str(world), 'g-height.png'))
    control_map(field, [LayerRule()], size=32).save(
        os.path.join(str(world), 'g-control.png'))
    document['extras'] = dict({
        'terrain': {
            'height': 'g-height.png', 'control': 'g-control.png',
            'extent': 2048.0, 'base': field.base,
            'relief': max(field.relief, 1.0), 'resolution': 33,
            'layers': ['grass'],
        },
    }, **extras)
    json.dump(document, open(path, 'w'))
    return path


def _plants(world):
    """A clump and a card in ``world``; the cover record naming them."""
    (world / 'grass.glb').write_bytes(_glb_bytes(*_ribbon()))
    from PIL import Image
    Image.new('RGBA', (4, 4), (40, 120, 40, 255)).save(str(world / 'blade.png'))
    np.savez(str(world / 'trees.npz'),
             positions=np.zeros((1, 3), 'f4'), yaws=np.zeros(1, 'f4'),
             heights=np.ones(1, 'f4'), species=np.zeros(1, 'i4'))
    return {
        'trees': 'trees.npz',
        'species': [{'name': 'oak', 'mesh': 'oak.npz',
                     'solidTexture': 'bark.png', 'foliageTexture': 'leaf.png',
                     'impostor': 'card.png'}],
        'cover': {'name': 'grass', 'card': 'blade.png', 'clump': 'grass.glb',
                  'density': 0.5},
    }


class TestZonesNamedByAWorld:
    def test_a_zones_document_outside_the_world_is_not_loaded(
            self, tmp_path, caplog):
        world = tmp_path / 'world'
        world.mkdir()
        shutil.copy(ZONES, str(tmp_path / 'outside.gltf'))
        path = _landscape(world, {'zones': {'document': '../outside.gltf'}})
        with caplog.at_level(logging.WARNING):
            terrain = TilesTerrain(path, workers=1)
        try:
            assert terrain.zones is None
            assert 'outside.gltf' in caplog.text
        finally:
            terrain.shutdown()

    def test_a_zones_document_that_will_not_load_leaves_the_world_without_zones(
            self, tmp_path, caplog):
        world = tmp_path / 'world'
        world.mkdir()
        (world / 'zones.gltf').write_text('this is not a glTF document')
        path = _landscape(world, {'zones': {'document': 'zones.gltf'}})
        with caplog.at_level(logging.WARNING):
            terrain = TilesTerrain(path, workers=1)
        try:
            assert terrain.zones is None
            assert terrain.field is not None
            assert 'zones.gltf' in caplog.text
        finally:
            terrain.shutdown()

    def test_a_served_world_loads_its_zones_from_its_origin(
            self, served, tmp_path):
        world, url = served
        shutil.copy(ZONES, str(world / 'zones.gltf'))
        _landscape(world, {'zones': {'document': 'zones.gltf'}})
        terrain = TilesTerrain(url + 'tileset.json', workers=1,
                               cache_dir=str(tmp_path / 'cache'))
        try:
            assert terrain.zones is not None
            assert len(terrain.zones.zones) == 2
        finally:
            terrain.shutdown()


class TestPlantsNamedByAWorld:
    @pytest.mark.parametrize('escape', ['../grass.glb', '/etc/hostname'])
    def test_a_clump_outside_the_world_is_refused(self, tmp_path, escape):
        world = tmp_path / 'world'
        world.mkdir()
        record = _plants(world)
        record['cover']['clump'] = escape
        path = _landscape(world, {'vegetation': record})
        with pytest.raises(IOError):
            TilesTerrain(path, workers=1).shutdown()

    def test_a_tree_texture_outside_the_world_is_refused(self, tmp_path):
        world = tmp_path / 'world'
        world.mkdir()
        record = _plants(world)
        record['species'][0]['impostor'] = '../../card.png'
        path = _landscape(world, {'vegetation': record})
        with pytest.raises(IOError):
            TilesTerrain(path, workers=1).shutdown()

    def test_a_served_world_s_cover_is_fetched_and_grown(self, served, tmp_path):
        world, url = served
        record = _plants(world)
        # Every file a served species names has to be there to be fetched.
        record['species'] = [{
            'name': 'oak', 'mesh': 'trees.npz', 'solidTexture': 'blade.png',
            'foliageTexture': 'blade.png', 'impostor': 'blade.png'}]
        _landscape(world, {'vegetation': record})
        terrain = TilesTerrain(url + 'tileset.json', workers=1,
                               cache_dir=str(tmp_path / 'cache'))
        try:
            species = terrain.cover.species[0]
            assert not fetch.is_url(species.clump)
            assert not fetch.is_url(species.card)
            assert os.path.isfile(species.clump)
            assert terrain.cover.rungs[0].clumps_far is not None
            tree = terrain.vegetation.species[0]
            assert os.path.isfile(tree.impostor)
        finally:
            terrain.shutdown()
