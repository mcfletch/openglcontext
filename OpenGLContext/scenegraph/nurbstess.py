"""GLU-callback tessellation service for NURBS surfaces.

Turns a NURBS surface (control points + knots, with optional colour / trims /
parametric texcoords) into a triangle-soup VBO via the GLU tessellator in callback
mode, so NURBS works under the core profile.

The service is parameterised by the ``surface`` (and a sampling node / explicit
LOD steps), not by any node ``self``; the surface node classes call into it from
their ``_build_shader_geometry_cached`` overrides. :mod:`nurbs` re-exports
:func:`_tessellate_nurbs_surface` and :func:`_build_nurbs_vbo`, which
:mod:`teapot_nurbs` reaches for as ``nurbs._tessellate_nurbs_surface``.
"""

from OpenGL.GLU import *
from OpenGL.GL import *
from OpenGL.arrays import vbo
import logging

from OpenGLContext import arrays
from OpenGLContext.scenegraph.nurbssampling import (
    NurbsToleranceSample,
    NurbsDomainDistanceSample,
)

log = logging.getLogger(__name__)


class NURBSTessellatorCallback:
    """Collects tessellated NURBS data via GLU callbacks.

    This class is used to tessellate NURBS surfaces into triangle data
    that can be rendered with shaders in core profile.
    """

    def __init__(self):
        """Initialize the callback collector."""
        self.reset()

    def reset(self):
        """Reset collection state for a new tessellation."""
        self.vertices = []
        self.normals = []
        self.colors = []
        self.texcoords = []
        self.primitives = []  # List of (prim_type, start_index, count)
        self._current_type = None
        self._current_start = 0
        self._current_count = 0
        self._has_colors = False

    def on_begin(self, prim_type):
        """Callback for primitive begin."""
        self._current_type = prim_type
        self._current_start = len(self.vertices)
        self._current_count = 0

    def on_vertex(self, vertex):
        """Callback for vertex data."""
        self.vertices.append((float(vertex[0]), float(vertex[1]), float(vertex[2])))
        self._current_count += 1

    def on_normal(self, normal):
        """Callback for normal data."""
        self.normals.append((float(normal[0]), float(normal[1]), float(normal[2])))

    def on_color(self, color):
        """Callback for color data."""
        self.colors.append((float(color[0]), float(color[1]), float(color[2]), float(color[3])))
        self._has_colors = True

    def on_texcoord(self, tex):
        """Callback for texture-coordinate data (parametric u, v)."""
        self.texcoords.append((float(tex[0]), float(tex[1])))

    def on_end(self):
        """Callback for primitive end."""
        if self._current_count > 0:
            self.primitives.append((
                self._current_type,
                self._current_start,
                self._current_count
            ))
        self._current_type = None

    def on_error(self, errno):
        """Callback for errors."""
        log.error("GLU NURBS tessellation error %d: %s", errno, gluErrorString(errno))

    def build_triangles(self):
        """Convert collected primitives to triangle vertex list.

        Returns:
            List of (vertex_index, vertex_index, vertex_index) tuples
        """
        triangles = []
        for prim_type, start, count in self.primitives:
            if prim_type == GL_TRIANGLES:
                # Already triangles - take them directly
                for i in range(0, count - 2, 3):
                    triangles.append((start + i, start + i + 1, start + i + 2))
            elif prim_type == GL_TRIANGLE_STRIP:
                # Convert strip to triangles
                for i in range(count - 2):
                    if i % 2 == 0:
                        triangles.append((start + i, start + i + 1, start + i + 2))
                    else:
                        triangles.append((start + i + 1, start + i, start + i + 2))
            elif prim_type == GL_TRIANGLE_FAN:
                # Convert fan to triangles
                for i in range(1, count - 1):
                    triangles.append((start, start + i, start + i + 1))
            elif prim_type == GL_POLYGON:
                # Convert polygon to triangles (as fan)
                for i in range(1, count - 1):
                    triangles.append((start, start + i, start + i + 1))
            elif prim_type == GL_QUAD_STRIP:
                # Convert quad strip to triangles
                # Each quad is: v[i], v[i+1], v[i+3], v[i+2] (CCW order)
                for i in range(0, count - 2, 2):
                    # First triangle of quad
                    triangles.append((start + i, start + i + 1, start + i + 3))
                    # Second triangle of quad
                    triangles.append((start + i, start + i + 3, start + i + 2))
            elif prim_type == GL_QUADS:
                # Convert quads to triangles
                for i in range(0, count - 3, 4):
                    # First triangle
                    triangles.append((start + i, start + i + 1, start + i + 2))
                    # Second triangle
                    triangles.append((start + i, start + i + 2, start + i + 3))
        return triangles


