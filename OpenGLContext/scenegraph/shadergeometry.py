"""Shader-compatible geometry rendering support

This module provides utilities for rendering geometry with the VRML97 shader pass.
Geometry nodes can use these utilities to support shader-based rendering alongside
legacy fixed-function rendering.

The shader expects vertex attributes at specific layout locations:
- layout(location = 0): aTexCoord (vec2)
- layout(location = 1): aNormal (vec3)
- layout(location = 2): aPosition (vec3)

Two common vertex formats are supported:
1. T2F_N3F_V3F (Box): texcoord(2) + normal(3) + position(3) = 32 bytes
2. V3F_T2F_N3F (Quadrics): position(3) + texcoord(2) + normal(3) = 32 bytes

For separate arrays (ArrayGeometry), each array is bound individually.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from OpenGL.GL import (
    GL_FLOAT, GL_FALSE, GL_TRIANGLES, GL_UNSIGNED_SHORT,
    glGetAttribLocation, glEnableVertexAttribArray,
    glDisableVertexAttribArray, glVertexAttribPointer,
    glDrawArrays, glDrawElements,
    glGenVertexArrays, glBindVertexArray, glDeleteVertexArrays,
)
from OpenGL.arrays import vbo
from OpenGLContext.arrays import array

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


def bind_interleaved_vbo(
    vbo_obj: vbo.VBO,
    program: int,
    vertex_format: Dict[str, int]
) -> Dict[str, int]:
    """Bind an interleaved VBO and set up vertex attributes.

    Args:
        vbo_obj: VBO containing interleaved vertex data
        program: Shader program ID
        vertex_format: One of VertexFormat.T2F_N3F_V3F or VertexFormat.V3F_T2F_N3F

    Returns:
        Dict of enabled attribute locations for cleanup
    """
    vbo_obj.bind()

    stride = vertex_format['stride']
    enabled: Dict[str, int] = {}

    # Position attribute
    pos_loc = glGetAttribLocation(program, 'aPosition')
    if pos_loc >= 0:
        glEnableVertexAttribArray(pos_loc)
        glVertexAttribPointer(
            pos_loc,
            vertex_format['position_size'],
            GL_FLOAT, GL_FALSE,
            stride,
            vbo_obj + vertex_format['position_offset']
        )
        enabled['aPosition'] = pos_loc

    # Normal attribute
    normal_loc = glGetAttribLocation(program, 'aNormal')
    if normal_loc >= 0:
        glEnableVertexAttribArray(normal_loc)
        glVertexAttribPointer(
            normal_loc,
            vertex_format['normal_size'],
            GL_FLOAT, GL_FALSE,
            stride,
            vbo_obj + vertex_format['normal_offset']
        )
        enabled['aNormal'] = normal_loc

    # Texture coordinate attribute
    tex_loc = glGetAttribLocation(program, 'aTexCoord')
    if tex_loc >= 0:
        glEnableVertexAttribArray(tex_loc)
        glVertexAttribPointer(
            tex_loc,
            vertex_format['texcoord_size'],
            GL_FLOAT, GL_FALSE,
            stride,
            vbo_obj + vertex_format['texcoord_offset']
        )
        enabled['aTexCoord'] = tex_loc

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
        program: Shader program ID
        vertices: VBO of vertex positions (vec3)
        normals: VBO of normals (vec3)
        texcoords: VBO of texture coordinates (vec2)

    Returns:
        Tuple of (enabled attribute locations, list of bound VBOs)
    """
    enabled: Dict[str, int] = {}
    bound_vbos: List[vbo.VBO] = []

    # Position attribute
    if vertices is not None:
        pos_loc = glGetAttribLocation(program, 'aPosition')
        if pos_loc >= 0:
            vertices.bind()
            bound_vbos.append(vertices)
            glEnableVertexAttribArray(pos_loc)
            glVertexAttribPointer(pos_loc, 3, GL_FLOAT, GL_FALSE, 0, vertices)
            enabled['aPosition'] = pos_loc

    # Normal attribute
    if normals is not None:
        normal_loc = glGetAttribLocation(program, 'aNormal')
        if normal_loc >= 0:
            normals.bind()
            bound_vbos.append(normals)
            glEnableVertexAttribArray(normal_loc)
            glVertexAttribPointer(normal_loc, 3, GL_FLOAT, GL_FALSE, 0, normals)
            enabled['aNormal'] = normal_loc

    # Texture coordinate attribute
    if texcoords is not None:
        tex_loc = glGetAttribLocation(program, 'aTexCoord')
        if tex_loc >= 0:
            texcoords.bind()
            bound_vbos.append(texcoords)
            glEnableVertexAttribArray(tex_loc)
            glVertexAttribPointer(tex_loc, 2, GL_FLOAT, GL_FALSE, 0, texcoords)
            enabled['aTexCoord'] = tex_loc

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


def get_or_build_vao(owner, program, vbo_refs, build):
    """Return a cached VAO for (owner, program), building it once via ``build``.

    A VAO records attribute layout once, so it should be created once per
    (node, shader-program) pair and merely re-bound on every later frame -- the
    same discipline ``passes/instancing`` and ``pbrmesh`` already use. The VAO is
    keyed by shader program (attribute locations are program-specific) and by the
    identity of the VBOs it wraps, so a data-driven VBO replacement rebuilds it
    rather than binding stale buffers.

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
    key = int(program)
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
        vao = get_or_build_vao(owner, program, (vbo_obj, index_vbo), build)
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
            owner, program, (vertices, normals, texcoords), build)
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
