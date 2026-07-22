"""SSE hysteresis: sticky refinement so LOD does not flicker at the threshold.

A tile whose screen-space error sits just under the refine threshold should stay
refined if it was refined last frame (until the error drops well below), while a
tile that was not refined should not refine at the same error. Without hysteresis
the decision is a hard threshold.
"""
import math

from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset
from OpenGLContext.loaders.tiles3d.traversal import select_tiles

FOVY = math.radians(60.0)
VH = 1000
MAX_SSE = 16.0


def _nested():
    box = [0, 0, 0, 5, 0, 0, 0, 5, 0, 0, 0, 5]
    return build_runtime_tileset({
        "asset": {"version": "1.1"}, "geometricError": 200.0,
        "root": {
            "boundingVolume": {"box": box}, "geometricError": 100.0,
            "refine": "REPLACE", "content": {"uri": "root.glb"},
            "children": [{"boundingVolume": {"box": box}, "geometricError": 0.0,
                          "content": {"uri": "leaf.glb"}}],
        },
    })


def _uris(tiles):
    return [t.content_uri for t in tiles]


# root sse = 86600 / distance; pick distances for target errors.
_D_SSE14 = 86600.0 / 14.0   # in the hysteresis band (12..16)
_D_SSE10 = 86600.0 / 10.0   # below the band


def test_in_band_does_not_refine_without_prior_state():
    ts = _nested()
    r = select_tiles(ts, camera=(_D_SSE14, 0, 0), viewport_height=VH, fovy=FOVY,
                     max_sse=MAX_SSE, prefetch_factor=1.0,
                     hysteresis=0.25, refined_state={})
    assert _uris(r.render) == ["root.glb"]


def test_in_band_stays_refined_when_previously_refined():
    ts = _nested()
    state = {id(ts.root): True}
    r = select_tiles(ts, camera=(_D_SSE14, 0, 0), viewport_height=VH, fovy=FOVY,
                     max_sse=MAX_SSE, prefetch_factor=1.0,
                     hysteresis=0.25, refined_state=state)
    assert _uris(r.render) == ["leaf.glb"]


def test_below_band_coarsens_even_if_previously_refined():
    ts = _nested()
    state = {id(ts.root): True}
    r = select_tiles(ts, camera=(_D_SSE10, 0, 0), viewport_height=VH, fovy=FOVY,
                     max_sse=MAX_SSE, prefetch_factor=1.0,
                     hysteresis=0.25, refined_state=state)
    assert _uris(r.render) == ["root.glb"]


def test_traversal_updates_refined_state():
    ts = _nested()
    state = {}
    # Close in (inside the box -> huge sse) refines and records the root as refined.
    select_tiles(ts, camera=(0, 0, 0), viewport_height=VH, fovy=FOVY,
                 max_sse=MAX_SSE, prefetch_factor=1.0,
                 hysteresis=0.25, refined_state=state)
    assert state.get(id(ts.root)) is True
