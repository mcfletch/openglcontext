"""Shader-compatible NURBS rendering using GLU tessellator callbacks.

This module provides NURBS surface rendering that works with OpenGL core profile
by using GLU's tessellator mode to generate triangle data, then rendering with
VBOs and shaders.

The approach:
1. Configure GLU NURBS to use GLU_NURBS_TESSELLATOR mode
2. Register callbacks to collect vertex, normal, and color data
3. Convert the collected data into VBOs
4. Render using the standard shader pipeline

This allows NURBS surfaces to be rendered in core profile without
requiring OpenGL 4.0 tessellation shaders.
"""

from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.arrays import vbo
import numpy as np
import logging

log = logging.getLogger(__name__)


class NURBSTessellator:
    """Tessellates NURBS surfaces using GLU callbacks and renders with shaders.

    This class wraps GLU's NURBS tessellator functionality to generate triangle
    data that can be rendered with shaders in core profile.
    """

    def __init__(self):
        """Initialize the tessellator."""
        self._nurb = None
        self._reset_collection()

    def _reset_collection(self):
        """Reset the data collection state."""
        self._vertices = []
        self._normals = []
        self._colors = []
        self._tex_coords = []
        self._primitives = []  # List of (prim_type, start_index, count)
        self._current_prim_type = None
        self._current_prim_start = 0
        self._current_vertex_count = 0
        self._has_colors = False
        self._has_tex_coords = False

    def _on_begin(self, prim_type):
        """Callback for primitive begin."""
        self._current_prim_type = prim_type
        self._current_prim_start = len(self._vertices)
        self._current_vertex_count = 0

    def _on_vertex(self, vertex):
        """Callback for vertex data."""
        self._vertices.append(vertex[:3])
        self._current_vertex_count += 1

    def _on_normal(self, normal):
        """Callback for normal data."""
        self._normals.append(normal[:3])

    def _on_color(self, color):
        """Callback for color data."""
        self._colors.append(color[:4])
        self._has_colors = True

    def _on_tex_coord(self, tex_coord):
        """Callback for texture coordinate data."""
        self._tex_coords.append(tex_coord[:2])
        self._has_tex_coords = True

    def _on_end(self):
        """Callback for primitive end."""
        if self._current_vertex_count > 0:
            self._primitives.append((
                self._current_prim_type,
                self._current_prim_start,
                self._current_vertex_count
            ))
        self._current_prim_type = None

    def _on_error(self, errno):
        """Callback for errors."""
        log.error("GLU NURBS tessellation error %d: %s", errno, gluErrorString(errno))

    def tessellate_surface(self, surface_node, trimming_contours=None):
        """Tessellate a NURBS surface and return triangle data.

        Args:
            surface_node: A NurbsSurface node with controlPoint, uKnot, vKnot, etc.
            trimming_contours: Optional list of Contour2D nodes for trimming

        Returns:
            dict with:
                'vertices': numpy array of vertices (N, 3)
                'normals': numpy array of normals (N, 3)
                'colors': numpy array of colors (N, 4) or None
                'triangles': list of numpy arrays, each containing indices for a triangle batch
                'triangle_strips': list of numpy arrays for triangle strips
        """
        self._reset_collection()

        # Create NURBS renderer
        self._nurb = gluNewNurbsRenderer()
        try:
            # Set tessellator mode - this makes GLU call our callbacks
            # instead of rendering directly
            gluNurbsProperty(self._nurb, GLU_NURBS_MODE, GLU_NURBS_TESSELLATOR)

            # Register callbacks
            gluNurbsCallback(self._nurb, GLU_NURBS_BEGIN, self._on_begin)
            gluNurbsCallback(self._nurb, GLU_NURBS_VERTEX, self._on_vertex)
            gluNurbsCallback(self._nurb, GLU_NURBS_NORMAL, self._on_normal)
            gluNurbsCallback(self._nurb, GLU_NURBS_COLOR, self._on_color)
            gluNurbsCallback(self._nurb, GLU_NURBS_TEXTURE_COORD, self._on_tex_coord)
            gluNurbsCallback(self._nurb, GLU_NURBS_END, self._on_end)
            gluNurbsCallback(self._nurb, GLU_NURBS_ERROR, self._on_error)

            # Configure sampling - use domain distance for consistent tessellation
            sampling = getattr(surface_node, 'sampling', None)
            if sampling:
                sampling.properties(self._nurb)
            else:
                # Default sampling
                gluNurbsProperty(self._nurb, GLU_SAMPLING_METHOD, GLU_DOMAIN_DISTANCE)
                gluNurbsProperty(self._nurb, GLU_U_STEP, 20.0)
                gluNurbsProperty(self._nurb, GLU_V_STEP, 20.0)

            # Begin surface tessellation
            gluBeginSurface(self._nurb)
            try:
                # Get surface parameters
                control_points = np.array(surface_node.controlPoint, dtype='f')
                u_knot = np.array(surface_node.uKnot, dtype='f')
                v_knot = np.array(surface_node.vKnot, dtype='f')
                u_dim = int(surface_node.uDimension)
                v_dim = int(surface_node.vDimension)

                # Reshape control points if needed
                if control_points.ndim == 2:
                    control_points = control_points.reshape((v_dim, u_dim, 3))

                # Add color surface if colors are provided
                if hasattr(surface_node, 'color') and len(surface_node.color):
                    color_data = np.array(surface_node.color, dtype='f')
                    if color_data.ndim == 2:
                        # Expand RGB to RGBA
                        if color_data.shape[1] == 3:
                            rgba = np.ones((len(color_data), 4), dtype='f')
                            rgba[:, :3] = color_data
                            color_data = rgba
                        color_data = color_data.reshape((v_dim, u_dim, 4))
                    elif color_data.ndim == 3 and color_data.shape[2] == 3:
                        # 3D array with RGB, expand to RGBA
                        rgba = np.ones((v_dim, u_dim, 4), dtype='f')
                        rgba[:, :, :3] = color_data
                        color_data = rgba
                    gluNurbsSurface(self._nurb, v_knot, u_knot, color_data, GL_MAP2_COLOR_4)

                # Add vertex surface
                gluNurbsSurface(self._nurb, v_knot, u_knot, control_points, GL_MAP2_VERTEX_3)

                # Apply trimming contours if provided
                if trimming_contours:
                    for contour in trimming_contours:
                        contour.trim(self._nurb)

            finally:
                gluEndSurface(self._nurb)

        finally:
            gluDeleteNurbsRenderer(self._nurb)
            self._nurb = None

        return self._build_result()

    def _build_result(self):
        """Convert collected data to numpy arrays and organize by primitive type."""
        if not self._vertices:
            return {
                'vertices': np.array([], dtype='f').reshape(0, 3),
                'normals': np.array([], dtype='f').reshape(0, 3),
                'colors': None,
                'triangles': [],
                'triangle_strips': [],
            }

        vertices = np.array(self._vertices, dtype='f')
        normals = np.array(self._normals, dtype='f') if self._normals else np.zeros_like(vertices)

        colors = None
        if self._has_colors and self._colors:
            colors = np.array(self._colors, dtype='f')

        # Organize primitives by type
        triangles = []  # GL_TRIANGLES batches
        triangle_strips = []  # GL_TRIANGLE_STRIP batches

        for prim_type, start, count in self._primitives:
            indices = np.arange(start, start + count, dtype='I')

            if prim_type == GL_TRIANGLES:
                triangles.append(indices)
            elif prim_type == GL_TRIANGLE_STRIP:
                triangle_strips.append(indices)
            elif prim_type == GL_TRIANGLE_FAN:
                # Convert triangle fan to triangles
                if count >= 3:
                    tri_indices = []
                    for i in range(1, count - 1):
                        tri_indices.extend([start, start + i, start + i + 1])
                    triangles.append(np.array(tri_indices, dtype='I'))
            elif prim_type == GL_POLYGON:
                # Convert polygon to triangle fan, then to triangles
                if count >= 3:
                    tri_indices = []
                    for i in range(1, count - 1):
                        tri_indices.extend([start, start + i, start + i + 1])
                    triangles.append(np.array(tri_indices, dtype='I'))

        return {
            'vertices': vertices,
            'normals': normals,
            'colors': colors,
            'triangles': triangles,
            'triangle_strips': triangle_strips,
        }


