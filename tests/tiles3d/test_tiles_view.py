"""The oglc-tiles viewer's framing helpers and CLI.

These cover the non-GL logic: descending an external/grouping tree to the first
content tile for auto-framing, deriving a world-space look direction from a view
platform's orientation quaternion, and argument parsing. The GL render path is
exercised by the tiles3d runtime tests and manual captures.
"""
import math

import numpy as np
import pytest

from OpenGLContext import quaternion
from OpenGLContext.bin import tiles_view
from OpenGLContext.loaders.tiles3d.tileset import RuntimeTile
from OpenGLContext.loaders.tiles3d.boundingvolume import SphereBV

_IDENTITY = np.identity(4, dtype="d")


def _tile(content_uri, children=()):
    return RuntimeTile(
        bounding_volume=SphereBV((0, 0, 0), 1.0),
        geometric_error=0.0, refine="REPLACE",
        content_uris=[content_uri] if content_uri else [],
        world_transform=_IDENTITY, children=list(children),
    )


def test_leaf_tile_returns_self_when_it_has_content():
    t = _tile("model.b3dm")
    assert tiles_view._leaf_tile(t) is t


def test_leaf_tile_descends_past_contentless_grouping_tiles():
    leaf = _tile("detail.b3dm")
    mid = _tile(None, children=[leaf])
    root = _tile(None, children=[mid])   # e.g. root -> external tileset -> content
    assert tiles_view._leaf_tile(root) is leaf


def test_forward_is_negative_z_for_identity_orientation():
    fwd = tiles_view._forward(quaternion.fromXYZR(0, 1, 0, 0.0))
    assert np.allclose(fwd, [0, 0, -1], atol=1e-9)


def test_forward_yaws_with_orientation():
    # A +90-degree yaw about +Y turns the look direction toward -X.
    fwd = tiles_view._forward(quaternion.fromXYZR(0, 1, 0, math.pi / 2))
    assert np.allclose(fwd, [-1, 0, 0], atol=1e-6)


def test_parser_defaults_and_overrides():
    args = tiles_view.build_parser().parse_args(["scene/tileset.json"])
    assert args.source == "scene/tileset.json"
    assert args.sse == 16.0 and args.memory == 512 and not args.no_recenter
    assert args.cache_dir is None

    args = tiles_view.build_parser().parse_args(
        ["t.json", "--sse", "4", "--memory", "1024", "--no-recenter",
         "--capture", "out.png"])
    assert args.sse == 4.0 and args.memory == 1024 and args.no_recenter
    assert args.capture == "out.png"


def test_parser_requires_a_source():
    with pytest.raises(SystemExit):
        tiles_view.build_parser().parse_args([])
