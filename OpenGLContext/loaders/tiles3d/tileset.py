"""Parse a tileset.json into a world-space runtime tree.

The tileset bounding-volume hierarchy is read into `RuntimeTile`s whose bounding
volumes are already composed into world space (each tile's `transform` combined with
its ancestors'), so per-frame traversal only measures distances and compares errors.

We parse the tree ourselves rather than via py3dtiles: py3dtiles' tile reader raises
`NotImplementedError` for `sphere`/`region` volumes, which terrain tilesets use.
py3dtiles remains the tool for tile *content* and bake-side writing.
"""
import json
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, Optional, Union

import numpy as np

from OpenGLContext.loaders.tiles3d import fetch
from OpenGLContext.loaders.tiles3d.boundingvolume import (
    SphereBV, BoxBV, RegionBV, WGS84_A, WGS84_B,
)

BoundingVolume = Union[SphereBV, BoxBV, RegionBV]

_IDENTITY = np.identity(4, dtype="d")

#: Rotations from a glTF up axis into the tile's Z-up frame, keyed by the axis
#: `asset.gltfUpAxis` names. glTF models are Y-up and 3D Tiles frames are Z-up, so
#: content is rotated a quarter turn about +X unless the tileset says otherwise;
#: "Z" content is already in the tile's frame, and "X" turns about +Z first.
_UP_AXIS_TO_Z_UP: dict[str, np.ndarray] = {
    "X": np.array([[0.0, -1.0, 0.0, 0.0],
                   [0.0, 0.0, 1.0, 0.0],
                   [-1.0, 0.0, 0.0, 0.0],
                   [0.0, 0.0, 0.0, 1.0]], dtype="d"),
    "Y": np.array([[1.0, 0.0, 0.0, 0.0],
                   [0.0, 0.0, -1.0, 0.0],
                   [0.0, 1.0, 0.0, 0.0],
                   [0.0, 0.0, 0.0, 1.0]], dtype="d"),
    "Z": _IDENTITY,
}

#: What a tileset means when it does not say (3D Tiles 1.0 and 1.1 both default
#: glTF content to Y-up).
DEFAULT_GLTF_UP_AXIS = "Y"

#: A quarter turn about -X: the rotation from the Z-up frame 3D Tiles places
#: tiles in to the Y-up world this renderer draws them in.  A dataset that is
#: not on the globe has no reference point to level against, so this is what
#: stands it up instead.
Z_UP_TO_Y_UP = np.array([[1.0, 0.0, 0.0, 0.0],
                         [0.0, 0.0, 1.0, 0.0],
                         [0.0, -1.0, 0.0, 0.0],
                         [0.0, 0.0, 0.0, 1.0]], dtype="d")


def gltf_up_axis_matrix(asset: Optional[dict[str, Any]]) -> np.ndarray:
    """The rotation taking a tileset's glTF content into its tiles' Z-up frame.

    `asset` is a tileset document's `asset` object, whose optional `gltfUpAxis`
    names the axis the content treats as up. An unknown value falls back to the
    default rather than refusing the dataset.
    """
    axis = str((asset or {}).get("gltfUpAxis", DEFAULT_GLTF_UP_AXIS)).upper()
    return _UP_AXIS_TO_Z_UP.get(axis, _UP_AXIS_TO_Z_UP[DEFAULT_GLTF_UP_AXIS])