class NURBSShaderGeometry:
    """Cached shader-compatible geometry for a NURBS surface.

    This class holds the VBOs and rendering data for a tessellated NURBS surface.
    """

    def __init__(self, tess_data):
        """Create geometry from tessellation data.

        Args:
            tess_data: Result dict from NURBSTessellator.tessellate_surface()
        """
        self.vertex_count = len(tess_data['vertices'])
        self.has_colors = tess_data['colors'] is not None

        if self.vertex_count == 0:
            self.vbo = None
            self.triangle_indices = []
            self.strip_indices = []
            return

        # Build interleaved vertex data: [tex_coord(2), normal(3), vertex(3)] = 8 floats
        # For now we'll use a simpler format: [normal(3), vertex(3)] = 6 floats
        # with optional color

        vertices = tess_data['vertices']
        normals = tess_data['normals']
        colors = tess_data['colors']

        if self.has_colors:
            # Format: color(4) + normal(3) + vertex(3) = 10 floats per vertex
            interleaved = np.zeros((self.vertex_count, 10), dtype='f')
            interleaved[:, 0:4] = colors
            interleaved[:, 4:7] = normals
            interleaved[:, 7:10] = vertices
            self.stride = 40  # 10 * 4 bytes
            self.color_offset = 0
            self.normal_offset = 16  # 4 * 4 bytes
            self.vertex_offset = 28  # 7 * 4 bytes
        else:
            # Format: normal(3) + vertex(3) = 6 floats per vertex
            interleaved = np.zeros((self.vertex_count, 6), dtype='f')
            interleaved[:, 0:3] = normals
            interleaved[:, 3:6] = vertices
            self.stride = 24  # 6 * 4 bytes
            self.color_offset = None
            self.normal_offset = 0
            self.vertex_offset = 12  # 3 * 4 bytes

        self.vbo = vbo.VBO(interleaved.flatten())

        # Store index arrays
        self.triangle_indices = tess_data['triangles']
        self.strip_indices = tess_data['triangle_strips']

    def render(self, mode):
        """Render the geometry using the shader pipeline.

        Args:
            mode: The render pass mode object
        """
        if self.vbo is None or self.vertex_count == 0:
            return 0

        self.vbo.bind()
        try:
            # Set up vertex attributes for shader
            # Using the same attribute locations as our VRML97 lighting shader:
            # location 0 = texcoord (not used here)
            # location 1 = normal
            # location 2 = position

            # Disable texcoord attribute since we don't have it
            glDisableVertexAttribArray(0)

            # Normal attribute (location 1)
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(
                1, 3, GL_FLOAT, GL_FALSE,
                self.stride, self.vbo + self.normal_offset
            )

            # Position attribute (location 2)
            glEnableVertexAttribArray(2)
            glVertexAttribPointer(
                2, 3, GL_FLOAT, GL_FALSE,
                self.stride, self.vbo + self.vertex_offset
            )

            # If we have colors, we need to handle them specially
            # For now, colors from NURBS will be passed through material

            # Draw triangles
            for indices in self.triangle_indices:
                glDrawElements(GL_TRIANGLES, len(indices), GL_UNSIGNED_INT, indices)

            # Draw triangle strips
            for indices in self.strip_indices:
                glDrawElements(GL_TRIANGLE_STRIP, len(indices), GL_UNSIGNED_INT, indices)

        finally:
            glDisableVertexAttribArray(1)
            glDisableVertexAttribArray(2)
            self.vbo.unbind()

        return 1


