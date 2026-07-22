"""SSE-driven traversal: pick the tiles to render and the tiles to keep resident.

`select_tiles` walks the tileset against the live camera and returns a render set
(the ideal visible tiles) and a want set (render set plus a speculative prefetch
margin). REPLACE hides the parent when children are shown; ADD keeps it.
"""
import math
import pytest

from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset
from OpenGLContext.loaders.tiles3d.traversal import select_tiles


FOVY = math.radians(60.0)
VH = 1000
MAX_SSE = 16.0


def _nested(refine="REPLACE", mid_ge=40.0):
    # root(GE=100) -> mid(GE) -> leaf(GE=0), all boxes centred at origin.
    box = [0, 0, 0, 5, 0, 0, 0, 5, 0, 0, 0, 5]
    return build_runtime_tileset({
        "asset": {"version": "1.1"}, "geometricError": 200.0,
        "root": {
            "boundingVolume": {"box": box}, "geometricError": 100.0,
            "refine": refine, "content": {"uri": "root.glb"},
            "children": [{
                "boundingVolume": {"box": box}, "geometricError": mid_ge,
                "content": {"uri": "mid.glb"},
                "children": [{
                    "boundingVolume": {"box": box}, "geometricError": 0.0,
                    "content": {"uri": "leaf.glb"},
                }],
            }],
        },
    })


def _uris(tiles):
    return [t.content_uri for t in tiles]


def test_distant_camera_renders_only_root():
    ts = _nested()
    # 86600/dist for root; at dist 10000 sse ~8.7 < 16 -> stop at root.
    result = select_tiles(ts, camera=(10000, 0, 0), viewport_height=VH,
                          fovy=FOVY, max_sse=MAX_SSE)
    assert _uris(result.render) == ["root.glb"]


def test_camera_inside_replace_shows_leaf_not_parents():
    ts = _nested(refine="REPLACE")
    result = select_tiles(ts, camera=(0, 0, 0), viewport_height=VH,
                          fovy=FOVY, max_sse=MAX_SSE)
    # distance 0 -> inf sse at every level -> refine to the leaf; REPLACE hides parents.
    assert _uris(result.render) == ["leaf.glb"]


def test_add_refine_keeps_ancestors():
    ts = _nested(refine="ADD")
    result = select_tiles(ts, camera=(0, 0, 0), viewport_height=VH,
                          fovy=FOVY, max_sse=MAX_SSE)
    assert set(_uris(result.render)) == {"root.glb", "mid.glb", "leaf.glb"}


def test_want_superset_of_render():
    ts = _nested()
    result = select_tiles(ts, camera=(3000, 0, 0), viewport_height=VH,
                          fovy=FOVY, max_sse=MAX_SSE, prefetch_factor=2.0)
    render_ids = {id(t) for t in result.render}
    want_ids = {id(t) for t in result.want}
    assert render_ids <= want_ids


def test_prefetch_pulls_in_finer_tiles_than_render():
    ts = _nested(mid_ge=40.0)
    # At dist 3000: root sse ~28.9 (>16, refine), mid sse ~11.5 (<16 render).
    # Prefetch threshold 8 -> mid refines -> leaf wanted but not rendered.
    result = select_tiles(ts, camera=(3000, 0, 0), viewport_height=VH,
                          fovy=FOVY, max_sse=MAX_SSE, prefetch_factor=2.0)
    assert _uris(result.render) == ["mid.glb"]
    assert "leaf.glb" in _uris(result.want)
    assert "leaf.glb" not in _uris(result.render)


def test_no_prefetch_makes_want_equal_render():
    ts = _nested()
    result = select_tiles(ts, camera=(3000, 0, 0), viewport_height=VH,
                          fovy=FOVY, max_sse=MAX_SSE, prefetch_factor=1.0)
    assert {id(t) for t in result.render} == {id(t) for t in result.want}


def test_leaf_always_renders_regardless_of_error():
    # A single childless tile renders even when its SSE is tiny (nothing finer exists).
    ts = build_runtime_tileset({
        "asset": {"version": "1.1"}, "geometricError": 10.0,
        "root": {"boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
                 "geometricError": 100.0, "content": {"uri": "only.glb"}},
    })
    result = select_tiles(ts, camera=(0, 0, 0), viewport_height=VH,
                          fovy=FOVY, max_sse=MAX_SSE)
    assert _uris(result.render) == ["only.glb"]


def test_contentless_tile_excluded_from_render_but_descends():
    # Intermediate grouping tile without content contributes no draw, but its
    # children are still traversed.
    ts = build_runtime_tileset({
        "asset": {"version": "1.1"}, "geometricError": 200.0,
        "root": {
            "boundingVolume": {"box": [0, 0, 0, 5, 0, 0, 0, 5, 0, 0, 0, 5]},
            "geometricError": 100.0,  # no content
            "children": [{
                "boundingVolume": {"box": [0, 0, 0, 5, 0, 0, 0, 5, 0, 0, 0, 5]},
                "geometricError": 0.0, "content": {"uri": "real.glb"}}],
        },
    })
    result = select_tiles(ts, camera=(0, 0, 0), viewport_height=VH,
                          fovy=FOVY, max_sse=MAX_SSE)
    assert _uris(result.render) == ["real.glb"]
