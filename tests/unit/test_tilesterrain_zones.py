"""A streamed world that carries zones: a glTF document named in its extras.

A tileset has nowhere of its own to put an ``OGLC_zone``, and a zone is not
part of any one tile: a tunnel's zone runs through as many tiles as the tunnel
does, and a zone that came and went with a tile would switch a room's lighting
off as the tile under it refined. So a world writes its zones once, as a glTF
document beside the tileset, and the terrain node loads it and keeps it
mounted.
"""
import json
import os
import shutil

import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.scenegraph.tilesterrain import TilesTerrain  # noqa: E402
from OpenGLContext.scenegraph.zone import ENVIRONMENT, Zone  # noqa: E402

EXAMPLE = os.path.join(os.path.dirname(__file__), '..', '..', 'docs', 'extensions',
                       'examples', 'OGLC_zone-2.0.gltf')


def _world(directory, zones=True):
    from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset
    path = build_sample_tileset(str(directory))
    document = json.load(open(path))
    if zones:
        shutil.copy(EXAMPLE, os.path.join(str(directory), 'zones.gltf'))
        document.setdefault('extras', {})['zones'] = {'document': 'zones.gltf'}
    json.dump(document, open(path, 'w'))
    return path


def _zones_under(node):
    found, todo = [], [node]
    while todo:
        item = todo.pop()
        if isinstance(item, Zone):
            found.append(item)
        todo.extend(getattr(item, 'children', None) or ())
    return found


def test_a_world_naming_zones_mounts_them(tmp_path):
    terrain = TilesTerrain(_world(tmp_path), workers=1)
    try:
        assert terrain.zones is not None
        assert len(terrain.zones.zones) == 2
        mounted = _zones_under(terrain)
        assert len(mounted) == 2
        assert all(zone.setting(ENVIRONMENT) is not None for zone in mounted)
    finally:
        terrain.shutdown()


def test_the_zones_stay_when_the_tiles_change(tmp_path):
    terrain = TilesTerrain(_world(tmp_path), workers=1)
    try:
        terrain.children = list(terrain._mounted)
        assert terrain.zones.group in terrain.children
    finally:
        terrain.shutdown()


def test_a_world_without_zones_has_none(tmp_path):
    terrain = TilesTerrain(_world(tmp_path, zones=False), workers=1)
    try:
        assert terrain.zones is None
        assert _zones_under(terrain) == []
    finally:
        terrain.shutdown()
