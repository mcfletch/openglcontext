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
    SphereBV, BoxBV, RegionBV,
)

BoundingVolume = Union[SphereBV, BoxBV, RegionBV]

_IDENTITY = np.identity(4, dtype="d")


class RuntimeTile:
    """A tile in the runtime hierarchy, bounding volume in world space.

    A tile may carry several content URIs: 3D Tiles 1.0 has one `content`, while 1.1
    allows a `contents` array (e.g. buildings and trees as separate glTF in one tile).
    `content_uris` holds them all; `content_uri` returns the first for single-content
    callers.
    """

    def __init__(
        self,
        bounding_volume: BoundingVolume,
        geometric_error: float,
        refine: str,
        content_uris: Optional[Iterable[str]],
        world_transform: np.ndarray,
        children: "list[RuntimeTile]",
    ) -> None:
        self.bounding_volume = bounding_volume
        self.geometric_error = float(geometric_error)
        self.refine = refine
        self.content_uris = list(content_uris) if content_uris else []
        self.world_transform = world_transform
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
    """A parsed tileset: its root tile plus top-level metadata."""

    def __init__(
        self, root: RuntimeTile, root_geometric_error: float, asset: dict[str, Any]
    ) -> None:
        self.root = root
        self.root_geometric_error = root_geometric_error
        self.asset = asset

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
    bv_dict: dict[str, Any], matrix: np.ndarray, recenter_offset: np.ndarray
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
        return RegionBV(bv_dict["region"], offset=recenter_offset)
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
) -> RuntimeTile:
    local = tile_dict.get("transform")
    matrix = parent_transform @ _matrix_from_list(local) if local else parent_transform
    refine = tile_dict.get("refine", parent_refine).upper()
    bv = _world_bounding_volume(tile_dict["boundingVolume"], matrix,
                                recenter_offset)
    children = [
        _build_tile(child, base_uri, matrix, refine, recenter_offset,
                    resolve_external, depth)
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
            sub_root = _build_tile(
                sub_doc["root"], _dir_of(resolved), matrix, refine,
                recenter_offset, resolve_external, depth + 1)
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
    )


def _dir_of(uri: Optional[str]) -> str:
    return fetch.dir_of(uri) if uri else ""


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
    if recenter:
        recenter_offset = _recenter_offset(root_dict)
        if np.any(recenter_offset):
            initial = np.identity(4, dtype="d")
            initial[:3, 3] = -recenter_offset
    root = _build_tile(root_dict, base_uri, initial, parent_refine="REPLACE",
                       recenter_offset=recenter_offset,
                       resolve_external=resolve_external, depth=0)
    return RuntimeTileset(
        root=root,
        root_geometric_error=float(tileset_dict.get("geometricError", 0.0)),
        asset=tileset_dict.get("asset", {}),
    )
