"""Construction-time behaviour of the TilesTerrain node (no GL context).

Covers the default field-of-view fallback, the URL base-URI branch, and the
external-tileset resolver -- the parts of ``__init__`` that the residency/streaming
integration tests (which always pass an explicit local path and fovy) never reach.
"""
import functools
import http.server
import json
import math
import threading
import time
import types

import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.loaders.tiles3d.sample import build_sample_tileset
from OpenGLContext.scenegraph.tilesterrain import TilesTerrain


def test_default_fovy_is_45_degrees(tmp_path):
    path = build_sample_tileset(str(tmp_path))
    terrain = TilesTerrain(path, workers=1)      # no fovy -> default
    try:
        assert terrain.fovy == pytest.approx(math.radians(45.0))
    finally:
        terrain.shutdown()


@pytest.fixture
def http_dir(tmp_path):
    """Serve `tmp_path` over http on localhost; yields the base URL."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                 directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield tmp_path, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


def test_url_tileset_with_external_reference(http_dir, tmp_path):
    # A parent tileset whose root content is the sample tileset.json (an external
    # `.json`): serving it over http exercises both the URL base-URI branch and the
    # external-tileset resolver.
    build_sample_tileset(str(tmp_path))
    with open(tmp_path / "tileset.json") as fh:
        sample = json.load(fh)
    parent = {
        "asset": {"version": "1.1"},
        "geometricError": 1000.0,
        "root": {
            "boundingVolume": sample["root"]["boundingVolume"],
            "geometricError": 500.0,
            "refine": "REPLACE",
            "content": {"uri": "tileset.json"},   # external tileset -> resolver
        },
    }
    with open(tmp_path / "parent.json", "w") as fh:
        json.dump(parent, fh)

    _dir, base_url = http_dir
    terrain = TilesTerrain(f"{base_url}/parent.json", workers=1,
                           cache_dir=str(tmp_path / "cache"))
    try:
        # The external sample subtree was grafted in under the parent root.
        assert terrain.tileset.root is not None
        drawn = terrain.update_for_camera(camera=(0, 1000, 4000), viewport_height=800)
        terrain.wait_for_loads(timeout=5.0)
        assert isinstance(drawn, list)
    finally:
        terrain.shutdown()



def test_waiting_for_loads_shares_one_deadline(tmp_path):
    """The tiles and the cover wait within the one timeout between them."""
    path = build_sample_tileset(str(tmp_path))
    terrain = TilesTerrain(path, workers=1)
    given = []

    def slow_tiles(timeout):  # noqa: ARG001 the signature of the runtime.wait_for_loads it stands in for, called with timeout=
        time.sleep(0.2)
        return True
    runtime_wait = terrain.runtime.wait_for_loads
    terrain.runtime.wait_for_loads = slow_tiles
    terrain.cover = types.SimpleNamespace(wait=given.append,
                                          shutdown=lambda: None)
    try:
        terrain.wait_for_loads(timeout=0.5)
        assert given and given[0] <= 0.31
    finally:
        terrain.runtime.wait_for_loads = runtime_wait
        terrain.cover = None
        terrain.shutdown()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
