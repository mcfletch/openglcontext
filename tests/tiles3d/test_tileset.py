"""Runtime tileset tree: parse tileset.json into world-space RuntimeTiles.

Covers geometric error, refine inheritance, content-URI resolution, both box and
sphere bounding volumes (sphere is unsupported by py3dtiles, so we parse the tree
ourselves), and transform composition down the hierarchy into world space.
"""
import os

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

    base = os.path.realpath("tiles") + os.sep

    def resolver(uri):
        assert uri == os.path.join(base, "sub", "other.json")
        return external

    ts = build_runtime_tileset(_tileset({
        "boundingVolume": _box(),
        "geometricError": 100.0,
        "refine": "REPLACE",
        "content": {"uri": "sub/other.json"},
    }), base_uri=base, resolve_external=resolver)

    # The referring tile drops the .json as content and gains the external root.
    assert ts.root.content_uri is None
    assert len(ts.root.children) == 1
    grafted = ts.root.children[0]
    # Its content resolves relative to the external tileset's own directory.
    assert grafted.content_uri == os.path.join(base, "sub", "detail.b3dm")


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
    }), base_uri=os.path.realpath("scene") + os.sep)
    scene = os.path.realpath("scene")
    assert ts.root.has_content
    assert ts.root.content_uris == [os.path.join(scene, name) for name in
                                    ("house.glb", "tree-a.glb", "tree-b.glb")]
    # content_uri (singular) stays available for one-content callers.
    assert ts.root.content_uri == os.path.join(scene, "house.glb")


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


# -- glTF up axis -----------------------------------------------------------

def test_content_transform_turns_gltf_y_up_into_the_tiles_z_up_frame():
    """glTF content is Y-up; a tile's frame is Z-up, and content_transform bridges.

    A building modelled with its height along +Y has to stand along the tile
    frame's +Z, or every dataset that follows the specification lies on its side.
    """
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": _box(),
        "geometricError": 10.0,
        "content": {"uri": "a.b3dm"},
    }))
    up = ts.root.content_transform[:3, :3] @ np.array([0.0, 1.0, 0.0])
    assert np.allclose(up, [0.0, 0.0, 1.0])
    # The tile transform itself is untouched: bounding volumes are already Z-up.
    assert np.allclose(ts.root.world_transform, np.identity(4))


def test_content_transform_composes_with_the_tile_transform():
    """The conversion sits between the content and the tile's own placement."""
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": _box(),
        "geometricError": 10.0,
        # A quarter turn about +Z, so the frame's +Z is unchanged.
        "transform": [0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 7, 0, 0, 1],
        "content": {"uri": "a.b3dm"},
    }))
    point = ts.root.content_transform @ np.array([0.0, 2.0, 0.0, 1.0])
    assert np.allclose(point[:3], [7.0, 0.0, 2.0])


def test_gltf_up_axis_z_leaves_content_unrotated():
    """`asset.gltfUpAxis: "Z"` says the content is already in the tile's frame."""
    tileset = _tileset({
        "boundingVolume": _box(),
        "geometricError": 10.0,
        "content": {"uri": "a.b3dm"},
    })
    tileset["asset"]["gltfUpAxis"] = "Z"
    ts = build_runtime_tileset(tileset)
    assert np.allclose(ts.root.content_transform, np.identity(4))


def test_external_tileset_keeps_its_own_up_axis():
    """A sub-tileset declares the axis convention of the content it names."""
    external = {
        "asset": {"version": "1.1", "gltfUpAxis": "Z"},
        "geometricError": 5.0,
        "root": {"boundingVolume": _box(), "geometricError": 5.0,
                 "content": {"uri": "leaf.b3dm"}},
    }
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": _box(),
        "geometricError": 100.0,
        "content": {"uri": "child.json"},
    }), resolve_external=lambda uri: external)
    grafted = ts.root.children[0]
    assert np.allclose(grafted.content_transform, np.identity(4))


# -- levelling a geospatial dataset -----------------------------------------

def _enu_tileset(longitude=-1.3856, latitude=0.7617):
    """A tileset mounted the way a geospatial exporter writes one.

    The root transform is an east/north/up frame at the given point, which is how
    b3dm content is placed on the globe, and the content is a metre above it.
    """
    from OpenGLContext.loaders.tiles3d.boundingvolume import (
        geodetic_to_ecef, WGS84_A, WGS84_B)
    origin = geodetic_to_ecef(longitude, latitude, 0.0)
    # Up is the ellipsoid normal, which is what an east/north/up frame means and
    # is a fifth of a degree off the direction back to the geocentre.
    up = np.array([origin[0] / WGS84_A ** 2, origin[1] / WGS84_A ** 2,
                   origin[2] / WGS84_B ** 2])
    up /= np.linalg.norm(up)
    east = np.cross([0.0, 0.0, 1.0], up)
    east /= np.linalg.norm(east)
    north = np.cross(up, east)
    matrix = np.identity(4)
    matrix[:3, 0], matrix[:3, 1], matrix[:3, 2] = east, north, up
    matrix[:3, 3] = origin
    return _tileset({
        "boundingVolume": {"box": [0, 0, 50, 500, 0, 0, 0, 500, 0, 0, 0, 50]},
        "geometricError": 100.0,
        "transform": list(matrix.T.reshape(-1)),
        "content": {"uri": "tile.b3dm"},
    }), origin


