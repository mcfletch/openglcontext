"""Runtime tileset tree: parse tileset.json into world-space RuntimeTiles.

Covers geometric error, refine inheritance, content-URI resolution, both box and
sphere bounding volumes (sphere is unsupported by py3dtiles, so we parse the tree
ourselves), and transform composition down the hierarchy into world space.
"""
import numpy as np
import pytest

from OpenGLContext.loaders.tiles3d.tileset import build_runtime_tileset
from OpenGLContext.loaders.tiles3d.boundingvolume import SphereBV, BoxBV, RegionBV


def _tileset(root):
    return {"asset": {"version": "1.1"}, "geometricError": 500.0, "root": root}


def _region(dlon=1e-3, dlat=1e-3):
    # A small geodetic patch near (lon 0.1, lat 0.8) rad, 0..200 m elevation.
    lon0, lat0 = 0.1, 0.8
    return [lon0 - dlon, lat0 - dlat, lon0 + dlon, lat0 + dlat, 0.0, 200.0]


def test_region_bounding_volume_parses():
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": {"region": _region()},
        "geometricError": 100.0,
        "refine": "REPLACE",
        "content": {"uri": "root.b3dm"},
    }))
    assert isinstance(ts.root.bounding_volume, RegionBV)
    # Un-recentred, the patch sits a full Earth radius from the geocentre.
    c, _ = ts.root.bounding_volume.bounding_sphere()
    assert np.linalg.norm(c) == pytest.approx(6.36e6, rel=1e-2)


def test_region_tileset_recenters_to_origin():
    root = {
        "boundingVolume": {"region": _region()},
        "geometricError": 100.0,
        "refine": "REPLACE",
        "content": {"uri": "root.b3dm"},
        "children": [
            {"boundingVolume": {"region": _region(5e-4, 5e-4)},
             "geometricError": 0.0, "content": {"uri": "child.b3dm"}},
        ],
    }
    ts = build_runtime_tileset(_tileset(root), recenter=True)
    c, _ = ts.root.bounding_volume.bounding_sphere()
    assert np.linalg.norm(c) < 1.0e4  # brought home from ~6400 km out
    # The child region recenters by the same offset, staying next to the root.
    cc, _ = ts.root.children[0].bounding_volume.bounding_sphere()
    assert np.linalg.norm(cc) < 1.0e4


# -- external (nested) tilesets ---------------------------------------------

def _box(size=10.0):
    return {"box": [0, 0, 0, size, 0, 0, 0, size, 0, 0, 0, size]}


def test_external_tileset_is_grafted_as_child_subtree():
    external = {
        "asset": {"version": "1.1"},
        "geometricError": 20.0,
        "root": {
            "boundingVolume": _box(),
            "geometricError": 20.0,
            "refine": "REPLACE",
            "content": {"uri": "detail.b3dm"},
        },
    }

    def resolver(uri):
        assert uri == "sub/other.json"
        return external

    ts = build_runtime_tileset(_tileset({
        "boundingVolume": _box(),
        "geometricError": 100.0,
        "refine": "REPLACE",
        "content": {"uri": "sub/other.json"},
    }), resolve_external=resolver)

    # The referring tile drops the .json as content and gains the external root.
    assert ts.root.content_uri is None
    assert len(ts.root.children) == 1
    grafted = ts.root.children[0]
    # Its content resolves relative to the external tileset's own directory.
    assert grafted.content_uri == "sub/detail.b3dm"


def test_external_tileset_content_uri_resolves_against_base_uri():
    external = {"asset": {}, "geometricError": 5.0,
                "root": {"boundingVolume": _box(), "geometricError": 5.0,
                         "content": {"uri": "leaf.b3dm"}}}
    seen = []

    def resolver(uri):
        seen.append(uri)
        return external

    build_runtime_tileset(_tileset({
        "boundingVolume": _box(),
        "geometricError": 100.0,
        "content": {"uri": "child.json"},
    }), base_uri="http://host/tiles/", resolve_external=resolver)
    assert seen == ["http://host/tiles/child.json"]


def test_plural_contents_collected_on_tile():
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": _box(),
        "geometricError": 10.0,
        "refine": "ADD",
        "contents": [
            {"uri": "house.glb"},
            {"uri": "tree-a.glb"},
            {"uri": "tree-b.glb"},
        ],
    }), base_uri="scene/")
    assert ts.root.has_content
    assert ts.root.content_uris == [
        "scene/house.glb", "scene/tree-a.glb", "scene/tree-b.glb"]
    # content_uri (singular) stays available for one-content callers.
    assert ts.root.content_uri == "scene/house.glb"


def test_single_and_plural_content_combine():
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": _box(),
        "geometricError": 10.0,
        "content": {"uri": "a.b3dm"},
        "contents": [{"uri": "b.glb"}],
    }))
    assert ts.root.content_uris == ["a.b3dm", "b.glb"]


def test_plural_contents_split_external_json_from_geometry():
    external = {"asset": {}, "geometricError": 1.0,
                "root": {"boundingVolume": _box(), "geometricError": 1.0,
                         "content": {"uri": "leaf.glb"}}}
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": _box(),
        "geometricError": 10.0,
        "refine": "ADD",
        "contents": [
            {"uri": "building.glb"},
            {"uri": "sub.json"},        # external tileset among the contents
        ],
    }), resolve_external=lambda uri: external)
    # Geometry stays as content; the .json is grafted as a child subtree.
    assert ts.root.content_uris == ["building.glb"]
    assert len(ts.root.children) == 1
    assert ts.root.children[0].content_uri == "leaf.glb"


