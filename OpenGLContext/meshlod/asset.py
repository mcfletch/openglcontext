"""Levels of detail on disk, in a glB a normal glTF reader can still open.

Two hundred assets each carrying an ultra-high-resolution original cannot be
decimated when the player opens the door: the reduction is seconds per asset,
and it is the same answer every time. It is baked once, and what ships is the
chain. The question is then what the chain looks like on disk, and the answer
has to satisfy two things at once -- a finer level must not cost memory,
bandwidth or parse time until something asks for it, and the file should still
be a file other tools understand.

glTF answers both, without an invention:

**A glB may point outside itself.** The binary chunk inside a glB is buffer
zero and is the one buffer with no ``uri``. Every *other* buffer is an ordinary
glTF buffer and may name an external file. So the coarse levels live in the
chunk, always there and always cheap, and each finer level is its own sidecar
that the operating system never opens until it is wanted.

**glTF is addressable.** Every array reaches its bytes through
``accessor -> bufferView -> buffer``, and a bufferView is an offset and a
length. There is no container to walk, no compression spanning the file and no
need to read what comes before: a level's vertices are a known byte range in a
known file, and reading it is a seek and a read. The one thing that must be
parsed is the JSON chunk, which is kilobytes.

**The levels are declared the way the ecosystem declares them**, with
``MSFT_lod``: the node carrying the extension is the finest, ``ids`` lists the
coarser alternatives in decreasing detail, and ``MSFT_screencoverage`` in
``extras`` says at what share of the screen each takes over. A reader that does
not know the extension ignores it and draws the finest level, which is the
correct thing for it to do; a reader that does know it picks a level.

    from OpenGLContext.meshlod import write_chain, LODAsset

    write_chain('bust.glb', chain)          # bust.glb + bust.lod0.bin, ...

    asset = LODAsset.open('bust.glb')       # parses kilobytes of JSON
    asset.levels[-1].triangle_count         # the coarsest, in the glb itself
    asset.load(len(asset.levels) - 1)       # a seek and a read
"""

from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from typing import Any

import numpy as np

__all__ = ["LODAsset", "LODEntry", "write_chain", "sidecar_name"]

#: glTF component types, for the accessors written here.
_FLOAT = 5126
_UNSIGNED_INT = 5125
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963
_TRIANGLES = 4

#: How wide each attribute is and what glTF calls that shape.
_ATTRIBUTES = {
    "POSITION": (3, "VEC3"),
    "NORMAL": (3, "VEC3"),
    "TANGENT": (4, "VEC4"),
    "TEXCOORD_0": (2, "VEC2"),
    "TEXCOORD_1": (2, "VEC2"),
    "COLOR_0": (4, "VEC4"),
}

_GLB_MAGIC = 0x46546C67
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942


def sidecar_name(path: str, level: int) -> str:
    """Where level ``level``'s geometry lives beside ``path``."""
    stem, _ = os.path.splitext(path)
    return "%s.lod%d.bin" % (stem, level)


@dataclass(frozen=True)
class LODEntry:
    """One level, as the file describes it before anything is read.

    Everything here comes from the JSON chunk, so a caller can decide which
    level it wants -- and what that will cost -- without touching the geometry.
    """

    level: int
    triangle_count: int
    vertex_count: int
    error: float
    #: Share of the screen's height at or above which this level is the one to
    #: draw, as ``MSFT_screencoverage`` states it.
    screen_coverage: float
    #: Where the bytes are: the sidecar's name, or None for the glb's own chunk.
    source: str | None
    byte_length: int


