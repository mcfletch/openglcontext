"""The vertex array object a geometry's buffers are described into.

A Vertex Array Object records which buffer each attribute reads from, and it is
the only place OpenGL keeps that description: a ``glVertexAttribPointer`` with
none bound is an invalid operation. Building one per node per frame is wasteful,
so :func:`get_or_build_vao` builds it once and keeps it on the node.

What goes *into* one is described by
:mod:`OpenGLContext.scenegraph.geometryarrays`, which is what a geometry node
should reach for; this module is the cache underneath it, and the two
interleaved layouts the engine's own geometry is built in:

``T2F_N3F_V3F``
    texcoord(2) + normal(3) + position(3); what ``Box`` and ``Teapot`` build.
``V3F_T2F_N3F``
    position(3) + texcoord(2) + normal(3); what the quadrics build.
"""
from __future__ import annotations

from typing import Dict

from OpenGL.GL import (
    glGenVertexArrays, glBindVertexArray, glDeleteVertexArrays,
)

__all__ = ['VertexFormat', 'VBO_STRIDE', 'SHARED_LAYOUT', 'get_or_build_vao']


class VertexFormat:
    """The interleaved layouts the engine's own geometry is built in.

    Each is the argument ``geometryarrays.GeometryArrays.interleaved`` reads:
    the stride, and each attribute's byte offset and component count.
    """

    # Layout: texcoord(2f) + normal(3f) + position(3f) = 8 floats = 32 bytes
    T2F_N3F_V3F: Dict[str, int] = {
        'stride': 32,
        'texcoord_offset': 0,
        'texcoord_size': 2,
        'normal_offset': 8,
        'normal_size': 3,
        'position_offset': 20,
        'position_size': 3,
    }

    # Layout: position(3f) + texcoord(2f) + normal(3f) = 8 floats = 32 bytes
    V3F_T2F_N3F: Dict[str, int] = {
        'stride': 32,
        'position_offset': 0,
        'position_size': 3,
        'texcoord_offset': 12,
        'texcoord_size': 2,
        'normal_offset': 20,
        'normal_size': 3,
    }


#: Bytes per vertex in both of the layouts above.
VBO_STRIDE: int = 32


def _same_refs(a, b) -> bool:
    """Identity comparison of two VBO reference tuples (Nones allowed)."""
    return len(a) == len(b) and all(x is y for x, y in zip(a, b, strict=False))


#: Cache key for a layout that reads the same in every program, because it uses
#: the locations :mod:`OpenGLContext.scenegraph.vertexsemantics` declares.
SHARED_LAYOUT = 0


def get_or_build_vao(owner, program, vbo_refs, build, layout_key=None):
    """Return a VAO cached on ``owner``, building it once via ``build``.

    A VAO records attribute layout once, so it should be created once and merely
    re-bound on every later frame -- the same discipline ``passes/instancing``
    and ``pbrmesh`` already use. It is keyed by ``layout_key`` and by the
    identity of the VBOs it wraps, so a data-driven VBO replacement rebuilds it
    rather than binding stale buffers.

    ``layout_key`` defaults to ``program``, which is what a ``build`` that looks
    its attribute names up in the program needs: those locations are that
    program's. A ``build`` that uses the engine's declared locations passes
    :data:`SHARED_LAYOUT` instead, and its one VAO then serves the lit pass, the
    unlit pass and the depth pass alike.

    ``build`` runs with the new VAO bound and must set up (and leave enabled) the
    vertex attributes; it must NOT draw or disable them. Returns the VAO name.
    Falls back to a transient VAO (returns None) if ``owner`` cannot hold a cache.
    """
    cache = getattr(owner, '_shader_vao_cache', None)
    if cache is None:
        try:
            cache = {}
            owner._shader_vao_cache = cache
        except (AttributeError, TypeError):
            return None
    key = int(program if layout_key is None else layout_key)
    entry = cache.get(key)
    if entry is not None:
        cached_refs, vao = entry
        if _same_refs(cached_refs, vbo_refs):
            return vao
        # VBOs were replaced (data changed) -> the recorded pointers are stale.
        glDeleteVertexArrays(1, [vao])
    vao = glGenVertexArrays(1)
    glBindVertexArray(vao)
    try:
        build()
    finally:
        glBindVertexArray(0)
    cache[key] = (vbo_refs, vao)
    return vao