def test_external_tileset_unexpanded_when_resolver_is_none():
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": _box(),
        "geometricError": 100.0,
        "content": {"uri": "child.json"},
    }), resolve_external=None)
    # Without a resolver the .json stays as the tile's content, unexpanded.
    assert ts.root.content_uri == "child.json"
    assert ts.root.children == []


def test_external_tileset_cycle_is_rejected():
    def resolver(uri):
        # Always points back at another external tileset -> unbounded nesting.
        return {"asset": {}, "geometricError": 1.0,
                "root": {"boundingVolume": _box(), "geometricError": 1.0,
                         "content": {"uri": "loop.json"}}}

    with pytest.raises(ValueError):
        build_runtime_tileset(_tileset({
            "boundingVolume": _box(),
            "geometricError": 100.0,
            "content": {"uri": "loop.json"},
        }), resolve_external=resolver)


def test_parses_geometric_error_and_children():
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": {"box": [0, 0, 0, 50, 0, 0, 0, 50, 0, 0, 0, 50]},
        "geometricError": 50.0,
        "refine": "REPLACE",
        "content": {"uri": "root.glb"},
        "children": [
            {"boundingVolume": {"sphere": [10, 0, 0, 5]},
             "geometricError": 0.0,
             "content": {"uri": "a/child.glb"}},
        ],
    }))
    root = ts.root
    assert root.geometric_error == 50.0
    assert isinstance(root.bounding_volume, BoxBV)
    assert len(root.children) == 1
    assert isinstance(root.children[0].bounding_volume, SphereBV)


def test_refine_inherits_from_parent_when_absent():
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
        "geometricError": 10.0,
        "refine": "ADD",
        "children": [
            {"boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
             "geometricError": 0.0},  # no refine -> inherit ADD
        ],
    }))
    assert ts.root.refine == "ADD"
    assert ts.root.children[0].refine == "ADD"


def test_root_refine_defaults_to_replace():
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
        "geometricError": 10.0,
    }))
    assert ts.root.refine == "REPLACE"


def test_content_uri_resolved_against_base():
    ts = build_runtime_tileset(
        _tileset({
            "boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
            "geometricError": 10.0,
            "content": {"uri": "tiles/root.glb"},
        }),
        base_uri="/world/",
    )
    assert ts.root.content_uri == "/world/tiles/root.glb"


def test_content_uri_none_when_no_content():
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
        "geometricError": 10.0,
    }))
    assert ts.root.content_uri is None


def test_transform_moves_bounding_volume_into_world_space():
    # Root transform translates +100 in x (column-major 4x4).
    T = [1, 0, 0, 0,  0, 1, 0, 0,  0, 0, 1, 0,  100, 0, 0, 1]
    ts = build_runtime_tileset(_tileset({
        "transform": T,
        "boundingVolume": {"box": [0, 0, 0, 2, 0, 0, 0, 2, 0, 0, 0, 2]},
        "geometricError": 10.0,
    }))
    assert ts.root.bounding_volume.center == pytest.approx([100.0, 0.0, 0.0])
    # A point at world x=105 is 3 outside the half-extent-2 box.
    assert ts.root.bounding_volume.distance_to((105, 0, 0)) == pytest.approx(3.0)


def test_child_transform_composes_with_parent():
    T_parent = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 100, 0, 0, 1]
    T_child = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 0, 0, 1]
    ts = build_runtime_tileset(_tileset({
        "transform": T_parent,
        "boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
        "geometricError": 10.0,
        "children": [{
            "transform": T_child,
            "boundingVolume": {"sphere": [0, 0, 0, 1]},
            "geometricError": 0.0,
        }],
    }))
    # child world center = parent(+100) composed with child(+10) = +110
    assert ts.root.children[0].bounding_volume.center == pytest.approx([110.0, 0.0, 0.0])


def test_sphere_radius_scaled_by_transform():
    # Uniform scale of 3 in the transform triples the sphere radius.
    S = [3, 0, 0, 0, 0, 3, 0, 0, 0, 0, 3, 0, 0, 0, 0, 1]
    ts = build_runtime_tileset(_tileset({
        "transform": S,
        "boundingVolume": {"sphere": [0, 0, 0, 2]},
        "geometricError": 10.0,
    }))
    assert ts.root.bounding_volume.radius == pytest.approx(6.0)


def test_parent_and_ancestors_links():
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
        "geometricError": 10.0,
        "children": [
            {"boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
             "geometricError": 0.0,
             "children": [
                 {"boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
                  "geometricError": 0.0}]},
        ],
    }))
    root = ts.root
    assert root.parent is None
    mid = root.children[0]
    leaf = mid.children[0]
    assert mid.parent is root
    assert list(leaf.ancestors()) == [mid, root]


def test_iter_visits_every_tile():
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
        "geometricError": 10.0,
        "children": [
            {"boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
             "geometricError": 0.0},
            {"boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
             "geometricError": 0.0,
             "children": [
                 {"boundingVolume": {"box": [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]},
                  "geometricError": 0.0}]},
        ],
    }))
    assert sum(1 for _ in ts.iter_tiles()) == 4
