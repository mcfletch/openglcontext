"""Binding a geometry node's vertex buffers for the shader passes.

Geometry nodes that keep their vertices in ordinary arrays -- as against the
raw-GL layers, which drive their own programs -- hand those arrays to the
functions here, which bind them at the locations
:mod:`OpenGLContext.scenegraph.vertexsemantics` declares. The locations are the
same in every conforming program, so a Vertex Array Object built once serves the
lit pass, the unlit pass and the shadow depth pass, and ``get_or_build_vao``
keeps it on the node.

Two interleaved layouts have names here, both 32 bytes per vertex:

``T2F_N3F_V3F``
    texcoord(2) + normal(3) + position(3); what ``Box`` builds.
``V3F_T2F_N3F``
    position(3) + texcoord(2) + normal(3); what the quadrics build.

A geometry with an array per attribute passes them to ``bind_separate_arrays``
instead.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from OpenGL.GL import (
    GL_FLOAT, GL_FALSE, GL_TRIANGLES, GL_UNSIGNED_SHORT,
    glEnableVertexAttribArray,
    glDisableVertexAttribArray, glVertexAttribPointer,
    glDrawArrays, glDrawElements,
    glGenVertexArrays, glBindVertexArray, glDeleteVertexArrays,
)
from OpenGL.arrays import vbo
from OpenGLContext.arrays import array
from OpenGLContext.scenegraph.vertexsemantics import (
    LOC_TEXCOORD, LOC_NORMAL, LOC_POSITION,
)

if TYPE_CHECKING:
    from OpenGLContext.passes.shaderpass import VRML97ShaderProgram


# Vertex format descriptors
class VertexFormat:
    """Describes vertex data layouts for shader binding."""

    # T2F_N3F_V3F format (used by Box)
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

    # V3F_T2F_N3F format (used by Quadrics: Sphere, Cone, Cylinder)
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


# Legacy constants for backward compatibility
VBO_STRIDE: int = 32


#: Which semantic each ``VertexFormat`` key describes, in binding order.
_INTERLEAVED = (
    ('position', LOC_POSITION),
    ('normal', LOC_NORMAL),
    ('texcoord', LOC_TEXCOORD),
)


def bind_interleaved_vbo(
    vbo_obj: vbo.VBO,
    program: int,
    vertex_format: Dict[str, int]
) -> Dict[str, int]:
    """Bind an interleaved VBO and set up its vertex attributes.

    Args:
        vbo_obj: VBO containing interleaved vertex data
        program: Shader program the draw will use; the locations do not depend
            on it, and it is here so a caller can key a cache by it.
        vertex_format: One of VertexFormat.T2F_N3F_V3F or VertexFormat.V3F_T2F_N3F

    Returns:
        Dict of enabled attribute locations for cleanup
    """
    vbo_obj.bind()

    stride = vertex_format['stride']
    enabled: Dict[str, int] = {}
    for name, location in _INTERLEAVED:
        glEnableVertexAttribArray(location)
        glVertexAttribPointer(
            location,
            vertex_format['%s_size' % (name,)],
            GL_FLOAT, GL_FALSE,
            stride,
            vbo_obj + vertex_format['%s_offset' % (name,)]
        )
        enabled[name] = location

    return enabled


def bind_separate_arrays(
    program: int,
    vertices: Optional[vbo.VBO] = None,
    normals: Optional[vbo.VBO] = None,
    texcoords: Optional[vbo.VBO] = None,
) -> Tuple[Dict[str, int], List[vbo.VBO]]:
    """Bind separate VBOs for each vertex attribute.

    This is used by ArrayGeometry and IndexedFaceSet which store
    vertex data in separate arrays rather than interleaved.

    Args:
        program: Shader program the draw will use; the locations do not depend
            on it, and it is here so a caller can key a cache by it.
        vertices: VBO of vertex positions (vec3)
        normals: VBO of normals (vec3)
        texcoords: VBO of texture coordinates (vec2)

    Returns:
        Tuple of (enabled attribute locations, list of bound VBOs)
    """
    enabled: Dict[str, int] = {}
    bound_vbos: List[vbo.VBO] = []

    for name, buffer, location, components in (
        ('position', vertices, LOC_POSITION, 3),
        ('normal', normals, LOC_NORMAL, 3),
        ('texcoord', texcoords, LOC_TEXCOORD, 2),
    ):
        if buffer is None:
            continue
        buffer.bind()
        bound_vbos.append(buffer)
        glEnableVertexAttribArray(location)
        glVertexAttribPointer(location, components, GL_FLOAT, GL_FALSE, 0, buffer)
        enabled[name] = location

    return enabled, bound_vbos


def unbind_attributes(enabled_attrs: Dict[str, int], bound_vbos: Optional[List[vbo.VBO]] = None) -> None:
    """Disable vertex attributes and unbind VBOs.

    Args:
        enabled_attrs: Dict of attribute names to locations from bind functions
        bound_vbos: Optional list of VBOs to unbind
    """
    for loc in enabled_attrs.values():
        if loc >= 0:
            glDisableVertexAttribArray(loc)

    if bound_vbos:
        for vbo_obj in bound_vbos:
            vbo_obj.unbind()


def _same_refs(a, b) -> bool:
    """Identity comparison of two VBO reference tuples (Nones allowed)."""
    return len(a) == len(b) and all(x is y for x, y in zip(a, b))


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


def render_shader_interleaved(
    mode: Any,
    vbo_obj: vbo.VBO,
    vertex_count: int,
    vertex_format: Dict[str, int],
    draw_mode: int = GL_TRIANGLES,
    index_vbo: Optional[vbo.VBO] = None,
    index_count: Optional[int] = None,
    owner: Any = None,
) -> bool:
    """Render geometry using an interleaved VBO with the shader.

    When ``owner`` is supplied the VAO is cached on it (keyed by shader program +
    VBO identity) and merely re-bound on later frames instead of being
    regenerated and deleted every draw.

    Args:
        mode: Render mode with shader_program attribute
        vbo_obj: VBO containing interleaved vertex data
        vertex_count: Number of vertices to draw (if no indices)
        vertex_format: Vertex format descriptor (VertexFormat.T2F_N3F_V3F, etc.)
        draw_mode: GL draw mode (GL_TRIANGLES, etc.)
        index_vbo: Optional index buffer for indexed drawing
        index_count: Number of indices (required if index_vbo provided)
        owner: node to cache the VAO on (falls back to per-frame VAO if None)

    Returns:
        True if rendering succeeded
    """
    shader_program = getattr(mode, 'shader_program', None)
    if shader_program is None or shader_program.program is None:
        return False
    program = shader_program.program

    def draw():
        if index_vbo is not None and index_count is not None:
            glDrawElements(draw_mode, index_count, GL_UNSIGNED_SHORT, None)
        else:
            glDrawArrays(draw_mode, 0, vertex_count)

    if owner is not None:
        def build():
            bind_interleaved_vbo(vbo_obj, program, vertex_format)
            if index_vbo is not None:
                index_vbo.bind()   # element-array binding is recorded in the VAO
            vbo_obj.unbind()
        vao = get_or_build_vao(owner, program, (vbo_obj, index_vbo), build,
                               layout_key=SHARED_LAYOUT)
        if vao is not None:
            glBindVertexArray(vao)
            try:
                draw()
            finally:
                glBindVertexArray(0)
            return True

    # Transient (uncached) fallback.
    vao = glGenVertexArrays(1)
    glBindVertexArray(vao)
    try:
        enabled = bind_interleaved_vbo(vbo_obj, program, vertex_format)
        try:
            if index_vbo is not None and index_count is not None:
                index_vbo.bind()
                try:
                    glDrawElements(draw_mode, index_count, GL_UNSIGNED_SHORT, index_vbo)
                finally:
                    index_vbo.unbind()
            else:
                glDrawArrays(draw_mode, 0, vertex_count)
            return True
        finally:
            unbind_attributes(enabled)
            vbo_obj.unbind()
    finally:
        glBindVertexArray(0)
        glDeleteVertexArrays(1, [vao])


def render_shader_arrays(
    mode: Any,
    vertices: vbo.VBO,
    normals: Optional[vbo.VBO],
    texcoords: Optional[vbo.VBO],
    vertex_count: int,
    draw_mode: int = GL_TRIANGLES,
    owner: Any = None,
) -> bool:
    """Render geometry using separate VBOs for each attribute.

    When ``owner`` is supplied the VAO is cached on it (keyed by shader program +
    VBO identity) and merely re-bound on later frames.

    Args:
        mode: Render mode with shader_program attribute
        vertices: VBO of vertex positions
        normals: VBO of normals (optional)
        texcoords: VBO of texture coordinates (optional)
        vertex_count: Number of vertices to draw
        draw_mode: GL draw mode (GL_TRIANGLES, etc.)
        owner: node to cache the VAO on (falls back to per-frame VAO if None)

    Returns:
        True if rendering succeeded
    """
    shader_program = getattr(mode, 'shader_program', None)
    if shader_program is None or shader_program.program is None:
        return False
    program = shader_program.program

    if owner is not None:
        def build():
            _enabled, bound = bind_separate_arrays(program, vertices, normals, texcoords)
            for bound_vbo in bound:
                bound_vbo.unbind()
        vao = get_or_build_vao(
            owner, program, (vertices, normals, texcoords), build,
            layout_key=SHARED_LAYOUT)
        if vao is not None:
            glBindVertexArray(vao)
            try:
                glDrawArrays(draw_mode, 0, vertex_count)
            finally:
                glBindVertexArray(0)
            return True

    # Transient (uncached) fallback.
    vao = glGenVertexArrays(1)
    glBindVertexArray(vao)
    try:
        enabled, bound_vbos = bind_separate_arrays(
            program, vertices, normals, texcoords
        )
        try:
            glDrawArrays(draw_mode, 0, vertex_count)
            return True
        finally:
            unbind_attributes(enabled, bound_vbos)
    finally:
        glBindVertexArray(0)
        glDeleteVertexArrays(1, [vao])


# Backward compatibility: old function names
def bind_vbo_for_shader(vbo_obj: vbo.VBO, shader_program: Any) -> Dict[str, int]:
    """Legacy function for T2F_N3F_V3F format (Box).

    Deprecated: Use bind_interleaved_vbo with explicit vertex format instead.
    """
    return bind_interleaved_vbo(vbo_obj, shader_program.program, VertexFormat.T2F_N3F_V3F)


def unbind_vbo_for_shader(vbo_obj: vbo.VBO, enabled_attrs: Dict[str, int]) -> None:
    """Legacy function to unbind VBO.

    Deprecated: Use unbind_attributes instead.
    """
    unbind_attributes(enabled_attrs)
    vbo_obj.unbind()