class RuntimeTile:
    """A tile in the runtime hierarchy, bounding volume in world space.

    A tile may carry several content URIs: 3D Tiles 1.0 has one `content`, while 1.1
    allows a `contents` array (e.g. buildings and trees as separate glTF in one tile).
    `content_uris` holds them all; `content_uri` returns the first for single-content
    callers.

    Two transforms, because a tile's frame and its content's are not the same one.
    `world_transform` places the tile: bounding volumes are expressed in the tile's
    Z-up frame and use it as it stands. `content_transform` places the glTF inside
    the tile, and carries the extra rotation from the content's up axis (Y for
    everything that does not say otherwise) into that Z-up frame.
    """

    def __init__(
        self,
        bounding_volume: BoundingVolume,
        geometric_error: float,
        refine: str,
        content_uris: Optional[Iterable[str]],
        world_transform: np.ndarray,
        children: "list[RuntimeTile]",
        up_axis_matrix: np.ndarray = _IDENTITY,
    ) -> None:
        self.bounding_volume = bounding_volume
        self.geometric_error = float(geometric_error)
        self.refine = refine
        self.content_uris = list(content_uris) if content_uris else []
        self.world_transform = world_transform
        self.content_transform = world_transform @ up_axis_matrix
        self.children = children
        self.parent: Optional[RuntimeTile] = None
        for child in children:
            child.parent = self

    def ancestors(self) -> "Iterator[RuntimeTile]":
        """Yield this tile's ancestors from immediate parent up to the root."""
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    @property
    def content_uri(self) -> Optional[str]:
        return self.content_uris[0] if self.content_uris else None

    @property
    def has_content(self) -> bool:
        return bool(self.content_uris)

    def iter_tiles(self) -> "Iterator[RuntimeTile]":
        yield self
        for child in self.children:
            yield from child.iter_tiles()


class RuntimeTileset:
    """A parsed tileset: its root tile plus top-level metadata.

    `geospatial` is whether the dataset is placed on the globe -- an
    Earth-centred root transform or a `region` volume. Such a dataset is in
    metres by specification, which is how a viewer knows how big a person is in
    it without being told.
    """

    def __init__(
        self, root: RuntimeTile, root_geometric_error: float, asset: dict[str, Any],
        geospatial: bool = False,
    ) -> None:
        self.root = root
        self.root_geometric_error = root_geometric_error
        self.asset = asset
        self.geospatial = geospatial

    def iter_tiles(self) -> Iterator[RuntimeTile]:
        return self.root.iter_tiles()


def _matrix_from_list(values: Sequence[float]) -> np.ndarray:
    # 3D Tiles transforms are 16 column-major values.
    return np.asarray(values, dtype="d").reshape(4, 4).T


def _transform_point(matrix: np.ndarray, point: np.ndarray) -> np.ndarray:
    p = np.ones(4, dtype="d")
    p[:3] = point
    return (matrix @ p)[:3]


