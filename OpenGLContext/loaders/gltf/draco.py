"""KHR_draco_mesh_compression: decode Draco-compressed primitives via DracoPy.

Draco packs a primitive's whole vertex + index stream into one compressed
``bufferView`` and leaves the primitive's attribute accessors without a
``bufferView`` -- they describe only componentType/normalization/bounds, and the
values live in the Draco blob keyed by a per-attribute *unique id*. This module
turns that blob back into the plain numpy arrays :mod:`meshes` expects, mapping the
extension's ``attributes`` (semantic -> Draco unique id) onto the accessor
semantics the loader already uses and honoring each accessor's normalization.

``DracoPy`` is a soft dependency: :data:`HAVE_DRACO` is False when it is absent, and
:func:`draco_arrays` returns None so the caller skips the primitive (warning once
per load) instead of crashing the whole scene.
"""
from __future__ import annotations

import logging

import numpy as np

from OpenGLContext.loaders.gltf.accessors import (
    _buffer_bytes, _coerce_normalized, _colors_to_rgba,
)

log = logging.getLogger(__name__)

DRACO_EXTENSION = 'KHR_draco_mesh_compression'

try:
    import DracoPy
    HAVE_DRACO = True
except ImportError:  # pragma: no cover - absence is exercised via monkeypatch
    DracoPy = None
    HAVE_DRACO = False


def _ext_field(ext, name):
    return ext.get(name) if isinstance(ext, dict) else getattr(ext, name, None)


def draco_extension(primitive):
    """Return a primitive's KHR_draco_mesh_compression payload, or None."""
    ext = getattr(primitive, 'extensions', None) or {}
    if not isinstance(ext, dict):
        return None
    return ext.get(DRACO_EXTENSION) or None


# Dedupe the "install DracoPy" warning when there is no resolver to stash the
# flag on (a primitive decoded outside a load, so `resolver is None`).
_warned_missing_no_resolver = False


def _warn_missing_once(resolver):
    global _warned_missing_no_resolver
    if resolver is not None:
        if getattr(resolver, '_draco_warned', False):
            return
    elif _warned_missing_no_resolver:
        return
    log.warning(
        "glTF: primitive uses KHR_draco_mesh_compression but DracoPy is not "
        "installed; skipping it (pip install DracoPy). The rest of the scene loads.")
    if resolver is not None:
        resolver._draco_warned = True
    else:
        _warned_missing_no_resolver = True


def _decode_blob(g, ext, resolver):
    """Decode the extension's compressed bufferView into a DracoPy mesh."""
    bv_index = _ext_field(ext, 'bufferView')
    if bv_index is None:
        raise ValueError("KHR_draco_mesh_compression primitive has no bufferView")
    bv = g.bufferViews[bv_index]
    data = _buffer_bytes(g, bv.buffer, resolver)
    start = bv.byteOffset or 0
    end = start + (bv.byteLength or 0)
    if bv.byteLength is None or end > len(data):
        raise ValueError(
            "glTF Draco bufferView %d reads %d bytes at offset %d but its buffer "
            "holds only %d" % (bv_index, bv.byteLength or 0, start, len(data)))
    return DracoPy.decode(bytes(data[start:end]))


def draco_arrays(g, primitive, resolver):
    """Decoded attribute arrays for a Draco ``primitive``, or None to skip it.

    Returns a dict with ``positions`` and ``indices`` (flat uint32) plus whichever
    of ``normals``/``texcoords``/``texcoords1``/``tangents``/``colors``/
    ``skin_joints``/``skin_weights`` the stream carries -- the same keys and dtypes
    :mod:`meshes` builds from accessors, so the shared decode path is unchanged.
    None means DracoPy is unavailable (a warning was emitted); the caller drops the
    primitive. Raises ValueError on a malformed blob. Call only after
    :func:`draco_extension` confirms the primitive is Draco-compressed.
    """
    if not HAVE_DRACO:
        _warn_missing_once(resolver)
        return None
    ext = draco_extension(primitive)
    mesh = _decode_blob(g, ext, resolver)
    attr_map = _ext_field(ext, 'attributes') or {}
    attrs = primitive.attributes

    def decoded(semantic):
        uid = attr_map.get(semantic)
        if uid is None:
            return None
        attr = mesh.get_attribute_by_unique_id(int(uid))
        if attr is None:
            log.warning("glTF: Draco stream has no attribute id %s for %s",
                        uid, semantic)
            return None
        return np.asarray(attr['data'])

    def accessor(semantic):
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
