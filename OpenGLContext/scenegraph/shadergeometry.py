"""Shader-compatible geometry rendering support

This module provides a mixin class and utilities for rendering geometry
with the VRML97 shader pass. Geometry nodes can inherit from ShaderGeometryMixin
to gain shader-compatible rendering capabilities.

The shader uses an interleaved vertex format matching T2F_N3F_V3F:
- Texture coords: 2 floats (offset 0)
- Normal: 3 floats (offset 8 bytes)
- Position: 3 floats (offset 20 bytes)
- Total stride: 32 bytes
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from OpenGL.GL import (
    GL_FLOAT, GL_FALSE, GL_TRIANGLES,
    glGetAttribLocation, glEnableVertexAttribArray,
    glDisableVertexAttribArray, glVertexAttribPointer,
    glDrawArrays,
)
from OpenGL.arrays import vbo
from OpenGLContext.arrays import array

if TYPE_CHECKING:
    from OpenGLContext.passes.shaderpass import VRML97ShaderProgram

# Vertex attribute locations matching shader layout
ATTR_TEXCOORD: int = 0
ATTR_NORMAL: int = 1
ATTR_POSITION: int = 2

# Stride for T2F_N3F_V3F format
VBO_STRIDE: int = 32  # 8 floats * 4 bytes


def bind_vbo_for_shader(
    vbo_obj: vbo.VBO,
    shader_program: VRML97ShaderProgram
) -> Dict[str, int]:
    """Bind VBO and set up vertex attributes for shader rendering.

    Args:
        vbo_obj: VBO containing interleaved T2F_N3F_V3F vertex data
        shader_program: VRML97ShaderProgram instance

    Returns:
        Dict mapping attribute names to their locations (for cleanup)
    """
    vbo_obj.bind()

    program = shader_program.program
    enabled: Dict[str, int] = {}

    # Texture coords at offset 0
    tex_loc = glGetAttribLocation(program, 'aTexCoord')
    if tex_loc >= 0:
        glEnableVertexAttribArray(tex_loc)
        glVertexAttribPointer(tex_loc, 2, GL_FLOAT, GL_FALSE, VBO_STRIDE, vbo_obj)
        enabled['aTexCoord'] = tex_loc

    # Normals at offset 8 (2 floats * 4 bytes)
    normal_loc = glGetAttribLocation(program, 'aNormal')
    if normal_loc >= 0:
        glEnableVertexAttribArray(normal_loc)
        glVertexAttribPointer(normal_loc, 3, GL_FLOAT, GL_FALSE, VBO_STRIDE, vbo_obj + 8)
        enabled['aNormal'] = normal_loc

    # Positions at offset 20 (5 floats * 4 bytes)
    pos_loc = glGetAttribLocation(program, 'aPosition')
    if pos_loc >= 0:
        glEnableVertexAttribArray(pos_loc)
        glVertexAttribPointer(pos_loc, 3, GL_FLOAT, GL_FALSE, VBO_STRIDE, vbo_obj + 20)
        enabled['aPosition'] = pos_loc

    return enabled


def unbind_vbo_for_shader(vbo_obj: vbo.VBO, enabled_attrs: Dict[str, int]) -> None:
    """Unbind VBO and disable vertex attributes.

    Args:
        vbo_obj: VBO to unbind
        enabled_attrs: Dict of attribute names to locations from bind_vbo_for_shader
    """
    for loc in enabled_attrs.values():
        glDisableVertexAttribArray(loc)
    vbo_obj.unbind()


class ShaderGeometryMixin:
    """Mixin providing shader-compatible geometry rendering.

    Geometry nodes can inherit from this mixin to support both legacy
    and shader-based rendering paths. The mixin checks if shader mode
    is active and delegates to the appropriate rendering method.

    To use this mixin, geometry nodes should:
    1. Inherit from ShaderGeometryMixin
    2. Implement get_shader_vbo(mode) to return/create a VBO
    3. Implement get_vertex_count() to return the number of vertices
    4. Optionally override get_draw_mode() for non-triangle geometry
    """

    def render_shader(self, mode: Any) -> bool:
        """Render geometry using the shader pipeline.

        Args:
            mode: Render mode with shader_program attribute

        Returns:
            True if rendering succeeded
        """
        shader_program: Optional[VRML97ShaderProgram] = getattr(mode, 'shader_program', None)
        if shader_program is None:
            return False

        vbo_obj = self.get_shader_vbo(mode)
        if vbo_obj is None:
            return False

        enabled = bind_vbo_for_shader(vbo_obj, shader_program)
        try:
            glDrawArrays(self.get_draw_mode(), 0, self.get_vertex_count())
        finally:
            unbind_vbo_for_shader(vbo_obj, enabled)

        return True

    def get_shader_vbo(self, mode: Any) -> Optional[vbo.VBO]:
        """Get or create a VBO for shader rendering.

        Subclasses should implement this to return a VBO containing
        interleaved T2F_N3F_V3F vertex data.

        Args:
            mode: Render mode for caching

        Returns:
            VBO object, or None if not available
        """
        raise NotImplementedError("Subclasses must implement get_shader_vbo")

    def get_vertex_count(self) -> int:
        """Get the number of vertices to draw.

        Subclasses must implement this.

        Returns:
            Number of vertices
        """
        raise NotImplementedError("Subclasses must implement get_vertex_count")

    def get_draw_mode(self) -> int:
        """Get the OpenGL draw mode.

        Default is GL_TRIANGLES. Override for other geometry types.

        Returns:
            GL constant (e.g., GL_TRIANGLES, GL_TRIANGLE_STRIP)
        """
        return GL_TRIANGLES


class ShaderBox(ShaderGeometryMixin):
    """Shader-compatible Box geometry wrapper.

    This class wraps a Box node and provides shader-compatible rendering.
    """

    def __init__(self, box_node: Any) -> None:
        """Initialize with a Box node.

        Args:
            box_node: VRML97 Box node
        """
        self.box_node = box_node

    def get_shader_vbo(self, mode: Any) -> Optional[vbo.VBO]:
        """Get or create VBO for the box."""
        from OpenGLContext.scenegraph import box as box_module

        vbo_obj = mode.cache.getData(self.box_node, 'shader_vbo')
        if vbo_obj is None:
            vertices = array(list(box_module.yieldVertices(self.box_node.size)), 'f')
            vbo_obj = vbo.VBO(vertices)
            mode.cache.holder(self.box_node, vbo_obj, 'shader_vbo')
        return vbo_obj

    def get_vertex_count(self) -> int:
        """Box always has 36 vertices (6 faces * 2 triangles * 3 vertices)."""
        return 36


def create_shader_geometry(geometry_node: Any, mode: Any) -> Optional[ShaderGeometryMixin]:
    """Factory function to create shader-compatible geometry wrapper.

    Args:
        geometry_node: VRML97 geometry node (Box, Sphere, etc.)
        mode: Render mode for determining capabilities

    Returns:
        ShaderGeometryMixin subclass instance, or None if not supported
    """
    node_type = type(geometry_node).__name__

    if node_type == 'Box':
        return ShaderBox(geometry_node)

    # Add support for other geometry types as needed
    # For now, return None for unsupported types
    return None
