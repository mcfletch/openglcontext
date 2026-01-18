"""Shader-based rendering pass implementing VRML97 lighting model

This module provides a shader-based alternative to the legacy fixed-function
rendering pipeline. It implements the VRML97 lighting model using GLSL shaders.

The shader pass is designed to:
1. Work alongside the existing flatcompat rendering path
2. Provide the same visual output as the fixed-function pipeline
3. Be selectable as an alternative render path
"""
from __future__ import annotations

import os
import logging
from math import cos, sin
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

from OpenGL.GL import (
    GL_FALSE, GL_VERTEX_SHADER, GL_FRAGMENT_SHADER,
    GL_TEXTURE0, GL_TEXTURE_2D, GL_CURRENT_PROGRAM,
    glUseProgram, glGetUniformLocation, glGetIntegerv,
    glUniform1i, glUniform1f,
    glUniform3fv, glUniform4fv, glUniformMatrix3fv, glUniformMatrix4fv,
    glActiveTexture, glBindTexture,
)
from OpenGL.GL import shaders as GL_shaders
from OpenGLContext.arrays import array
import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from OpenGLContext.texture import Texture

log = logging.getLogger(__name__)

# Type aliases
Color3 = Tuple[float, float, float]
Color4 = Tuple[float, float, float, float]
Vec3 = Tuple[float, float, float]
Vec4 = Tuple[float, float, float, float]
Matrix4 = npt.NDArray[np.float32]
Matrix3 = npt.NDArray[np.float32]

# Path to shader files
SHADER_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'shaders')


