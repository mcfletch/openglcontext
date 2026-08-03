"""Framing a streamed dataset, and what ``oglc-tiles`` is now.

The framing helpers belong to the 3D-Tiles *adapter*, since which tile to aim at
is a fact about the format rather than about a command: descending an
external/grouping tree to the first tile that carries content, and deriving a
world-space look direction from a view platform's orientation.  ``oglc-tiles``
itself is a deprecation alias for ``oglc-view``, which opens every format, so
what is left to check of it is that it says so and delegates.

The GL render path is exercised by the tiles3d runtime tests and manual captures.
"""
import math

import numpy as np
import pytest

from OpenGLContext import quaternion
from OpenGLContext.bin import tiles_view
from OpenGLContext.loaders.tiles3d.tileset import RuntimeTile
from OpenGLContext.loaders.tiles3d.boundingvolume import SphereBV
from OpenGLContext.viewer.adapters import tiles as tilesadapter

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
    assert tilesadapter.leaf_tile(t) is t


def test_leaf_tile_descends_past_contentless_grouping_tiles():
    leaf = _tile("detail.b3dm")
    mid = _tile(None, children=[leaf])
    root = _tile(None, children=[mid])   # e.g. root -> external tileset -> content
    assert tilesadapter.leaf_tile(root) is leaf


def test_forward_is_negative_z_for_identity_orientation():
    fwd = tilesadapter._forward(quaternion.fromXYZR(0, 1, 0, 0.0))
    assert np.allclose(fwd, [0, 0, -1], atol=1e-9)


def test_forward_yaws_with_orientation():
    # A +90-degree yaw about +Y turns the look direction toward -X.
    fwd = tilesadapter._forward(quaternion.fromXYZR(0, 1, 0, math.pi / 2))
    assert np.allclose(fwd, [-1, 0, 0], atol=1e-6)


class TestTheDeprecatedCommand:
    """``oglc-tiles`` runs ``oglc-view``, having said that is what it now is."""

    def _run(self, monkeypatch, argv):
        seen = {}

        def fake_main(passed, prog=None):
            seen['argv'] = passed
            seen['prog'] = prog
            return 0
        monkeypatch.setattr(tiles_view, 'view_main', fake_main)
        return seen, tiles_view.main(argv)

    def test_it_delegates_to_the_one_viewer(self, monkeypatch):
        seen, result = self._run(monkeypatch, ['scene/tileset.json', '--sse', '4'])
        assert result == 0
        assert seen['argv'] == ['scene/tileset.json', '--sse', '4']

    def test_it_keeps_its_own_name_in_the_usage_message(self, monkeypatch):
        """Someone who typed ``oglc-tiles --help`` must not be shown another
        command's usage line."""
        seen, _result = self._run(monkeypatch, [])
        assert seen['prog'] == 'oglc-tiles'

    def test_it_says_what_to_type_instead(self, monkeypatch, capsys):
        self._run(monkeypatch, [])
        assert tiles_view.REPLACEMENT in capsys.readouterr().err


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
