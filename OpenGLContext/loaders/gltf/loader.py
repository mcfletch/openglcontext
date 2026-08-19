"""Public entry points: load a glTF/GLB from bytes, a file path, or a URL.

The two functions callers actually use. :func:`load_gltf` parses a document (bytes,
a ``.glb``/``.gltf`` path, or with ``base_url`` a document with relative refs) and
hands it to the scene builder; :func:`load_gltf_url` fetches a document over the
security-hardened :mod:`resolver` first, then loads it. Both return a
:class:`~OpenGLContext.loaders.gltf.scene.GLTFScene`.

``pygltflib`` is a core dependency; :func:`_require_pygltflib` still imports it
lazily, so an install missing it fails at the point of loading with a message
naming what to install rather than at import time.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional, Union

from OpenGLContext.loaders.resolver import (
    _check_size, Resolver, _fetch_url, DEFAULT_MAX_RESOURCE_BYTES,
)
from OpenGLContext.loaders.gltf import fastdecode
from OpenGLContext.loaders.gltf.scene import _build_scene, GLTFScene

if TYPE_CHECKING:
    import pygltflib

log = logging.getLogger(__name__)


def _decode_document(data: bytes) -> "pygltflib.GLTF2":
    """Parse ``.glb``/``.gltf`` bytes into a document, fast.

    :mod:`fastdecode` builds the pygltflib object graph directly, which for a
    rigged model is the difference between milliseconds and seconds. Should it
    meet a document shape it does not expect, the parse falls back to pygltflib's
    own decoder so loading never regresses to a failure -- logged, because the
    slow path is worth knowing about.
    """
    try:
        if data[:4] == b'glTF':
            return fastdecode.load_glb(data)
        return fastdecode.decode_gltf(data)
    except Exception:                       # pragma: no cover - safety net
        GLTF2 = _require_pygltflib()
        if data[:4] == b'glTF':
            log.warning('fast glTF decode failed; using pygltflib', exc_info=True)
            return GLTF2.load_from_bytes(data)
        log.warning('fast glTF decode failed; using pygltflib', exc_info=True)
        return GLTF2.from_json(data.decode('utf-8'))


def _require_pygltflib() -> "type[pygltflib.GLTF2]":
    try:
        from pygltflib import GLTF2
        return GLTF2
    except ImportError as err:  # pragma: no cover - dependency guard
        raise ImportError(
            "glTF loading requires 'pygltflib' (pip install pygltflib)"
        ) from err


def _source_bytes(source: Union[bytes, bytearray, str],
                  max_resource_bytes: Optional[int],
                  base_dir: Optional[str]) -> "tuple[bytes, Optional[str]]":
    """The bytes of a glTF/GLB source, and where its relative references live.

    Bytes come with a ``base_dir`` the caller supplies; a path reads itself and
    resolves references against its own directory. Both cap the primary document,
    not just its external refs, so a huge in-memory ``.glb`` cannot slip the size
    limit the resolver puts on everything else.
    """
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        _check_size(len(data), max_resource_bytes, 'glTF document')
        return data, base_dir
    if max_resource_bytes is not None and os.path.exists(source):
        _check_size(os.path.getsize(source), max_resource_bytes, source)
    with open(source, 'rb') as handle:
        data = handle.read()
    return data, os.path.dirname(os.path.abspath(source))


class SharedDocument:
    """A parsed glTF, ready to build into a scene many times over.

    One asset drawn as many instances -- a cast of one character, a forest of one
    tree -- parses the file and decodes its buffers once. Hand this to
    :func:`load_gltf` as ``document`` for each instance: the JSON parse is already
    done, and the immutable vertex and animation-keyframe arrays are decoded on
    the first build and shared, by reference, with every later one. Each build is
    still its own scenegraph with its own materials and its own deformable-mesh
    state, so the instances animate and recolour independently; what they hold in
    common is only what none of them changes.
    """

    def __init__(self, gltf: "pygltflib.GLTF2", base_url: Optional[str] = None,
                 base_dir: Optional[str] = None,
                 max_resource_bytes: Optional[int] = DEFAULT_MAX_RESOURCE_BYTES) -> None:
        self.gltf = gltf
        self.base_url = base_url
        self.base_dir = base_dir
        self.max_resource_bytes = max_resource_bytes
        #: (kind, accessor index) -> decoded array, shared across every build.
        self.reads: dict = {}

    def _resolver(self) -> Resolver:
        resolver = Resolver(base_url=self.base_url, base_dir=self.base_dir,
                            max_resource_bytes=self.max_resource_bytes)
        resolver._reads = self.reads       # type: ignore[attr-defined]
        return resolver


def parse_gltf(source: Union[bytes, bytearray, str], base_url: Optional[str] = None,
               max_resource_bytes: Optional[int] = DEFAULT_MAX_RESOURCE_BYTES,
               base_dir: Optional[str] = None) -> SharedDocument:
    """Parse a glTF/GLB into a reusable :class:`SharedDocument`, building no scene.

    For a caller that will draw one asset as many instances: parse here once, then
    call :func:`load_gltf` with ``document=`` for each instance.
    """
    data, base_dir = _source_bytes(source, max_resource_bytes, base_dir)
    return SharedDocument(_decode_document(data), base_url=base_url,
                          base_dir=base_dir, max_resource_bytes=max_resource_bytes)


def load_gltf(source: "Union[bytes, bytearray, str, None]" = None,
              base_url: Optional[str] = None,
              max_resource_bytes: Optional[int] = DEFAULT_MAX_RESOURCE_BYTES,
              pointer_time: Optional[float] = None,
              base_dir: Optional[str] = None,
              document: Optional[SharedDocument] = None) -> GLTFScene:
    """Load a glTF/GLB from bytes, a file path, or (with base_url) relative refs.

    ``base_dir`` says where a document handed over as *bytes* came from, so its
    relative references -- an external image, an external buffer -- resolve
    against that directory. A path source works this out for itself; a caller
    that has already read the bytes has to say. This is how a tile whose texture
    is shared with the rest of its tileset finds it: the image is named once
    beside the tileset rather than copied into every tile.

    ``document`` is a :class:`SharedDocument` from :func:`parse_gltf` to build
    from instead of ``source``, so one asset drawn many times parses and decodes
    its buffers once; each build is still an independent scenegraph.

    ``pointer_time`` bakes KHR_animation_pointer channels at that animation time
    (seconds) into the static scene (None => the bind/initial state)."""
    if document is not None:
        return _build_scene(document.gltf, document._resolver(),
                            pointer_time=pointer_time)
    if source is None:
        raise TypeError('load_gltf needs a source or a document to build from')
    data, base_dir = _source_bytes(source, max_resource_bytes, base_dir)
    g = _decode_document(data)
    resolver = Resolver(base_url=base_url, base_dir=base_dir,
                         max_resource_bytes=max_resource_bytes)
    return _build_scene(g, resolver, pointer_time=pointer_time)


def load_gltf_url(url: str, cache_dir: Optional[str] = None,
                  max_resource_bytes: Optional[int] = DEFAULT_MAX_RESOURCE_BYTES) -> GLTFScene:
    """Fetch a glTF/GLB from a URL (caching bytes) and load it.

    External buffers/images referenced by a ``.gltf`` are resolved relative to the
    URL and confined to its origin. ``.glb`` files are self-contained.
    """
    data = _fetch_url(url, cache_dir, max_resource_bytes)
    if data[:4] == b'glTF':
        return load_gltf(data, max_resource_bytes=max_resource_bytes)  # GLB
    g = _decode_document(data)
    return _build_scene(g, Resolver(base_url=url,
                                     max_resource_bytes=max_resource_bytes))