class VRML97ShaderProgram:
    """Manages the VRML97 lighting shader program and uniforms.

    This class encapsulates shader compilation, uniform management,
    and provides methods for setting up material and light parameters.
    """

    # Maximum lights supported (matches shader)
    MAX_LIGHTS: int = 8

    def __init__(self) -> None:
        self.program: Optional[int] = None
        self.unlit_program: Optional[int] = None
        self.vertex_color_program: Optional[int] = None  # For per-vertex color geometry
        self.point_program: Optional[int] = None  # For PointSet with per-vertex colors
        self.line_program: Optional[int] = None  # For IndexedLineSet with per-vertex colors
        # Cache uniform locations per program: {program_id: {uniform_name: location}}
        self._location_cache: Dict[int, Dict[str, int]] = {}
        self._compiled: bool = False

    def compile(self) -> bool:
        """Compile the shader programs from source files.

        Returns:
            True if compilation succeeded, False otherwise
        """
        if self._compiled:
            return self.program is not None

        try:
            # Load and compile main lighting shader
            vert_path = os.path.join(SHADER_DIR, 'vrml97_lighting.vert')
            frag_path = os.path.join(SHADER_DIR, 'vrml97_lighting.frag')

            with open(vert_path, 'r') as f:
                vert_source = f.read()
            with open(frag_path, 'r') as f:
                frag_source = f.read()

            vertex_shader = GL_shaders.compileShader(vert_source, GL_VERTEX_SHADER)
            fragment_shader = GL_shaders.compileShader(frag_source, GL_FRAGMENT_SHADER)
            self.program = GL_shaders.compileProgram(vertex_shader, fragment_shader)

            # Load and compile unlit shader for selection
            unlit_vert_path = os.path.join(SHADER_DIR, 'vrml97_unlit.vert')
            unlit_frag_path = os.path.join(SHADER_DIR, 'vrml97_unlit.frag')

            with open(unlit_vert_path, 'r') as f:
                unlit_vert_source = f.read()
            with open(unlit_frag_path, 'r') as f:
                unlit_frag_source = f.read()

            unlit_vertex = GL_shaders.compileShader(unlit_vert_source, GL_VERTEX_SHADER)
            unlit_fragment = GL_shaders.compileShader(unlit_frag_source, GL_FRAGMENT_SHADER)
            self.unlit_program = GL_shaders.compileProgram(unlit_vertex, unlit_fragment)

            # Load and compile vertex color shader (for NURBS and other per-vertex color geometry)
            vc_vert_path = os.path.join(SHADER_DIR, 'vrml97_vertex_color.vert')
            vc_frag_path = os.path.join(SHADER_DIR, 'vrml97_vertex_color.frag')

            with open(vc_vert_path, 'r') as f:
                vc_vert_source = f.read()
            with open(vc_frag_path, 'r') as f:
                vc_frag_source = f.read()

            vc_vertex = GL_shaders.compileShader(vc_vert_source, GL_VERTEX_SHADER)
            vc_fragment = GL_shaders.compileShader(vc_frag_source, GL_FRAGMENT_SHADER)
            self.vertex_color_program = GL_shaders.compileProgram(vc_vertex, vc_fragment)

            # Load and compile point shader (for PointSet with per-vertex colors)
            pt_vert_path = os.path.join(SHADER_DIR, 'vrml97_point.vert')
            pt_frag_path = os.path.join(SHADER_DIR, 'vrml97_point.frag')

            with open(pt_vert_path, 'r') as f:
                pt_vert_source = f.read()
            with open(pt_frag_path, 'r') as f:
                pt_frag_source = f.read()

            pt_vertex = GL_shaders.compileShader(pt_vert_source, GL_VERTEX_SHADER)
            pt_fragment = GL_shaders.compileShader(pt_frag_source, GL_FRAGMENT_SHADER)
            self.point_program = GL_shaders.compileProgram(pt_vertex, pt_fragment)

            # Load and compile line shader (for IndexedLineSet with per-vertex colors)
            ln_vert_path = os.path.join(SHADER_DIR, 'vrml97_line.vert')
            ln_frag_path = os.path.join(SHADER_DIR, 'vrml97_line.frag')

            with open(ln_vert_path, 'r') as f:
                ln_vert_source = f.read()
            with open(ln_frag_path, 'r') as f:
                ln_frag_source = f.read()

            ln_vertex = GL_shaders.compileShader(ln_vert_source, GL_VERTEX_SHADER)
            ln_fragment = GL_shaders.compileShader(ln_frag_source, GL_FRAGMENT_SHADER)
            self.line_program = GL_shaders.compileProgram(ln_vertex, ln_fragment)

            self._compiled = True
            log.info("VRML97 shader programs compiled successfully")
            return True

        except Exception as err:
            log.error("Failed to compile VRML97 shaders: %s", err)
            self._compiled = True  # Mark as attempted
            return False

    def use(self, lit: bool = True, vertex_colors: bool = False) -> bool:
        """Activate the shader program.

        Args:
            lit: If True, use the lighting shader. If False, use unlit shader.
            vertex_colors: If True (and lit=True), use vertex color shader instead.

        Returns:
            True if shader was activated, False otherwise
        """
        if not self._compiled:
            self.compile()

        if lit and vertex_colors:
            program = self.vertex_color_program
        elif lit:
            program = self.program
        else:
            program = self.unlit_program
        if program:
            glUseProgram(program)
        return program is not None

    def use_vertex_color(self) -> bool:
        """Activate the vertex color shader program.

        Use this for geometry with per-vertex colors (like NURBS with color arrays).

        Returns:
            True if shader was activated, False otherwise
        """
        return self.use(lit=True, vertex_colors=True)

    def use_point(self) -> bool:
        """Activate the point shader program.

        Use this for PointSet geometry with per-vertex colors.
        This is a simple unlit shader that passes through vertex colors.

        Returns:
            True if shader was activated, False otherwise
        """
        if not self._compiled:
            self.compile()
        if self.point_program:
            glUseProgram(self.point_program)
            return True
        return False

    def use_line(self) -> bool:
        """Activate the line shader program.

        Use this for IndexedLineSet geometry with per-vertex colors.
        This is a simple unlit shader that passes through vertex colors.

        Returns:
            True if shader was activated, False otherwise
        """
        if not self._compiled:
            self.compile()
        if self.line_program:
            glUseProgram(self.line_program)
            return True
        return False

    def unuse(self) -> None:
        """Deactivate the shader program."""
        glUseProgram(0)

    def _get_location(self, name: str, program: Optional[int] = None) -> int:
        """Get uniform location, caching the result.

        Args:
            name: Uniform name
            program: Shader program (defaults to lit program)

        Returns:
            Uniform location, or -1 if not found
        """
        if program is None:
            program = self.program

        if program is None:
            return -1

        # Use per-program cache
        if program not in self._location_cache:
            self._location_cache[program] = {}
        cache = self._location_cache[program]

        if name not in cache:
            cache[name] = glGetUniformLocation(program, name)
        return cache[name]

    def set_matrices(
        self,
        modelview: Matrix4,
        projection: Matrix4,
        program: Optional[int] = None
    ) -> None:
        """Set the transformation matrices.

        Args:
            modelview: 4x4 modelview matrix (numpy array)
            projection: 4x4 projection matrix (numpy array)
            program: Shader program (defaults to currently active program)

        Note: If no program is specified, uses the currently bound program.
              This allows geometry nodes to update matrices without knowing
              which rendering mode (lit vs unlit) is active.
        """
        if program is None:
            # Use the currently bound program
            program = glGetIntegerv(GL_CURRENT_PROGRAM)
            if program == 0:
                # No program bound, default to lit program
                program = self.program

        mv_loc = self._get_location('modelViewMatrix', program)
        proj_loc = self._get_location('projectionMatrix', program)

        if mv_loc != -1:
            glUniformMatrix4fv(mv_loc, 1, GL_FALSE, modelview.astype('f'))
        if proj_loc != -1:
            glUniformMatrix4fv(proj_loc, 1, GL_FALSE, projection.astype('f'))

        # Calculate and set normal matrix (inverse transpose of upper-left 3x3)
        # Do this for any lit shader that uses normals (main or vertex color)
        if program == self.program or program == self.vertex_color_program:
            normal_loc = self._get_location('normalMatrix', program)
            if normal_loc != -1:
                # Extract the upper-left 3x3 of the modelview matrix
                mv3 = modelview[:3, :3].astype('f')
                # Compute inverse-transpose for proper normal transformation
                # This handles non-uniform scaling correctly
                try:
                    normal_matrix = np.linalg.inv(mv3).T
                except np.linalg.LinAlgError:
                    # Fallback if matrix is singular
                    normal_matrix = mv3
                glUniformMatrix3fv(normal_loc, 1, GL_FALSE, normal_matrix.astype('f'))

    def set_material(
        self,
        diffuse: Color3 = (0.8, 0.8, 0.8),
        specular: Color3 = (0.0, 0.0, 0.0),
        emissive: Color3 = (0.0, 0.0, 0.0),
        ambient_intensity: float = 0.2,
        shininess: float = 0.2,
        transparency: float = 0.0
    ) -> None:
        """Set material uniforms.

        Args match VRML97 Material node fields:
            diffuse: RGB diffuse color (0-1)
            specular: RGB specular color (0-1)
            emissive: RGB emissive color (0-1)
            ambient_intensity: Ambient intensity factor (0-1)
            shininess: Shininess factor (0-1, mapped to 1-128 in shader)
            transparency: Transparency (0=opaque, 1=fully transparent)
        """
        self._set_uniform3f('diffuseColor', diffuse)
        self._set_uniform3f('specularColor', specular)
        self._set_uniform3f('emissiveColor', emissive)
        self._set_uniform1f('ambientIntensity', ambient_intensity)
        self._set_uniform1f('shininess', shininess)
        self._set_uniform1f('transparency', transparency)

    def set_default_material(self) -> None:
        """Set VRML97 default material values."""
        self.set_material(
            diffuse=(0.8, 0.8, 0.8),
            specular=(0.0, 0.0, 0.0),
            emissive=(0.0, 0.0, 0.0),
            ambient_intensity=0.2,
            shininess=0.2,
            transparency=0.0
        )

    def set_scene_ambient(self, ambient: Color3 = (0.2, 0.2, 0.2)) -> None:
        """Set scene ambient color."""
        self._set_uniform3f('sceneAmbient', ambient)

    def set_num_lights(self, count: int, program: Optional[int] = None) -> None:
        """Set the number of active lights."""
        self._set_uniform1i('numLights', min(count, self.MAX_LIGHTS), program)

    def set_light(
        self,
        index: int,
        light_type: str = 'directional',
        color: Color3 = (1.0, 1.0, 1.0),
        position: Vec4 = (0.0, 0.0, 1.0, 0.0),
        direction: Vec3 = (0.0, 0.0, -1.0),
        attenuation: Vec3 = (1.0, 0.0, 0.0),
        intensity: float = 1.0,
        beam_width: float = 1.57,
        cutoff_angle: float = 0.785,
        program: Optional[int] = None
    ) -> None:
        """Set parameters for a single light.

        Args:
            index: Light index (0 to MAX_LIGHTS-1)
            light_type: 'off', 'directional', 'point', or 'spot'
            color: RGB color (0-1)
            position: XYZ position (w=0 for directional, w=1 for positional)
            direction: XYZ direction (for directional and spot)
            attenuation: (constant, linear, quadratic) factors
            intensity: Light intensity multiplier
            beam_width: Spot inner cone angle (radians)
            cutoff_angle: Spot outer cone angle (radians)
            program: Shader program to set uniforms on (defaults to main lit program)
        """
        if index >= self.MAX_LIGHTS:
            return

        type_map = {'off': 0, 'directional': 1, 'point': 2, 'spot': 3}
        type_val = type_map.get(light_type, 0)

        self._set_uniform1i(f'lightType[{index}]', type_val, program)
        self._set_uniform3f(f'lightColor[{index}]', color, program)
        self._set_uniform4f(f'lightPosition[{index}]', position, program)
        self._set_uniform3f(f'lightDirection[{index}]', direction, program)
        self._set_uniform3f(f'lightAttenuation[{index}]', attenuation, program)
        self._set_uniform1f(f'lightIntensity[{index}]', intensity, program)
        self._set_uniform1f(f'lightBeamWidth[{index}]', beam_width, program)
        self._set_uniform1f(f'lightCutOffAngle[{index}]', cutoff_angle, program)

    def set_default_light(self) -> None:
        """Set up default VRML97 headlight (directional from camera)."""
        self.set_num_lights(1)
        self.set_light(
            0,
            light_type='directional',
            color=(1.0, 1.0, 1.0),
            direction=(0.0, 0.0, -1.0),
            intensity=1.0
        )

    def set_texture_enabled(self, enabled: bool, texture_unit: int = 0) -> None:
        """Enable or disable diffuse texture."""
        self._set_uniform1i('hasDiffuseTexture', 1 if enabled else 0)
        if enabled:
            self._set_uniform1i('diffuseTexture', texture_unit)

    def set_solid_color(self, color: Color4) -> None:
        """Set solid color for unlit shader (used for picking)."""
        loc = self._get_location('solidColor', self.unlit_program)
        if loc != -1:
            glUniform4fv(loc, 1, array(color, 'f'))

    def set_text_mode(
        self,
        enabled: bool,
        text_color: Color4 = (1.0, 1.0, 1.0, 1.0),
        background_color: Color4 = (0.0, 0.0, 0.0, 1.0),
        solid_background: bool = False
    ) -> None:
        """Configure text rendering mode for the unlit shader.

        Args:
            enabled: Enable text rendering mode
            text_color: RGBA color for text (foreground)
            background_color: RGBA color for background (when solid_background=True)
            solid_background: If True, render solid background instead of transparent
        """
        # Set text mode flag
        loc = self._get_location('textMode', self.unlit_program)
        if loc != -1:
            glUniform1i(loc, 1 if enabled else 0)

        # Set text color
        loc = self._get_location('textColor', self.unlit_program)
        if loc != -1:
            glUniform4fv(loc, 1, array(text_color, 'f'))

        # Set background color
        loc = self._get_location('backgroundColor', self.unlit_program)
        if loc != -1:
            glUniform4fv(loc, 1, array(background_color, 'f'))

        # Set solid background flag
        loc = self._get_location('textSolidBg', self.unlit_program)
        if loc != -1:
            glUniform1i(loc, 1 if solid_background else 0)

        # Also set useTexture for text mode (text always uses texture)
        if enabled:
            loc = self._get_location('useTexture', self.unlit_program)
            if loc != -1:
                glUniform1i(loc, 1)

    def bind_texture(self, texture_obj: Optional[Texture], texture_unit: int = 0) -> None:
        """Bind a texture for shader use.

        Args:
            texture_obj: OpenGLContext Texture object (has .texture attribute)
            texture_unit: Texture unit to bind to (default 0)
        """
        if texture_obj is None:
            self.set_texture_enabled(False)
            return

        # Activate texture unit
        glActiveTexture(GL_TEXTURE0 + texture_unit)

        # Bind the texture
        glBindTexture(GL_TEXTURE_2D, texture_obj.texture)

        # Tell shader we have a texture
        self.set_texture_enabled(True, texture_unit)

    def unbind_texture(self, texture_unit: int = 0) -> None:
        """Unbind texture and disable texture sampling."""
        glActiveTexture(GL_TEXTURE0 + texture_unit)
        glBindTexture(GL_TEXTURE_2D, 0)
        self.set_texture_enabled(False)

    def set_texture_transform(self, transform_node: Optional[Any] = None) -> None:
        """Set texture transform matrix from a VRML97 TextureTransform node.

        Args:
            transform_node: TextureTransform node, or None for identity
        """
        if transform_node is None:
            # Identity matrix (no transform)
            tex_matrix = np.eye(3, dtype='f')
        else:
            # Build 2D homogeneous transform matrix from TextureTransform fields
            # Order: translate(center) -> rotate -> scale -> translate(-center) -> translate
            tx, ty = transform_node.translation
            cx, cy = transform_node.center
            angle = transform_node.rotation
            sx, sy = transform_node.scale

            # Start with identity
            tex_matrix = np.eye(3, dtype='f')

            # Translate to center
            if cx != 0 or cy != 0:
                T_center = np.array([
                    [1, 0, cx],
                    [0, 1, cy],
                    [0, 0, 1]
                ], dtype='f')
                tex_matrix = tex_matrix @ T_center

            # Rotate
            if angle != 0:
                c, s = cos(angle), sin(angle)
                R = np.array([
                    [c, -s, 0],
                    [s, c, 0],
                    [0, 0, 1]
                ], dtype='f')
                tex_matrix = tex_matrix @ R

            # Scale
            if sx != 1 or sy != 1:
                S = np.array([
                    [sx, 0, 0],
                    [0, sy, 0],
                    [0, 0, 1]
                ], dtype='f')
                tex_matrix = tex_matrix @ S

            # Translate from center
            if cx != 0 or cy != 0:
                T_neg_center = np.array([
                    [1, 0, -cx],
                    [0, 1, -cy],
                    [0, 0, 1]
                ], dtype='f')
                tex_matrix = tex_matrix @ T_neg_center

            # Apply translation
            if tx != 0 or ty != 0:
                T = np.array([
                    [1, 0, tx],
                    [0, 1, ty],
                    [0, 0, 1]
                ], dtype='f')
                tex_matrix = tex_matrix @ T

        loc = self._get_location('textureMatrix')
        if loc != -1:
            glUniformMatrix3fv(loc, 1, GL_FALSE, tex_matrix)

    def set_default_texture_transform(self) -> None:
        """Set identity texture transform."""
        self.set_texture_transform(None)

    def _set_uniform1i(self, name: str, value: int, program: Optional[int] = None) -> None:
        loc = self._get_location(name, program)
        if loc != -1:
            glUniform1i(loc, value)

    def _set_uniform1f(self, name: str, value: float, program: Optional[int] = None) -> None:
        loc = self._get_location(name, program)
        if loc != -1:
            glUniform1f(loc, float(value))

    def _set_uniform3f(self, name: str, value: Vec3, program: Optional[int] = None) -> None:
        loc = self._get_location(name, program)
        if loc != -1:
            glUniform3fv(loc, 1, array(value, 'f'))

    def _set_uniform4f(self, name: str, value: Vec4, program: Optional[int] = None) -> None:
        loc = self._get_location(name, program)
        if loc != -1:
            glUniform4fv(loc, 1, array(value, 'f'))