def test_recentred_geospatial_dataset_is_levelled_into_the_viewers_frame():
    """Content modelled upright stands upright, with the ground at the origin.

    A Y-up viewer has no globe to stand on, so an earth-centred dataset arrives
    levelled: the reference point's local up becomes +Y and its north -Z.
    """
    document, origin = _enu_tileset()
    ts = build_runtime_tileset(document, recenter=True)
    up = ts.root.content_transform[:3, :3] @ np.array([0.0, 1.0, 0.0])
    assert np.allclose(up, [0.0, 1.0, 0.0], atol=1e-9)
    centre, _radius = ts.root.bounding_volume.bounding_sphere()
    assert np.linalg.norm(centre) < 1.0e3      # brought home from 6400 km out
    assert centre[1] == pytest.approx(50.0)    # 50 m up, not 50 m north


def test_levelling_keeps_distances_and_needs_recentring():
    """Levelling is a rotation, so the dataset keeps its size; without
    `recenter` the dataset stays in its earth-centred frame."""
    document, origin = _enu_tileset()
    levelled = build_runtime_tileset(document, recenter=True).root.bounding_volume
    raw = build_runtime_tileset(document, recenter=False).root.bounding_volume
    assert levelled.bounding_sphere()[1] == pytest.approx(raw.bounding_sphere()[1])
    assert np.linalg.norm(raw.bounding_sphere()[0]) == pytest.approx(
        np.linalg.norm(origin), rel=1e-3)


def test_a_local_dataset_is_turned_rather_than_levelled():
    """A tileset that is not earth-centred has no local up to level against, so
    its own Z-up frame is turned into the viewer's Y-up world instead."""
    from OpenGLContext.loaders.tiles3d.tileset import Z_UP_TO_Y_UP
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": _box(),
        "geometricError": 10.0,
        "content": {"uri": "a.b3dm"},
    }), recenter=True)
    assert np.allclose(ts.root.world_transform, Z_UP_TO_Y_UP)


# -- a local dataset in the viewer's frame -----------------------------------

def _content_up(tileset):
    """Where a tile's content sends its own up axis, in world space."""
    tile = next(t for t in tileset.iter_tiles() if t.has_content)
    up = tile.content_transform[:3, :3] @ np.array([0.0, 1.0, 0.0])
    return up / np.linalg.norm(up)


def test_a_local_dataset_arrives_up_the_viewers_way():
    """3D Tiles frames are Z-up and this viewer's world is Y-up.

    Converting the content into its tile's frame and stopping there leaves the
    whole dataset on its side -- which is what the Cesium local samples did once
    the conversion was honoured and nothing turned the dataset itself.
    """
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": {"box": [0, 0, 0, 10, 0, 0, 0, 10, 0, 0, 0, 10]},
        "geometricError": 10.0,
        "content": {"uri": "a.glb"},
    }), recenter=True)
    assert np.allclose(_content_up(ts), [0.0, 1.0, 0.0], atol=1e-9)


def test_a_geospatial_dataset_is_levelled_rather_than_turned():
    """Both roads end up Y-up; the globe's is the reference point's own up."""
    document, _origin = _enu_tileset()
    ts = build_runtime_tileset(document, recenter=True)
    assert np.allclose(_content_up(ts), [0.0, 1.0, 0.0], atol=1e-9)


def test_the_raw_frame_is_still_available():
    """`--no-recenter` asks for the dataset as it was written."""
    ts = build_runtime_tileset(_tileset({
        "boundingVolume": {"box": [0, 0, 0, 10, 0, 0, 0, 10, 0, 0, 0, 10]},
        "geometricError": 10.0,
        "content": {"uri": "a.glb"},
    }), recenter=False)
    assert np.allclose(_content_up(ts), [0.0, 0.0, 1.0], atol=1e-9)


def test_a_local_datasets_bounding_volume_turns_with_it():
    """Content and bounds have to move together, or culling drops what is drawn."""
    ts = build_runtime_tileset(_tileset({
        # A slab 100 wide and 4 high in its own Z-up frame.
        "boundingVolume": {"box": [0, 0, 2, 100, 0, 0, 0, 100, 0, 0, 0, 2]},
        "geometricError": 10.0,
        "content": {"uri": "a.glb"},
    }), recenter=True)
    centre, _radius = ts.root.bounding_volume.bounding_sphere()
    assert centre[1] == pytest.approx(2.0)     # the height is up, not north
    assert abs(centre[2]) < 1e-9


def test_a_tile_finds_a_texture_named_beside_its_tileset(tmp_path):
    """3D Tiles content is read as bytes, so the loader has to be told where the
    tile came from or a shared texture cannot be found."""
    import numpy as np
    from PIL import Image

    from OpenGLContext.loaders.gltf.writer import ExternalImage, write_glb
    from OpenGLContext.loaders.tiles3d.gltf_uploader import file_tile_loader
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh

    Image.new('RGBA', (4, 4), (7, 200, 9, 255)).save(str(tmp_path / 'shared.png'))
    material = PBRMaterial()
    material.textures = {'baseColor': ExternalImage('shared.png', srgb=True)}
    mesh = PBRMesh(positions=np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0)], 'f'),
                   material=material)
    write_glb(mesh, path=str(tmp_path / 'tile.glb'))

    class _Tile:
        content_uris = [str(tmp_path / 'tile.glb')]

    scene, nbytes = file_tile_loader(_Tile())
    assert nbytes > 0
    found = []
    stack = [scene.group]
    while stack:
        node = stack.pop()
        appearance = getattr(node, 'appearance', None)
        if appearance is not None and appearance.material is not None:
            found.append(appearance.material)
        stack.extend(getattr(node, 'children', None) or [])
    assert any('baseColor' in m.textures for m in found)