# Module-level tessellator instance (reused)
_tessellator = None

def get_tessellator():
    """Get the module-level tessellator instance."""
    global _tessellator
    if _tessellator is None:
        _tessellator = NURBSTessellator()
    return _tessellator


def tessellate_and_cache(surface_node, trimming_contours, mode):
    """Tessellate a NURBS surface and cache the result.

    Args:
        surface_node: NurbsSurface node
        trimming_contours: Optional list of trimming contours
        mode: Render pass mode (for cache access)

    Returns:
        NURBSShaderGeometry instance
    """
    cache_key = 'nurbs_shader_geom'

    # Check cache
    cached = mode.cache.getData(surface_node, cache_key)
    if cached is not None:
        return cached

    # Tessellate
    tessellator = get_tessellator()
    tess_data = tessellator.tessellate_surface(surface_node, trimming_contours)

    # Create geometry
    geom = NURBSShaderGeometry(tess_data)

    # Cache it
    from vrml import protofunctions
    holder = mode.cache.holder(surface_node, geom, cache_key)
    holder.depend(surface_node, protofunctions.getField(surface_node, 'controlPoint'))
    holder.depend(surface_node, protofunctions.getField(surface_node, 'uKnot'))
    holder.depend(surface_node, protofunctions.getField(surface_node, 'vKnot'))
    if hasattr(surface_node, 'color'):
        holder.depend(surface_node, protofunctions.getField(surface_node, 'color'))

    return geom
