"""KHR_draco_mesh_compression: decode Draco-compressed primitives via DracoPy.

Draco packs a primitive's whole vertex + index stream into one compressed
``bufferView`` and leaves the primitive's attribute accessors without a
``bufferView`` -- they describe only componentType/normalization/bounds, and the
values live in the Draco blob keyed by a per-attribute *unique id*. This module
turns that blob back into the plain numpy arrays :mod:`meshes` expects, mapping the
extension's ``attributes`` (semantic -> Draco unique id) onto the accessor
semantics the loader already uses and honoring each accessor's normalization.

A primitive attribute the extension's map does not name is not in the stream;
the caller reads it from its own accessor (:func:`compressed_semantics`).

``DracoPy`` is a soft dependency: :data:`HAVE_DRACO` is False when it is absent.
A primitive whose accessors also carry the uncompressed data
(:func:`has_fallback`) is then read from them; one without is skipped, with
one warning per load.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from OpenGLContext.loaders.resolver import Resolver
from OpenGLContext.loaders.gltf.accessors import (
    _coerce_normalized, _colors_to_rgba, view_bytes,
)

if TYPE_CHECKING:
    import pygltflib

log = logging.getLogger(__name__)

DRACO_EXTENSION = 'KHR_draco_mesh_compression'

try:
    import DracoPy
    HAVE_DRACO = True
except ImportError:  # pragma: no cover - absence is exercised via monkeypatch
    DracoPy = None
    HAVE_DRACO = False


def _ext_field(ext: Any, name: str) -> Any:
    return ext.get(name) if isinstance(ext, dict) else getattr(ext, name, None)


def draco_extension(primitive: "pygltflib.Primitive") -> Optional[dict]:
    """Return a primitive's KHR_draco_mesh_compression payload, or None."""
    ext = getattr(primitive, 'extensions', None) or {}
    if not isinstance(ext, dict):
        return None
    return ext.get(DRACO_EXTENSION) or None


def compressed_semantics(primitive: "pygltflib.Primitive") -> frozenset[str]:
    """The attribute semantics the primitive's Draco stream holds."""
    return frozenset(_ext_field(draco_extension(primitive), 'attributes') or ())


def has_fallback(g: "pygltflib.GLTF2", primitive: "pygltflib.Primitive") -> bool:
    """Whether a Draco primitive's index and POSITION accessors hold the
    uncompressed data a loader without a decoder draws instead."""
    accessors = g.accessors or []
    needed = [primitive.attributes.POSITION]
    if primitive.indices is not None:
        needed.append(primitive.indices)
    return all(index is not None and 0 <= index < len(accessors)
               and (accessors[index].bufferView is not None
                    or getattr(accessors[index], 'sparse', None) is not None)
               for index in needed)


# Dedupe the "install DracoPy" warning when there is no resolver to stash the
# flag on (a primitive decoded outside a load, so `resolver is None`).
_warned_missing_no_resolver = False


def warn_missing_once(resolver: Optional[Resolver]) -> None:
    global _warned_missing_no_resolver
    if resolver is not None:
        if getattr(resolver, '_draco_warned', False):
            return
    elif _warned_missing_no_resolver:
        return
    log.warning(
        "glTF: primitive uses KHR_draco_mesh_compression with no uncompressed "
        "fallback and DracoPy is not installed; skipping it (pip install "
        "DracoPy). The rest of the scene loads.")
    if resolver is not None:
        resolver._draco_warned = True
    else:
        _warned_missing_no_resolver = True


def _decode_blob(g: "pygltflib.GLTF2", ext: Any, resolver: Resolver) -> Any:
    """Decode the extension's compressed bufferView into a DracoPy mesh."""
    bv_index = _ext_field(ext, 'bufferView')
    if bv_index is None:
        raise ValueError("KHR_draco_mesh_compression primitive has no bufferView")
    return DracoPy.decode(bytes(view_bytes(g, bv_index, resolver)))


def draco_arrays(g: "pygltflib.GLTF2", primitive: "pygltflib.Primitive",
                 resolver: Resolver) -> dict[str, np.ndarray]:
    """Decoded attribute arrays for a Draco ``primitive``.

    Returns a dict with ``positions`` and ``indices`` (flat uint32) plus whichever
    of ``normals``/``texcoords``/``texcoords1``/``tangents``/``colors``/
    ``skin_joints``/``skin_weights`` the stream carries -- the same keys and dtypes
    :mod:`meshes` builds from accessors, so the shared decode path is unchanged.
    Attributes the extension's map does not name are not read here. Raises ValueError on a malformed blob. Call only after
    :func:`draco_extension` confirms the primitive is Draco-compressed.
    """
    if not HAVE_DRACO:
        raise RuntimeError("decoding a Draco primitive needs DracoPy")
    ext = draco_extension(primitive)
    mesh = _decode_blob(g, ext, resolver)
    attr_map = _ext_field(ext, 'attributes') or {}
    attrs = primitive.attributes

    def decoded(semantic: str) -> Optional[np.ndarray]:
        uid = attr_map.get(semantic)
        if uid is None:
            return None
        attr = mesh.get_attribute_by_unique_id(int(uid))
        if attr is None:
            log.warning("glTF: Draco stream has no attribute id %s for %s",
                        uid, semantic)
            return None
        return np.asarray(attr['data'])

    def accessor(semantic: str) -> "pygltflib.Accessor":
        # A Draco stream may list a semantic in its extension `attributes` map
        # while the primitive omits the matching accessor. The accessor is
        # authoritative for componentType/normalization, so a decoded attribute
        # with no accessor is malformed -- refuse it with a located error rather
        # than dereferencing None.
        idx = getattr(attrs, semantic, None)
        if idx is None:
            raise ValueError(
                "Draco attribute %s has no matching accessor" % semantic)
        return g.accessors[idx]

    faces = getattr(mesh, 'faces', None)
    if faces is None:
        raise ValueError("KHR_draco_mesh_compression stream decoded to a point "
                         "cloud with no faces")
    out = {'indices': np.ascontiguousarray(np.asarray(faces, dtype=np.uint32).ravel())}

    pos = decoded('POSITION')
    if pos is None:
        raise ValueError("KHR_draco_mesh_compression stream has no POSITION attribute")
    out['positions'] = np.ascontiguousarray(pos.astype(np.float32))

    norm = decoded('NORMAL')
    if norm is not None:
        out['normals'] = np.ascontiguousarray(norm.astype(np.float32))
    tan = decoded('TANGENT')
    if tan is not None:
        out['tangents'] = np.ascontiguousarray(tan.astype(np.float32))

    for semantic, key in (('TEXCOORD_0', 'texcoords'), ('TEXCOORD_1', 'texcoords1'),
                          ('WEIGHTS_0', 'skin_weights')):
        raw = decoded(semantic)
        if raw is not None:
            out[key] = _coerce_normalized(accessor(semantic), raw)

    col = decoded('COLOR_0')
    if col is not None:
        out['colors'] = _colors_to_rgba(_coerce_normalized(accessor('COLOR_0'), col))

    joints = decoded('JOINTS_0')
    if joints is not None:
        out['skin_joints'] = np.ascontiguousarray(joints.astype(np.uint32))

    return out