class LODAsset:
    """A baked chain, opened without reading its geometry.

    :meth:`open` parses the JSON chunk and nothing else. :meth:`load` reads one
    level's byte ranges and returns the arrays for it, so a level that is never
    asked for is never read, never decoded and never in memory.
    """

    def __init__(self, path: str, document: dict[str, Any], binary_offset: int) -> None:
        self.path = path
        self.document = document
        self._binary_offset = binary_offset
        self.levels = tuple(_describe(path, document))

    @classmethod
    def open(cls, path: str) -> LODAsset:
        """Read the JSON chunk of a glb and stop there."""
        with open(path, "rb") as handle:
            magic, _version, _length = struct.unpack("<III", handle.read(12))
            if magic != _GLB_MAGIC:
                raise ValueError("%r is not a glb" % (path,))
            json_length, json_kind = struct.unpack("<II", handle.read(8))
            if json_kind != _JSON_CHUNK:
                raise ValueError("%r does not begin with a JSON chunk" % (path,))
            document = json.loads(handle.read(json_length))
            binary_offset = 12 + 8 + json_length
            header = handle.read(8)
            if len(header) == 8:
                _chunk_length, chunk_kind = struct.unpack("<II", header)
                if chunk_kind == _BIN_CHUNK:
                    binary_offset += 8
        return cls(path, document, binary_offset)

    def load(self, level: int) -> tuple[dict[str, np.ndarray], np.ndarray]:
        """The arrays for one level, read from wherever that level's bytes are.

        Only the byte ranges this level's accessors name are read. A sidecar
        holding a finer level is opened here and nowhere else.
        """
        primitive = self.document["meshes"][level]["primitives"][0]
        attributes = {
            name: self._read_accessor(index) for name, index in primitive["attributes"].items()
        }
        return attributes, self._read_accessor(primitive["indices"])

    def _read_accessor(self, index: int) -> np.ndarray:
        accessor = self.document["accessors"][index]
        view = self.document["bufferViews"][accessor["bufferView"]]
        buffer = self.document["buffers"][view["buffer"]]
        width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[accessor["type"]]
        dtype = np.dtype("<f4" if accessor["componentType"] == _FLOAT else "<u4")
        start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        count = accessor["count"] * width * dtype.itemsize

        uri = buffer.get("uri")
        if uri is None:
            source, start = self.path, start + self._binary_offset
        else:
            source = os.path.join(os.path.dirname(self.path), uri)
        with open(source, "rb") as handle:
            handle.seek(start)
            raw = handle.read(count)
        if len(raw) != count:
            raise ValueError("%s is short: wanted %d bytes at %d" % (source, count, start))
        values = np.frombuffer(raw, dtype=dtype)
        return values if width == 1 else values.reshape(-1, width)


def _describe(path: str, document: dict[str, Any]) -> list[LODEntry]:
    """What the JSON says about each level, finest first."""
    coverage = document["nodes"][0].get("extras", {}).get("MSFT_screencoverage", [])
    errors = document.get("extras", {}).get("OPENGLCONTEXT_lod_error", [])
    out = []
    for level, mesh in enumerate(document["meshes"]):
        primitive = mesh["primitives"][0]
        position = document["accessors"][primitive["attributes"]["POSITION"]]
        indices = document["accessors"][primitive["indices"]]
        buffer = document["buffers"][document["bufferViews"][position["bufferView"]]["buffer"]]
        out.append(
            LODEntry(
                level=level,
                triangle_count=indices["count"] // 3,
                vertex_count=position["count"],
                error=float(errors[level]) if level < len(errors) else 0.0,
                screen_coverage=(float(coverage[level]) if level < len(coverage) else 0.0),
                source=buffer.get("uri"),
                byte_length=buffer["byteLength"],
            )
        )
    del path
    return out


def _place(
    document: dict[str, Any],
    blob: bytearray,
    buffer_index: int,
    values: np.ndarray,
    target: int,
    kind: str,
    component: int,
    bounded: bool = False,
) -> int:
    """Append one array to a level's blob; return the accessor that names it."""
    blob.extend(b"\0" * _pad(len(blob)))
    document["bufferViews"].append(
        {
            "buffer": buffer_index,
            "byteOffset": len(blob),
            "byteLength": values.nbytes,
            "target": target,
        }
    )
    blob.extend(values.tobytes())
    accessor: dict[str, Any] = {
        "bufferView": len(document["bufferViews"]) - 1,
        "componentType": component,
        "count": len(values),
        "type": kind,
    }
    if bounded:
        # glTF requires min/max on POSITION, and a reader uses them to cull
        # without touching the geometry -- which is the point of a file whose
        # geometry it has not read.
        points = np.asarray(values, dtype="d")
        accessor["min"] = points.min(axis=0).tolist()
        accessor["max"] = points.max(axis=0).tolist()
    document["accessors"].append(accessor)
    return len(document["accessors"]) - 1


