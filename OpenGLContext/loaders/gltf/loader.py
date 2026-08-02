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

import os
from typing import TYPE_CHECKING, Optional, Union

from OpenGLContext.loaders.resolver import (
    _check_size, Resolver, _fetch_url, DEFAULT_MAX_RESOURCE_BYTES,
)
from OpenGLContext.loaders.gltf.scene import _build_scene, GLTFScene

if TYPE_CHECKING:
    import pygltflib


def _require_pygltflib() -> "type[pygltflib.GLTF2]":
    try:
        from pygltflib import GLTF2
        return GLTF2
    except ImportError as err:  # pragma: no cover - dependency guard
        raise ImportError(
            "glTF loading requires 'pygltflib' (pip install pygltflib)"
        ) from err


def load_gltf(source: Union[bytes, bytearray, str], base_url: Optional[str] = None,
              max_resource_bytes: Optional[int] = DEFAULT_MAX_RESOURCE_BYTES,
              pointer_time: Optional[float] = None) -> GLTFScene:
    """Load a glTF/GLB from bytes, a file path, or (with base_url) relative refs.

    ``pointer_time`` bakes KHR_animation_pointer channels at that animation time
    (seconds) into the static scene (None => the bind/initial state)."""
    GLTF2 = _require_pygltflib()
    base_dir = None
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        # Cap the primary document too: max_resource_bytes only
        # bounded *external* refs, so a huge in-memory .glb/.gltf (the documented
        # upload path) -- including its inline data: buffers -- was parsed
        # unbounded.
        _check_size(len(data), max_resource_bytes, 'glTF document')
        if data[:4] == b'glTF':
            g = GLTF2.load_from_bytes(data)
        else:
            g = GLTF2.from_json(data.decode('utf-8'))
    else:
        if max_resource_bytes is not None and os.path.exists(source):
            _check_size(os.path.getsize(source), max_resource_bytes, source)
        g = GLTF2.load(source)
        base_dir = os.path.dirname(os.path.abspath(source))
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
    GLTF2 = _require_pygltflib()
    g = GLTF2.from_json(data.decode('utf-8'))
    return _build_scene(g, Resolver(base_url=url,
                                     max_resource_bytes=max_resource_bytes))