# Module-level tessellator callback instance
_tess_callback = None


def _get_tess_callback():
    """Get the module-level tessellator callback instance."""
    global _tess_callback
    if _tess_callback is None:
        _tess_callback = NURBSTessellatorCallback()
    return _tess_callback


def _tessellate_nurbs_surface(surface, trimming_contours=None, sampling=None,
                              u_step=None, v_step=None, texcoord=False):
    """Tessellate a NURBS surface using GLU callbacks.

    Args:
        surface: NurbsSurface node with controlPoint, uKnot, vKnot, etc.
        trimming_contours: Optional list of Contour2D for trimming
        sampling: Optional sampling node
        u_step, v_step: Explicit GLU domain-distance steps. When given they
            override ``sampling`` -- used by the distance-LOD paths (teapot,
            NURBS surfaces) to tessellate a far-off surface coarsely.
        texcoord: When True, attach an identity ``GL_MAP2_TEXTURE_COORD_2`` map
            so GLU emits per-vertex parametric (u, v) into ``callback.texcoords``.
            Off by default, so callers that only need position/normal (e.g.
            NurbsSurface) pay no extra tessellation work.

    Returns:
        NURBSTessellatorCallback with collected data
    """
    callback = _get_tess_callback()
    callback.reset()

    nurb = gluNewNurbsRenderer()
    try:
        # Set to tessellator mode - generates callbacks instead of rendering
        gluNurbsProperty(nurb, GLU_NURBS_MODE, GLU_NURBS_TESSELLATOR)

        # Register callbacks
        gluNurbsCallback(nurb, GLU_NURBS_BEGIN, callback.on_begin)
        gluNurbsCallback(nurb, GLU_NURBS_VERTEX, callback.on_vertex)
        gluNurbsCallback(nurb, GLU_NURBS_NORMAL, callback.on_normal)
        gluNurbsCallback(nurb, GLU_NURBS_COLOR, callback.on_color)
        gluNurbsCallback(nurb, GLU_NURBS_END, callback.on_end)
        gluNurbsCallback(nurb, GLU_NURBS_ERROR, callback.on_error)
        if texcoord:
            gluNurbsCallback(nurb, GLU_NURBS_TEXTURE_COORD, callback.on_texcoord)

        # Configure sampling
        # Note: Screen-space tolerance (GLU_PATH_LENGTH) doesn't work reliably in
        # tessellator callback mode because there's no viewport context. We use
        # domain-distance sampling instead for predictable results.
        if u_step is not None and v_step is not None:
            # Explicit distance-LOD override wins over the sampling node.
            gluNurbsProperty(nurb, GLU_SAMPLING_METHOD, GLU_DOMAIN_DISTANCE)
            gluNurbsProperty(nurb, GLU_U_STEP, float(u_step))
            gluNurbsProperty(nurb, GLU_V_STEP, float(v_step))
        elif sampling and isinstance(sampling, NurbsDomainDistanceSample):
            # Domain distance sampling works fine in callback mode
            sampling.properties(nurb)
        elif sampling and isinstance(sampling, NurbsToleranceSample):
            # Convert tolerance-based sampling to domain-distance for callback mode
            # A tolerance of 3.0 pixels roughly corresponds to uStep/vStep of 30-50
            # depending on surface size. We use a heuristic based on tolerance.
            tolerance = getattr(sampling, 'tolerance', 50.0)
            # Smaller tolerance = more detail = higher steps
            # tolerance=3 -> steps=50, tolerance=50 -> steps=20
            steps = max(20.0, min(100.0, 150.0 / max(1.0, tolerance)))
            gluNurbsProperty(nurb, GLU_SAMPLING_METHOD, GLU_DOMAIN_DISTANCE)
            gluNurbsProperty(nurb, GLU_U_STEP, steps)
            gluNurbsProperty(nurb, GLU_V_STEP, steps)
        else:
            gluNurbsProperty(nurb, GLU_SAMPLING_METHOD, GLU_DOMAIN_DISTANCE)
            gluNurbsProperty(nurb, GLU_U_STEP, 30.0)
            gluNurbsProperty(nurb, GLU_V_STEP, 30.0)

        # Begin surface
        gluBeginSurface(nurb)
        try:
            # Get control points
            control_points = arrays.reshape(
                surface.controlPoint,
                (surface.vDimension, surface.uDimension, 3)
            ).astype('f')
            v_knot = surface.vKnot.astype('f')
            u_knot = surface.uKnot.astype('f')

            # Add color surface if present
            if len(surface.color):
                color_data = arrays.zeros(
                    (len(surface.controlPoint), 4), 'f'
                )
                color_data[:, :3] = surface.color.astype('f')
                color_data[:, 3] = 1.0
                color_data = arrays.reshape(
                    color_data,
                    (surface.vDimension, surface.uDimension, 4)
                )
                gluNurbsSurface(nurb, v_knot, u_knot, color_data, GL_MAP2_COLOR_4)

            # Attach an identity texture-coordinate map so GLU reports each
            # tessellated vertex's parametric (u, v) as a 0..1 texcoord over the
            # surface domain. A 2x2 order-2 grid whose corners are the domain
            # corners is the bilinear identity; its knots span the same domain as
            # the vertex surface so the two maps stay registered.
            if texcoord:
                u0, u1 = float(u_knot[0]), float(u_knot[-1])
                v0, v1 = float(v_knot[0]), float(v_knot[-1])
                tex_u_knot = arrays.array([u0, u0, u1, u1], 'f')
                tex_v_knot = arrays.array([v0, v0, v1, v1], 'f')
                tex_grid = arrays.array(
                    [[[0.0, 0.0], [1.0, 0.0]],
                     [[0.0, 1.0], [1.0, 1.0]]], 'f')
                gluNurbsSurface(
                    nurb, tex_v_knot, tex_u_knot, tex_grid, GL_MAP2_TEXTURE_COORD_2)

            # Add vertex surface
            gluNurbsSurface(nurb, v_knot, u_knot, control_points, GL_MAP2_VERTEX_3)

            # Apply trimming
            if trimming_contours:
                for contour in trimming_contours:
                    contour.trim(nurb)

        finally:
            gluEndSurface(nurb)

    finally:
        gluDeleteNurbsRenderer(nurb)
        # Clear any GL errors left by GLU tessellation (GLU may use deprecated functions)
        while glGetError() != GL_NO_ERROR:
            pass

    return callback


def _build_nurbs_vbo(callback):
    """Build a VBO from tessellated NURBS data.

    Args:
        callback: NURBSTessellatorCallback with collected data

    Returns:
        Tuple of (vbo, triangle_count, has_colors)
    """
    if not callback.vertices:
        return None, 0, False

    triangles = callback.build_triangles()
    if not triangles:
        return None, 0, False

    # Build vertex array from triangles
    # Format: normal(3) + vertex(3) = 6 floats per vertex
    # For colored: color(4) + normal(3) + vertex(3) = 10 floats
    has_colors = callback._has_colors and len(callback.colors) == len(callback.vertices)

    vertex_data = []
    for tri in triangles:
        for idx in tri:
            if has_colors:
                vertex_data.extend(callback.colors[idx])
            vertex_data.extend(callback.normals[idx] if idx < len(callback.normals) else (0, 0, 1))
            vertex_data.extend(callback.vertices[idx])

    vertex_array = arrays.array(vertex_data, 'f')
    nurbs_vbo = vbo.VBO(vertex_array)
    return nurbs_vbo, len(triangles) * 3, has_colors