def _pad(length: int, to: int = 4) -> int:
    """glTF wants every chunk and every bufferView aligned."""
    return (to - length % to) % to


def write_chain(
    path: str,
    chain: Any,
    coverage: Any = None,
    embed_coarsest: int = 1,
) -> list[str]:
    """Write a chain as a glb plus one sidecar per level kept out of it.

    ``embed_coarsest`` levels go into the glb's own binary chunk -- they are the
    ones always wanted, and a file that needs no sidecar to draw something is a
    file that always draws something. Every finer level becomes its own
    ``.lodN.bin``, so the cost of having it is a directory entry until it is
    asked for.

    ``coverage`` is the ``MSFT_screencoverage`` list, finest first; without one
    a geometric series is written, which is the right shape for levels that
    halve.

    Returns the paths written, the glb first.
    """
    levels = list(chain)
    if not levels:
        raise ValueError("a chain with no levels cannot be written")
    if coverage is None:
        coverage = [0.5 / (2**index) for index in range(len(levels))]

    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "OpenGLContext.meshlod"},
        "extensionsUsed": ["MSFT_lod"],
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [],
        "meshes": [],
        "accessors": [],
        "bufferViews": [],
        "buffers": [],
        "extras": {"OPENGLCONTEXT_lod_error": [float(level.error) for level in levels]},
    }

    # The finest level is the node that carries the extension; the rest are
    # listed on it in decreasing detail, which is how MSFT_lod is read.
    document["nodes"].append(
        {
            "mesh": 0,
            "extensions": {"MSFT_lod": {"ids": list(range(1, len(levels)))}},
            "extras": {"MSFT_screencoverage": [float(c) for c in coverage]},
        }
    )
    for level in range(1, len(levels)):
        document["nodes"].append({"mesh": level})

    embedded = bytearray()
    sidecars: dict[int, bytearray] = {}
    written = [path]

    for index, level in enumerate(levels):
        # The coarsest few ride inside the glb; everything finer is a sidecar.
        in_glb = index >= len(levels) - embed_coarsest
        if in_glb:
            buffer_index = 0
            blob = embedded
        else:
            buffer_index = len(sidecars) + 1
            blob = sidecars.setdefault(index, bytearray())

        attributes: dict[str, int] = {}
        for name, (_width, kind) in _ATTRIBUTES.items():
            if name in level.attributes:
                attributes[name] = _place(
                    document,
                    blob,
                    buffer_index,
                    np.ascontiguousarray(level.attributes[name], dtype="<f4"),
                    _ARRAY_BUFFER,
                    kind,
                    _FLOAT,
                    bounded=name == "POSITION",
                )
        indices_accessor = _place(
            document,
            blob,
            buffer_index,
            np.ascontiguousarray(level.indices, dtype="<u4").reshape(-1),
            _ELEMENT_ARRAY_BUFFER,
            "SCALAR",
            _UNSIGNED_INT,
        )

        document["meshes"].append(
            {
                "name": "lod%d" % (index,),
                "primitives": [
                    {
                        "attributes": attributes,
                        "indices": indices_accessor,
                        "mode": _TRIANGLES,
                    }
                ],
            }
        )

    document["buffers"].append({"byteLength": len(embedded)})
    for index in sorted(sidecars):
        name = os.path.basename(sidecar_name(path, index))
        document["buffers"].append({"uri": name, "byteLength": len(sidecars[index])})
        target = os.path.join(os.path.dirname(path) or ".", name)
        with open(target, "wb") as handle:
            handle.write(bytes(sidecars[index]))
        written.append(target)

    raw = json.dumps(document, separators=(",", ":")).encode("utf-8")
    raw += b" " * _pad(len(raw))
    binary = bytes(embedded) + b"\0" * _pad(len(embedded))
    total = 12 + 8 + len(raw) + (8 + len(binary) if binary else 0)
    with open(path, "wb") as handle:
        handle.write(struct.pack("<III", _GLB_MAGIC, 2, total))
        handle.write(struct.pack("<II", len(raw), _JSON_CHUNK))
        handle.write(raw)
        if binary:
            handle.write(struct.pack("<II", len(binary), _BIN_CHUNK))
            handle.write(binary)
    return written