def _transform_vector(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    return matrix[:3, :3] @ np.asarray(vector, dtype="d")


def _world_bounding_volume(
    bv_dict: dict[str, Any], matrix: np.ndarray, recenter_offset: np.ndarray,
    recenter_rotation: Optional[np.ndarray] = None,
) -> BoundingVolume:
    if "box" in bv_dict:
        b = np.asarray(bv_dict["box"], dtype="d")
        center = _transform_point(matrix, b[0:3])
        half_axes = [_transform_vector(matrix, b[3:6]),
                     _transform_vector(matrix, b[6:9]),
                     _transform_vector(matrix, b[9:12])]
        return BoxBV(center, half_axes)
    if "sphere" in bv_dict:
        s = np.asarray(bv_dict["sphere"], dtype="d")
        center = _transform_point(matrix, s[0:3])
        # Scale the radius by the largest axis scale so the sphere stays enclosing.
        scale = max(np.linalg.norm(matrix[:3, i]) for i in range(3))
        return SphereBV(center, float(s[3]) * scale)
    if "region" in bv_dict:
        # Regions are fixed to the WGS 84 datum and ignore the tile transform; only
        # the recenter offset (a pure ECEF translation) applies.
        return RegionBV(bv_dict["region"], offset=recenter_offset,
                        rotation=recenter_rotation)
    raise NotImplementedError(
        "Only box, sphere and region bounding volumes are supported (got %s)"
        % ", ".join(bv_dict)
    )


def _raw_content_uris(tile_dict: dict[str, Any]) -> list[str]:
    """Every content URI on a tile: 1.0 `content` and/or 1.1 `contents` (plural)."""
    uris = []
    single = tile_dict.get("content")
    if single:
        uri = single.get("uri", single.get("url"))
        if uri:
            uris.append(uri)
    for entry in tile_dict.get("contents", []) or []:
        uri = entry.get("uri", entry.get("url"))
        if uri:
            uris.append(uri)
    return uris


def _resolve_uri(uri: Optional[str], base_uri: str) -> Optional[str]:
    return fetch.resolve_uri(base_uri, uri) if uri else uri


def _is_external_tileset(uri: Optional[str]) -> bool:
    return uri is not None and uri.split("?", 1)[0].lower().endswith(".json")


_MAX_EXTERNAL_DEPTH = 32


def _build_tile(
    tile_dict: dict[str, Any],
    base_uri: str,
    parent_transform: np.ndarray,
    parent_refine: str,
    recenter_offset: np.ndarray,
    resolve_external: "Optional[Callable[[str], dict[str, Any]]]",
    depth: int,
    up_axis_matrix: np.ndarray = _IDENTITY,
    recenter_rotation: Optional[np.ndarray] = None,
) -> RuntimeTile:
    local = tile_dict.get("transform")
    matrix = parent_transform @ _matrix_from_list(local) if local else parent_transform
    refine = tile_dict.get("refine", parent_refine).upper()
    bv = _world_bounding_volume(tile_dict["boundingVolume"], matrix,
                                recenter_offset, recenter_rotation)
    children = [
        _build_tile(child, base_uri, matrix, refine, recenter_offset,
                    resolve_external, depth, up_axis_matrix, recenter_rotation)
        for child in tile_dict.get("children", [])
    ]

    # Content URIs split two ways: an external tileset (`.json`) is grafted in as a
    # subtree to refine into, while glTF/b3dm URIs become this tile's drawable content
    # (1.1 lets a tile hold several, e.g. buildings and trees in one tile).
    content_uris: list[str] = []
    for raw in _raw_content_uris(tile_dict):
        resolved = _resolve_uri(raw, base_uri)
        if resolved is None:  # pragma: no cover - _raw_content_uris yields only
            continue          # truthy URIs and _resolve_uri returns str for those
        if _is_external_tileset(raw) and resolve_external is not None:
            if depth >= _MAX_EXTERNAL_DEPTH:
                raise ValueError(
                    "external tileset nesting exceeds %d levels (cyclic reference?)"
                    % _MAX_EXTERNAL_DEPTH)
            sub_doc = resolve_external(resolved)
            # An external tileset describes its own content, up axis included.
            sub_root = _build_tile(
                sub_doc["root"], _dir_of(resolved), matrix, refine,
                recenter_offset, resolve_external, depth + 1,
                gltf_up_axis_matrix(sub_doc.get("asset")), recenter_rotation)
            children.append(sub_root)
        else:
            content_uris.append(resolved)

    return RuntimeTile(
        bounding_volume=bv,
        geometric_error=tile_dict["geometricError"],
        refine=refine,
        content_uris=content_uris,
        world_transform=matrix,
        children=children,
        up_axis_matrix=up_axis_matrix,
    )


def _dir_of(uri: Optional[str]) -> str:
    return fetch.dir_of(uri) if uri else ""


def level_matrix(origin: np.ndarray) -> np.ndarray:
    """The rotation taking the ECEF frame to a Y-up frame level at `origin`.

    An earth-centred dataset has its up direction wherever the globe puts it,
    which in a Y-up viewer leaves the ground as a tilted slab. This maps the
    ellipsoid normal at `origin` onto +Y, east onto +X and north onto -Z, so the
    dataset arrives the way a scene authored for the viewer would be.
    """
    up = np.array([origin[0] / WGS84_A ** 2, origin[1] / WGS84_A ** 2,
                   origin[2] / WGS84_B ** 2], dtype="d")
    norm = np.linalg.norm(up)
    if not norm:                     # pragma: no cover - the geocentre itself
        return np.identity(4, dtype="d")
    up /= norm
    east = np.cross([0.0, 0.0, 1.0], up)
    east_norm = np.linalg.norm(east)
    # Directly under a pole every direction is east; pick one rather than divide
    # by zero.
    east = east / east_norm if east_norm > 1e-12 else np.array([1.0, 0.0, 0.0])
    north = np.cross(up, east)
    matrix = np.identity(4, dtype="d")
    matrix[0, :3], matrix[1, :3], matrix[2, :3] = east, up, -north
    return matrix


def _recenter_offset(root_dict: dict[str, Any]) -> np.ndarray:
    """The ECEF point to shift to the origin so a geospatial tileset stays precise.

    A root transform's translation places transform-mounted content (the common
    b3dm-at-ECEF case); otherwise a root `region` volume's centre stands in, so
    datum-fixed region tilesets recenter too.
    """
    local = root_dict.get("transform")
    if local:
        t = _matrix_from_list(local)
        if np.any(t[:3, 3]):
            return t[:3, 3].copy()
    bv = root_dict.get("boundingVolume", {})
    if "region" in bv:
        return RegionBV(bv["region"]).ecef_center()
    return np.zeros(3, dtype="d")


def _default_external_resolver(uri: str) -> dict[str, Any]:
    """Read and parse an external tileset (`.json`), local path or http(s) URL."""
    return json.loads(fetch.read_bytes(uri))


def build_runtime_tileset(
    tileset_dict: dict[str, Any],
    base_uri: str = "",
    recenter: bool = False,
    resolve_external: "Optional[Callable[[str], dict[str, Any]]]" = (
        _default_external_resolver
    ),
) -> RuntimeTileset:
    """Build a `RuntimeTileset` from a parsed tileset.json dict.

    `base_uri` prefixes every relative tile `content.uri` so payloads resolve against
    the tileset's location. The root tile's refine defaults to REPLACE per spec.

    A tile whose content is a `.json` is an *external tileset*: its subtree lives in
    another file. `resolve_external(uri) -> dict` reads and parses it (local files by
    default); pass `None` to leave such tiles unexpanded, or a custom resolver to
    fetch remote tilesets. The external subtree is re-rooted under the referring
    tile's transform and grafted in as a child to refine into.

    Each tile also gets a `content_transform`, which is its `world_transform` with
    the rotation from the content's up axis (`asset.gltfUpAxis`, Y unless the
    document says otherwise) applied first, so glTF content stands up in the tile's
    Z-up frame. An external tileset's own `asset` governs the content it names.

    `recenter` is what adapts a dataset to the frame this renderer draws in, and
    covers both halves of that. A tileset on the globe is brought home to the
    origin and levelled at its reference point; one that is not is turned from
    the Z-up frame 3D Tiles places tiles in to the viewer's Y-up world, which is
    a rotation and nothing else. Switched off, a dataset arrives exactly as it
    was written.

    `recenter` subtracts a large ECEF offset from every tile, so an Earth-Centered
    geospatial tileset renders near the origin instead of ~6.4M metres out (where
    32-bit float precision would shatter it). The offset is the root transform's
    translation for transform-placed tiles (e.g. a b3dm at an ECEF origin), or the
    root region's ECEF centre for `region` tilesets (whose tiles carry no transform).
    Box/sphere volumes absorb the offset through the tile matrix; region volumes,
    which ignore the tile transform, receive it directly. The root keeps its
    orientation; only the huge translation is removed.
    """
    root_dict = tileset_dict["root"]
    initial = _IDENTITY
    recenter_offset = np.zeros(3, dtype="d")
    recenter_rotation = None
    if recenter:
        recenter_offset = _recenter_offset(root_dict)
        if np.any(recenter_offset):
            recenter_rotation = level_matrix(recenter_offset)
            initial = np.identity(4, dtype="d")
            initial[:3, 3] = -recenter_offset
            initial = recenter_rotation @ initial
        else:
            # Not on the globe, so there is no local up to level against: the
            # dataset's own Z-up frame becomes the viewer's Y-up world.
            recenter_rotation = Z_UP_TO_Y_UP
            initial = Z_UP_TO_Y_UP
    root = _build_tile(root_dict, base_uri, initial, parent_refine="REPLACE",
                       recenter_offset=recenter_offset,
                       resolve_external=resolve_external, depth=0,
                       up_axis_matrix=gltf_up_axis_matrix(
                           tileset_dict.get("asset")),
                       recenter_rotation=recenter_rotation)
    return RuntimeTileset(
        root=root,
        root_geometric_error=float(tileset_dict.get("geometricError", 0.0)),
        asset=tileset_dict.get("asset", {}),
        geospatial=bool(np.any(_recenter_offset(root_dict))),
    )
