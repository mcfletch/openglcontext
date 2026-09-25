"""The vertex array object a geometry's buffers are described into.

A Vertex Array Object records which buffer each attribute reads from, and it is
the only place OpenGL keeps that description: a ``glVertexAttribPointer`` with
none bound is an invalid operation. Building one per node per frame is wasteful,
so :func:`get_or_build_vao` builds it once and keeps it on the node, for each
context it is drawn in. A node that is collected has its objects deleted the
next time any is built or bound in their context, and a context that is torn
down (:func:`OpenGLContext.contextresources.context_lost`) has every node's
objects for it deleted and forgotten.

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

import threading
import weakref
from collections.abc import Callable, Sequence
from typing import Any, Dict, List, Optional, Tuple

from OpenGL.GL import (
    glGenVertexArrays, glBindVertexArray, glDeleteVertexArrays,
)

from OpenGLContext import contextresources

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


def _same_refs(a: Sequence[Any], b: Sequence[Any]) -> bool:
    """Identity comparison of two VBO reference tuples (Nones allowed)."""
    return len(a) == len(b) and all(x is y for x, y in zip(a, b, strict=False))


#: Cache key for a layout that reads the same in every program, because it uses
#: the locations :mod:`OpenGLContext.scenegraph.vertexsemantics` declares.
SHARED_LAYOUT = 0

#: One layout's entry: the VBOs the VAO records, and the VAO's name.
_Entry = Tuple[Sequence[Any], int]


class _VertexArrays:
    """The vertex array objects one node holds: by context, then by layout."""

    def __init__(self) -> None:
        self.by_context: Dict[Any, Dict[int, _Entry]] = {}


#: Every node's vertex arrays, so a lost context's can be found and deleted.
_HOLDERS: 'weakref.WeakSet[_VertexArrays]' = weakref.WeakSet()
#: VAO names whose node was collected, by the context that issued them, waiting
#: for that context to be current. Appended from a finalizer, which may run on
#: any thread, so guarded.
_ORPHANS: Dict[Any, List[int]] = {}
_ORPHANS_LOCK = threading.Lock()


def _orphaned(holder: _VertexArrays) -> None:
    """Queue a collected node's names for deletion in their own contexts."""
    with _ORPHANS_LOCK:
        for context, entries in holder.by_context.items():
            _ORPHANS.setdefault(context, []).extend(
                vao for _refs, vao in entries.values())
    holder.by_context.clear()


def _delete(names: Sequence[int]) -> None:
    for vao in names:
        try:
            glDeleteVertexArrays(1, [vao])
        except Exception:                       # pragma: no cover - a dying driver
            pass


def _collect_orphans(context: Any) -> None:
    """Delete the names collected nodes left in ``context``, which is current."""
    if not _ORPHANS.get(context):
        return
    with _ORPHANS_LOCK:
        names = _ORPHANS.pop(context, [])
    _delete(names)


@contextresources.on_context_lost
def _context_lost() -> None:
    """Delete and forget every node's vertex arrays in the context going away."""
    context = contextresources.context_key()
    _collect_orphans(context)
    for holder in list(_HOLDERS):
        entries = holder.by_context.pop(context, None)
        if entries:
            _delete([vao for _refs, vao in entries.values()])


def _holder_of(owner: Any) -> Optional[_VertexArrays]:
    """The vertex arrays ``owner`` holds, made on first use; None where it cannot hold any."""
    holder: Optional[_VertexArrays] = getattr(owner, '_shader_vao_cache', None)
    if holder is not None:
        return holder
    holder = _VertexArrays()
    try:
        owner._shader_vao_cache = holder
        weakref.finalize(owner, _orphaned, holder)
    except (AttributeError, TypeError):
        return None
    _HOLDERS.add(holder)
    return holder


def get_or_build_vao(owner: Any, program: Any, vbo_refs: Sequence[Any],
                     build: Callable[[], None],
                     layout_key: Any = None) -> Optional[int]:
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

    The VAO is kept for the context current now, and deleted in that context
    once ``owner`` is collected or the context is torn down.
    """
    holder = _holder_of(owner)
    if holder is None:
        return None
    context = contextresources.context_key()
    _collect_orphans(context)
    cache = holder.by_context.setdefault(context, {})
    key = int(program if layout_key is None else layout_key)
    entry = cache.get(key)
    if entry is not None:
        cached_refs, vao = entry
        if _same_refs(cached_refs, vbo_refs):
            return vao
        # VBOs were replaced (data changed) -> the recorded pointers are stale.
        glDeleteVertexArrays(1, [vao])
    # One name asked for is one name answered; the entry point's result follows
    # the count it was given, so the caller is what knows the shape.
    vao = int(glGenVertexArrays(1))
    glBindVertexArray(vao)
    try:
        build()
    finally:
        glBindVertexArray(0)
    cache[key] = (vbo_refs, vao)
    return vao


