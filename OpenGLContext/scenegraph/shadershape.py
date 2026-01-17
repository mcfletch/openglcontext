"""Shader-aware Shape node implementation

This module provides a shader-aware Shape node that can render using either
the legacy fixed-function pipeline or the VRML97 shader pipeline.

The ShaderShape class is a drop-in replacement for Shape that checks the
render mode and delegates to the appropriate rendering path.
"""
from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from OpenGL.GL import (
    GL_BLEND, GL_DEPTH_TEST, GL_LIGHTING, GL_LIGHTING_BIT,
    GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
    glEnable, glDisable, glPushAttrib, glPopAttrib, glColor3f, glBlendFunc,
)
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.shadergeometry import create_shader_geometry

if TYPE_CHECKING:
    from OpenGLContext.passes.shaderpass import VRML97ShaderProgram


class ShaderShapeMixin:
    """Mixin providing shader-aware rendering for Shape nodes.

    This mixin checks if the render mode has shader_mode enabled and
    uses shader-based rendering if available, falling back to legacy
    rendering otherwise.

    To use, inherit from both ShaderShapeMixin and Shape:

        class MyShape(ShaderShapeMixin, Shape):
            pass
    """

    def Render(self, mode: Any = None) -> None:
        """Render the shape using shader or legacy path.

        Args:
            mode: Render mode object
        """
        if not self.geometry:
            return

        # Check if we're in shader mode
        if getattr(mode, 'shader_mode', False) and hasattr(mode, 'shader_program'):
            self._render_shader(mode)
        else:
            # Fall back to legacy rendering
            super().Render(mode)

    def _render_shader(self, mode: Any) -> None:
        """Render using the shader pipeline.

        Args:
            mode: Render mode with shader_program attribute
        """
        from OpenGLContext.passes.shaderpass import (
            configure_material_from_node,
        )

        shader_program: VRML97ShaderProgram = mode.shader_program

        # Set up material
        if self.appearance and self.appearance.material:
            configure_material_from_node(shader_program, self.appearance.material)
            transparency = float(self.appearance.material.transparency)
        else:
            shader_program.set_default_material()
            transparency = 0.0

        # Handle transparency
        if transparency > 0:
            if not mode.transparent:
                mode.addTransparent(self)
                return
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        # Set up texture if present
        if self.appearance and hasattr(self.appearance, 'texture') and self.appearance.texture:
            tex = self.appearance.texture.cached(mode)
            if tex:
                shader_program.bind_texture(tex)

                # Handle texture transform
                if hasattr(self.appearance, 'textureTransform') and self.appearance.textureTransform:
                    shader_program.set_texture_transform(self.appearance.textureTransform)
                else:
                    shader_program.set_default_texture_transform()
        else:
            shader_program.set_texture_enabled(False)
            shader_program.set_default_texture_transform()

        # Render geometry
        shader_geom = create_shader_geometry(self.geometry, mode)
        if shader_geom:
            shader_geom.render_shader(mode)
        else:
            # Fall back to legacy geometry rendering
            self.geometry.render(lit=True, textured=True, mode=mode)

        # Cleanup
        if self.appearance and hasattr(self.appearance, 'texture') and self.appearance.texture:
            shader_program.unbind_texture()

    def RenderTransparent(self, mode: Any) -> None:
        """Render transparent geometry.

        Args:
            mode: Render mode
        """
        if not self.geometry:
            return

        # Check if we're in shader mode
        if getattr(mode, 'shader_mode', False) and hasattr(mode, 'shader_program'):
            # Enable blending for transparency
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            self._render_shader(mode)
            glDisable(GL_BLEND)
        else:
            # Fall back to legacy rendering
            super().RenderTransparent(mode)


class ShaderShape(ShaderShapeMixin, Shape):
    """Shape node with shader-aware rendering.

    This class extends Shape to check for shader mode and use
    shader-based rendering when available.

    Usage:
        shape = ShaderShape(
            appearance=Appearance(
                material=Material(diffuseColor=(0.8, 0.2, 0.2)),
            ),
            geometry=Box(size=(2, 2, 2)),
        )
    """
    pass


def enable_shader_rendering(shape_node: Shape) -> Shape:
    """Add shader rendering capability to an existing Shape node.

    This function patches the shape node's Render method to use
    shader rendering when available.

    Args:
        shape_node: An existing Shape node

    Returns:
        The same shape node with shader capability added
    """
    original_render = shape_node.Render

    def shader_aware_render(mode: Any = None) -> None:
        if getattr(mode, 'shader_mode', False) and hasattr(mode, 'shader_program'):
            ShaderShapeMixin._render_shader(shape_node, mode)
        else:
            original_render(mode)

    shape_node.Render = shader_aware_render
    return shape_node