class ShaderRenderMode:
    """Render mode flag indicating shader-based rendering is active.

    Geometry nodes can check mode.shader_mode to determine whether
    to use shader-based or legacy rendering.
    """
    shader_mode: bool = True
    shader_program: Optional[VRML97ShaderProgram] = None

    def __init__(self, base_mode: Any, shader_program: VRML97ShaderProgram) -> None:
        """Wrap a base render mode with shader capabilities.

        Args:
            base_mode: The underlying render mode (from flatcompat)
            shader_program: VRML97ShaderProgram instance
        """
        self._base_mode = base_mode
        self.shader_program = shader_program

    def __getattr__(self, name: str) -> Any:
        """Delegate to base mode for any attributes we don't override."""
        return getattr(self._base_mode, name)


# Global shader program instance (lazy initialization)
_shader_program: Optional[VRML97ShaderProgram] = None


def get_shader_program() -> VRML97ShaderProgram:
    """Get the global VRML97 shader program, compiling if needed."""
    global _shader_program
    if _shader_program is None:
        _shader_program = VRML97ShaderProgram()
    return _shader_program


def configure_light_from_node(
    shader_program: VRML97ShaderProgram,
    index: int,
    light_node: Any,
    modelview_matrix: Optional[Matrix4] = None,
    program: Optional[int] = None
) -> None:
    """Configure shader light from a VRML97 Light node.

    Args:
        shader_program: VRML97ShaderProgram instance
        index: Light index (0 to MAX_LIGHTS-1)
        light_node: A VRML97 Light node (DirectionalLight, PointLight, SpotLight)
        modelview_matrix: Modelview matrix to transform light position/direction to eye space.
                         This is required to match fixed-function OpenGL behavior where
                         glLightfv transforms the light by the current modelview matrix.
        program: Shader program to set uniforms on (defaults to main lit program)
    """
    from OpenGLContext.scenegraph import light as light_module

    if not light_node.on:
        shader_program.set_light(index, light_type='off', program=program)
        return

    # Get light color and intensity
    color = tuple(light_node.color)
    intensity = float(light_node.intensity)

    def transform_direction(direction: Vec3) -> Vec3:
        """Transform direction vector by modelview matrix (ignoring translation)."""
        if modelview_matrix is None:
            return direction
        # For directions, use only the upper 3x3 rotation/scale part
        # Note: OpenGLContext matrices are row-major (row vectors), so use d @ M
        d = np.array([direction[0], direction[1], direction[2]], dtype=np.float32)
        mv3 = modelview_matrix[:3, :3]
        transformed = d @ mv3
        # Normalize the result
        length = np.sqrt(np.sum(transformed * transformed))
        if length > 0:
            transformed = transformed / length
        return tuple(transformed)

    def transform_position(position: Vec3) -> Vec4:
        """Transform position by modelview matrix."""
        if modelview_matrix is None:
            return tuple(position) + (1.0,)
        # For positions, use full 4x4 transform
        # Note: OpenGLContext matrices are row-major (row vectors), so use p @ M
        p = np.array([position[0], position[1], position[2], 1.0], dtype=np.float32)
        transformed = p @ modelview_matrix
        # Return as (x, y, z, 1.0) - w=1 for positional light
        return (float(transformed[0]), float(transformed[1]), float(transformed[2]), 1.0)

    # Determine light type and parameters
    if isinstance(light_node, light_module.DirectionalLight):
        # Directional light - direction is constant
        # VRML direction is where light points (e.g., (0,-1,0) means pointing down)
        # Pass to shader as-is; shader will negate to get direction toward light
        orig_direction = tuple(light_node.direction)
        direction = transform_direction(orig_direction)
        shader_program.set_light(
            index,
            light_type='directional',
            color=color,
            direction=direction,
            intensity=intensity,
            program=program,
        )

    elif isinstance(light_node, light_module.SpotLight):
        # Spot light - has position, direction, and cone angles
        position = transform_position(tuple(light_node.location))
        direction = transform_direction(tuple(light_node.direction))
        attenuation = tuple(light_node.attenuation)

        # VRML97 uses cutOffAngle and beamWidth in radians
        cutoff_angle = float(light_node.cutOffAngle)
        beam_width = float(getattr(light_node, 'beamWidth', cutoff_angle))

        shader_program.set_light(
            index,
            light_type='spot',
            color=color,
            position=position,
            direction=direction,
            attenuation=attenuation,
            intensity=intensity,
            beam_width=beam_width,
            cutoff_angle=cutoff_angle,
            program=program,
        )

    elif isinstance(light_node, light_module.PointLight):
        # Point light - has position and attenuation
        position = transform_position(tuple(light_node.location))
        attenuation = tuple(light_node.attenuation)

        shader_program.set_light(
            index,
            light_type='point',
            color=color,
            position=position,
            attenuation=attenuation,
            intensity=intensity,
            program=program,
        )

    else:
        # Unknown light type - treat as directional
        direction = getattr(light_node, 'direction', (0.0, 0.0, -1.0))
        direction = transform_direction(tuple(direction))
        shader_program.set_light(
            index,
            light_type='directional',
            color=color,
            direction=direction,
            intensity=intensity,
            program=program,
        )


def configure_material_from_node(
    shader_program: VRML97ShaderProgram,
    material_node: Optional[Any]
) -> None:
    """Configure shader material from a VRML97 Material node.

    Args:
        shader_program: VRML97ShaderProgram instance
        material_node: A VRML97 Material node
    """
    if material_node is None:
        shader_program.set_default_material()
        return

    diffuse = tuple(material_node.diffuseColor)
    specular = tuple(material_node.specularColor)
    emissive = tuple(material_node.emissiveColor)
    ambient = float(material_node.ambientIntensity)
    shininess = float(material_node.shininess)
    transparency = float(material_node.transparency)

    log.debug(f"Material: diffuse={diffuse}, specular={specular}, ambient={ambient}")

    shader_program.set_material(
        diffuse=diffuse,
        specular=specular,
        emissive=emissive,
        ambient_intensity=ambient,
        shininess=shininess,
        transparency=transparency,
    )
