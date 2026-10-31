"""Extra coverage for tiles3d.physics_colliders: the on_renderable/on_evicted guard
branches (duplicate tile, empty extraction, unknown tile) in a physics service.
"""
import numpy as np
import pytest


from OpenGLContext.loaders.tiles3d import physics_colliders
from OpenGLContext.loaders.tiles3d.physics_colliders import TerrainColliders
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition


@pytest.fixture
def _world():
    service = Physics(PhysicsDefinition(mode='inline', colliders='none'))
    yield service
    service.close()


class _Tile:
    """Distinct-by-identity tile stand-in."""


def test_on_renderable_ignores_already_resident_tile(monkeypatch, _world):
    calls = {"n": 0}

    def fake_extract(_drawable, min_hull_size=0.0):  # noqa: ARG001 the signature of the extract_trimesh it stands in for
        calls["n"] += 1
        pts = np.array([[0, 0, 0], [1, 0, 0], [0, 0, 1]], "f4")
        idx = np.array([[0, 1, 2]], "u4")
        return pts, idx

    monkeypatch.setattr(physics_colliders.gltf_world, "extract_trimesh", fake_extract)
    colliders = TerrainColliders(_world)
    tile = _Tile()
    colliders.on_renderable(tile, object())
    colliders.on_renderable(tile, object())      # second call is a no-op
    assert colliders.collider_count == 1
    assert calls["n"] == 1                        # extraction ran only once


def test_on_renderable_skips_when_extraction_is_none(monkeypatch, _world):
    monkeypatch.setattr(physics_colliders.gltf_world, "extract_trimesh",
                        lambda _drawable, min_hull_size=0.0: None)  # noqa: ARG005 extract_trimesh's signature
    colliders = TerrainColliders(_world)
    colliders.on_renderable(_Tile(), object())
    assert colliders.collider_count == 0


def test_on_renderable_skips_empty_triangle_mesh(monkeypatch, _world):
    empty = (np.zeros((0, 3), "f4"), np.zeros((0, 3), "u4"))
    monkeypatch.setattr(physics_colliders.gltf_world, "extract_trimesh",
                        lambda _drawable, min_hull_size=0.0: empty)  # noqa: ARG005 extract_trimesh's signature
    colliders = TerrainColliders(_world)
    colliders.on_renderable(_Tile(), object())
    assert colliders.collider_count == 0


def test_on_evicted_unknown_tile_is_noop(_world):
    colliders = TerrainColliders(_world)
    colliders.on_evicted(_Tile(), None)          # never added -> body is None -> return
    assert colliders.collider_count == 0
