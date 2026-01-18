"""Nurbs-rendering nodes based on VRML97 Nurbs extension

NurbsSurface is a geometry object, drop it
into a shape to see the objects in a scene.

Note: at the moment, we cannot provide the object space
extension, due to what appears to be a bug in the PyOpenGL
library, so the code for that extension is short-circuit.

Shader-based rendering:
    When mode.shader_mode is True, NURBS surfaces are tessellated using
    GLU's tessellator callbacks and rendered with VBOs and shaders.
    This allows NURBS to work in OpenGL core profile.
"""

from vrml.vrml97 import nurbs, nodetypes
from vrml import node, field, fieldtypes, protofunctions
from OpenGL.GLU import *
from OpenGL.GL import *
from OpenGL.GLU.EXT.object_space_tess import *
from OpenGL.arrays import vbo
import numpy as np
import logging

log = logging.getLogger(__name__)
from OpenGLContext import arrays

object_space_tess = None


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


def _tessellate_nurbs_surface(surface, trimming_contours=None, sampling=None):
    """Tessellate a NURBS surface using GLU callbacks.

    Args:
        surface: NurbsSurface node with controlPoint, uKnot, vKnot, etc.
        trimming_contours: Optional list of Contour2D for trimming
        sampling: Optional sampling node

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

        # Configure sampling
        # Note: Screen-space tolerance (GLU_PATH_LENGTH) doesn't work reliably in
        # tessellator callback mode because there's no viewport context. We use
        # domain-distance sampling instead for predictable results.
        if sampling and isinstance(sampling, NurbsDomainDistanceSample):
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


def initialise(context=None):
    """Initialise the NURBs extensions for a context"""
    global object_space_tess
    if object_space_tess is None:
        object_space_tess = gluInitObjectSpaceTessEXT()
    return bool(object_space_tess)


class Polyline2D(nurbs.Polyline2D):
    """Simple polyline in 2D

    Basically this just calls gluPwlCurve
    """

    def render(self, nurbObject):
        """Render to the given nurbs object"""
        gluPwlCurve(nurbObject, self.point, GLU_MAP1_TRIM_2)


class NurbsCurve2D(nurbs.NurbsCurve2D):
    """Nurbs curve in 2D

    Basically this just calls gluNurbsCurve
    """

    def render(self, nurbObject):
        """Render to the given nurbs object"""
        gluNurbsCurve(nurbObject, self.knot, self.controlPoint, GLU_MAP1_TRIM_2)


class Contour2D(nurbs.Contour2D):
    """A 2D contour (collection of joined segments)

    children -- a set of polylines and/or curves which are
        joined to form the trimming contour

    Normally used to trim a Nurbs surface...
    """

    def trim(self, nurbObject):
        """Render the contour as a trim of the current surface"""
        gluBeginTrim(nurbObject)
        try:
            for child in self.children:
                child.render(nurbObject)
        finally:
            gluEndTrim(nurbObject)


def defaultSampling():
    """Get a default sampling node"""
    if initialise():
        return NurbsToleranceSample(method="object", parametric=1, tolerance=5)
    else:
        return NurbsToleranceSample(method="screen", parametric=1, tolerance=5)


class _SurfaceRenderer(object):
    """Abstract class providing surface-rendering framework

    attributes
        geometryType -- string specifying the geometry type
            "polygon", "patch", "edge"
        sampling -- NurbsSampling instance specifying a
            particular sampling methodology
    """

    geometryType = field.newField("geometryType", "SFString", 1, "polygon")  #
    sampling = field.newField("sampling", "SFNode", 1, defaultSampling)

    # Shader rendering data is stored per-instance to avoid context issues
    # These are class-level defaults that get overridden on instances

    def render(
        self,
        visible=1,  # can skip normals and textures if not
        lit=1,  # can skip normals if not
        textured=1,  # can skip textureCoordinates if not
        transparent=0,  # need to sort triangle geometry...
        mode=None,  # the renderpass object
    ):
        """Render the surface, with all the attendant error checking"""
        # Check if we need shader-based rendering
        if mode is not None and getattr(mode, 'shader_mode', False):
            return self._render_shader(mode, visible, lit)

        # Legacy fixed-function rendering
        if lit:
            glEnable(GL_AUTO_NORMAL)
            glEnable(GL_NORMALIZE)
        try:
            nurbObject = gluNewNurbsRenderer()
            try:
                gluBeginSurface(nurbObject)
                # do tessellation configuration here
                try:
                    self.renderProperties(nurbObject)
                    if self.renderSurface(nurbObject):
                        # no point rendering the trimming
                        # if there is no surface
                        self.renderTrims(nurbObject)
                finally:
                    gluEndSurface(nurbObject)
            finally:
                gluDeleteNurbsRenderer(nurbObject)
        finally:
            if lit:
                glDisable(GL_AUTO_NORMAL)
                glDisable(GL_NORMALIZE)

    def _render_shader(self, mode, visible=1, lit=1):
        """Render the surface using shader-based pipeline.

        Uses GLU tessellator callbacks to generate geometry, then
        renders via VBOs with the active shader.
        """
        # Build/update the VBO if needed - use mode.cache to store per-context
        cache_key = 'nurbs_shader_data'
        cached = mode.cache.getData(self, key=cache_key)
        if cached is None:
            cached = self._build_shader_geometry_cached()
            if cached is not None:
                # Create cache holder with dependencies on NURBS surface data
                holder = mode.cache.holder(self, cached, key=cache_key)
                # Add dependencies on fields that affect tessellation
                self._setup_shader_cache_dependencies(holder)

        if cached is None:
            return

        shader_vbo, vertex_count, has_colors = cached

        if shader_vbo is None or vertex_count == 0:
            return

        # Get shader program from mode
        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None:
            return

        # If we have per-vertex colors, switch to the vertex color shader
        # and restore the original shader afterward
        switched_shader = False
        if has_colors:
            # Switch to vertex color shader for per-vertex color support
            shader_program.use_vertex_color()
            switched_shader = True
            vc_prog = shader_program.vertex_color_program
            # Re-apply matrices to the new shader
            # Use mode.matrix which includes accumulated transforms (not getModelView())
            shader_program.set_matrices(
                mode.matrix,
                mode.getProjection(),
                vc_prog
            )
            # Set material properties that vertex color shader still uses
            # (specular, emissive, ambient, shininess - diffuse comes from vertex color)
            # Set material uniforms on the vertex color program
            # These are the non-diffuse properties
            shader_program._set_uniform3f('specularColor', (0.0, 0.0, 0.0), vc_prog)
            shader_program._set_uniform3f('emissiveColor', (0.0, 0.0, 0.0), vc_prog)
            shader_program._set_uniform1f('ambientIntensity', 0.2, vc_prog)
            shader_program._set_uniform1f('shininess', 0.2, vc_prog)
            shader_program._set_uniform1f('transparency', 0.0, vc_prog)
            shader_program._set_uniform3f('sceneAmbient', (0.2, 0.2, 0.2), vc_prog)
            # Set up lights on the vertex color program using scene lights
            self._setup_vertex_color_lights(mode, shader_program, vc_prog)

        # Create temporary VAO for core profile compatibility
        vao = glGenVertexArrays(1)
        glBindVertexArray(vao)

        try:
            # Render using the VBO
            shader_vbo.bind()
            try:
                # Determine stride based on whether we have colors
                if has_colors:
                    # color(4) + normal(3) + vertex(3) = 10 floats = 40 bytes
                    stride = 40
                    color_offset = 0
                    normal_offset = 16
                    vertex_offset = 28
                else:
                    # normal(3) + vertex(3) = 6 floats = 24 bytes
                    stride = 24
                    color_offset = None
                    normal_offset = 0
                    vertex_offset = 12

                # Set up vertex attributes for the shader
                # VRML97 shader attribute locations:
                # 0 = aTexCoord (vec2) - not used for NURBS
                # 1 = aNormal (vec3)
                # 2 = aPosition (vec3)
                # 3 = aColor (vec4) - for vertex color shader
                from ctypes import c_void_p

                # Position attribute (location 2 in VRML97 shaders)
                glEnableVertexAttribArray(2)
                glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, c_void_p(vertex_offset))

                # Normal attribute (location 1 in VRML97 shaders)
                glEnableVertexAttribArray(1)
                glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, c_void_p(normal_offset))

                # Color attribute (location 3 in vertex color shader)
                if has_colors and color_offset is not None:
                    glEnableVertexAttribArray(3)
                    glVertexAttribPointer(3, 4, GL_FLOAT, GL_FALSE, stride, c_void_p(color_offset))

                # Draw the triangles
                glDrawArrays(GL_TRIANGLES, 0, vertex_count)

                # Clean up vertex attributes
                glDisableVertexAttribArray(2)
                glDisableVertexAttribArray(1)
                if has_colors:
                    glDisableVertexAttribArray(3)
            finally:
                shader_vbo.unbind()
        finally:
            glBindVertexArray(0)
            glDeleteVertexArrays(1, [vao])

            # Restore the original lit shader if we switched
            if switched_shader:
                shader_program.use(lit=True, vertex_colors=False)
                # Re-apply matrices to the restored shader
                # Use mode.matrix which includes accumulated transforms
                shader_program.set_matrices(
                    mode.matrix,
                    mode.getProjection(),
                    shader_program.program
                )

    def _build_shader_geometry_cached(self):
        """Build VBO geometry from GLU tessellation.

        Returns:
            Tuple of (vbo, vertex_count, has_colors) or None if not supported/failed.

        Subclasses should override to provide surface-specific data.
        """
        # Base class returns None - subclasses override with actual implementation
        return None  # type: ignore[return-value]

    def _setup_vertex_color_lights(self, mode, shader_program, vc_prog):
        """Set up lights on the vertex color shader program.

        Configures the vertex color shader's light uniforms to match
        the scene's lights, similar to how setupShaderLights works
        for the main shader.

        Args:
            mode: The render mode (FlatPass instance)
            shader_program: VRML97ShaderProgram instance
            vc_prog: The vertex color program ID
        """
        from OpenGLContext.passes.shaderpass import configure_light_from_node
        from numpy import dot

        light_count = 0
        paths_dict = getattr(mode, 'paths', {})
        light_paths = paths_dict.get(nodetypes.Light, ())

        for path in light_paths:
            if light_count >= shader_program.MAX_LIGHTS:
                break
            tmatrix = path.transformMatrix()
            light_node = path[-1]
            if hasattr(light_node, 'on') and light_node.on:
                # Transform light to eye space
                light_matrix = dot(tmatrix, mode.matrix)
                # Configure light on the vertex color program
                configure_light_from_node(shader_program, light_count, light_node,
                                         light_matrix, program=vc_prog)
                light_count += 1

        if light_count == 0:
            # Set default headlight on vertex color program
            shader_program._set_uniform1i('numLights', 1, vc_prog)
            shader_program._set_uniform1i('lightType[0]', 1, vc_prog)  # directional
            shader_program._set_uniform3f('lightColor[0]', (1.0, 1.0, 1.0), vc_prog)
            shader_program._set_uniform4f('lightPosition[0]', (0.0, 0.0, 1.0, 0.0), vc_prog)
            shader_program._set_uniform3f('lightDirection[0]', (0.0, 0.0, -1.0), vc_prog)
            shader_program._set_uniform3f('lightAttenuation[0]', (1.0, 0.0, 0.0), vc_prog)
            shader_program._set_uniform1f('lightIntensity[0]', 1.0, vc_prog)
            shader_program._set_uniform1f('lightBeamWidth[0]', 1.57, vc_prog)
            shader_program._set_uniform1f('lightCutOffAngle[0]', 0.785, vc_prog)
        else:
            shader_program._set_uniform1i('numLights', light_count, vc_prog)

    def _get_trimming_contours(self):
        """Get trimming contours for this surface.

        Subclasses should override if they have trimming.
        """
        return None

    def _setup_shader_cache_dependencies(self, holder):
        """Set up cache dependencies for shader geometry.

        Subclasses should override to add dependencies on their specific fields.
        When any of these fields change, the cached geometry will be invalidated.

        Args:
            holder: Cache holder from mode.cache.holder()
        """
        # Base class has no fields to depend on - subclasses override
        pass

    def renderProperties(self, nurbObject):
        """Render any properties (such as tessellation)"""
        if self.geometryType == "edge":
            mode = GLU_OUTLINE_PATCH
        elif self.geometryType == "patch":
            mode = GLU_OUTLINE_PATCH
        elif self.geometryType == "polygon":
            mode = GLU_FILL
        else:
            log.warning(
                """%s declares geometryType of %s -> ignoring""",
                self,
                repr(self.geometryType),
            )
            self.geometryType = "polygon"
            mode = GLU_FILL
        gluNurbsProperty(nurbObject, GLU_DISPLAY_MODE, mode)
        self.sampling.properties(nurbObject)

    def renderSurface(self, nurbObject):
        """Render the surface (gluBeginSurface has been called)"""
        return 1

    def renderTrims(self, nurbObject):
        """Render any trims for the surface"""


class NurbsSurface(_SurfaceRenderer, nurbs.NurbsSurface):
    """Surface geometry implemented with gluNurbsSurface
    Notes:
        uOrder/vOrder -- is not currently used, as PyOpenGL
            calculates the order from the difference
            between the knot and control point arrays
        weight -- is not currently used, this is just
            not-yet-implemented, it's quite feasible
            to support it
        uTessellation/vTessellation -- not currently used
        color -- if present, is applied to the knot array
            one for one using another call to gluNurbsSurface
    """

    def _setup_shader_cache_dependencies(self, holder):
        """Set up cache dependencies for NurbsSurface shader geometry.

        Tracks controlPoint, color, uKnot, vKnot fields so that cache is
        invalidated when the surface data changes (e.g., during animation).
        """
        # Depend on all fields that affect tessellation
        for field_name in ('controlPoint', 'color', 'uKnot', 'vKnot',
                           'uDimension', 'vDimension'):
            field_obj = protofunctions.getField(self, field_name)
            if field_obj is not None:
                holder.depend(self, field_obj)

    def _build_shader_geometry_cached(self):
        """Build VBO geometry from GLU tessellation for shader rendering.

        Returns:
            Tuple of (vbo, vertex_count, has_colors) or None if failed.
        """
        try:
            callback = _tessellate_nurbs_surface(
                self,
                trimming_contours=self._get_trimming_contours(),
                sampling=self.sampling,
            )
            shader_vbo, vertex_count, has_colors = _build_nurbs_vbo(callback)
            return (shader_vbo, vertex_count, has_colors)
        except Exception as e:
            log.error("Failed to tessellate NURBS surface: %s", e)
            return None

    def renderSurface(self, nurbObject):
        """Render this surface"""
        ## XXX need to add weights
        # do tessellation configuration here
        controlPoint = arrays.reshape(
            self.controlPoint, (self.vDimension, self.uDimension, 3)
        )
        if self.ccw:
            glFrontFace(GL_CCW)
        else:
            glFrontFace(GL_CW)
        if self.solid:
            glEnable(GL_CULL_FACE)
        else:
            glDisable(GL_CULL_FACE)
        try:
            vKnot = self.vKnot.astype("f")
            uKnot = self.uKnot.astype("f")
            if len(self.color):
                glEnable(GL_COLOR_MATERIAL)
                color = arrays.zeros(
                    (len(self.controlPoint), 4),
                    "f",
                )
                color[:, :3] = self.color.astype("f")
                color = arrays.reshape(
                    color,
                    (self.vDimension, self.uDimension, 4),
                )
                gluNurbsSurface(nurbObject, vKnot, uKnot, color, GL_MAP2_COLOR_4)
            gluNurbsSurface(
                nurbObject,
                vKnot,
                uKnot,
                controlPoint,
                GL_MAP2_VERTEX_3,
            )
        finally:
            glEnable(GL_CULL_FACE)
            glFrontFace(GL_CCW)
        return 1


class TrimmedSurface(_SurfaceRenderer, nurbs.TrimmedSurface):
    """Trimmed surface geometry

    The TrimmedSurface is just a binding of
    a surface to a set of trimming contours.  There
    is nothing particularly complex done by the
    trimmed surface, it simply defers to the surface
    and the trimming contours.
    """

    def _get_trimming_contours(self):
        """Get trimming contours for this surface."""
        return self.trimmingContour if self.trimmingContour else None

    def _setup_shader_cache_dependencies(self, holder):
        """Set up cache dependencies for TrimmedSurface shader geometry.

        Tracks the inner surface's fields so that cache is invalidated
        when the surface data changes (e.g., during animation).
        """
        if self.surface:
            # Depend on inner surface's fields
            for field_name in ('controlPoint', 'color', 'uKnot', 'vKnot',
                               'uDimension', 'vDimension'):
                field_obj = protofunctions.getField(self.surface, field_name)
                if field_obj is not None:
                    holder.depend(self.surface, field_obj)
        # Also depend on our own trimmingContour field
        trim_field = protofunctions.getField(self, 'trimmingContour')
        if trim_field is not None:
            holder.depend(self, trim_field)

    def _build_shader_geometry_cached(self):
        """Build VBO geometry from GLU tessellation for shader rendering.

        Returns:
            Tuple of (vbo, vertex_count, has_colors) or None if failed.
        """
        if not self.surface:
            return None

        # Use surface's sampling if available (it's often set on the inner surface)
        sampling = getattr(self.surface, 'sampling', None) or self.sampling

        try:
            callback = _tessellate_nurbs_surface(
                self.surface,
                trimming_contours=self._get_trimming_contours(),
                sampling=sampling,
            )
            shader_vbo, vertex_count, has_colors = _build_nurbs_vbo(callback)
            return (shader_vbo, vertex_count, has_colors)
        except Exception as e:
            log.error("Failed to tessellate TrimmedSurface: %s", e)
            return None

    def renderProperties(self, nurbObject):
        """Render any properties (such as tessellation)"""
        self.surface.renderProperties(nurbObject)

    def renderSurface(self, nurbObject):
        """Render this surface"""
        if self.surface:
            self.surface.renderSurface(nurbObject)
            return 1
        return 0

    def renderTrims(self, nurbObject):
        """Render any trims for the surface"""
        for trim in self.trimmingContour:
            trim.trim(nurbObject)


class NurbsCurve(nurbs.NurbsCurve):
    """A 3D nurbs curve (a curvy line in 3D space)

    Notes:
        order -- is not currently used, as PyOpenGL
            calculates the order from the difference
            between the knot and control point arrays
        weight -- is not currently used, this is just
            not-yet-implemented, it's quite feasible
            to support it
        tessellation -- not currently used
    """

    def render(
        self,
        visible=1,  # can skip normals and textures if not
        lit=1,  # can skip normals if not
        textured=1,  # can skip textureCoordinates if not
        transparent=0,  # need to sort triangle geometry...
        mode=None,  # the renderpass object
    ):
        """Render the curve as a geometry node"""
        if not len(self.knot) and not len(self.controlPoint):
            return 0
        nurbObject = gluNewNurbsRenderer()
        try:
            gluBeginSurface(nurbObject)
            # do tessellation configuration here
            try:
                # self.renderProperties( nurbObject )
                if len(self.color):
                    color = arrays.zeros((len(self.color), 4), "d")
                    color[:, :3] = self.color
                    gluNurbsCurve(nurbObject, self.knot, color, GL_MAP1_COLOR_4)
                if len(self.weight):
                    points = arrays.zeros(
                        Numeric.shape(self.controlPoint)[:-1] + (4,), "d"
                    )
                    points[:, :3] = self.controlPoint
                    points[:, 3] = self.weight
                    type = GL_MAP1_VERTEX_4
                else:
                    points = self.controlPoint
                    type = GL_MAP1_VERTEX_3
                gluNurbsCurve(nurbObject, self.knot, points, type)
            finally:
                gluEndSurface(nurbObject)
        finally:
            gluDeleteNurbsRenderer(nurbObject)

    def degree(self):
        """Return degree of a nurbs-curve object"""
        return len(self.knot) - len(self.controlPoint) + 1

    def uniform(self):
        """Check that curve is "uniform"

        * all items in knots are increasing
        * starts with degree items the same
        * ends with degree items the same
        * all
        """
        deg = self.degree()
        last = self.knot[0]
        for item in self.knot[1:deg]:
            if item != last:
                return 0, "Doesn't start with degree (%s) equal knots, has %s" % (
                    deg,
                    self.knot[:deg],
                )
        last = self.knot[-1]
        for item in self.knot[-deg:-1]:
            if item != last:
                return 0, "Doesn't end with degree (%s) equal knots, has %s" % (
                    deg,
                    self.knot[-deg:],
                )
        if len(self.knot[deg:-deg]):
            last = self.knot[deg - 1]
            lastCount = deg
            for item in self.knot[deg : -(deg - 1)]:
                if item <= last:
                    return 0, "Knot %s is less than previous knot %s" % (item, last)
                last = item
        return 1, "Uniform"

    def allIncreasing(self):
        """Check that all items in knots are increasing"""
        if not len(self.knot):
            return 1, "No knots defined"
        for i in range(len(self.knot)):
            t = self.knot[i : i + 2]
            if len(t) == 2:
                if t[0] > t[1]:
                    return 0, "Knot %s (%s) is less than knot %s (%s)" % (
                        i + 1,
                        t[1],
                        i,
                        t[0],
                    )
        return 1, "All increasing"


class NurbsSampling(node.Node):
    """A node-type specifying NURBs sampling method and parameters"""


class NurbsToleranceSample(NurbsSampling):
    """Path-length tolerance sampling

    Can be either screen-space or object space,
        method = "screen" -> tolerance in pixels
        method = "object" -> tolerance in object-space coordinates
    and either parametric or not
        if true, tolerance is parametric tolerance (e.g. 0.5)
    """

    method = field.newField("method", "SFString", 1, "screen")  # "screen"/"object"
    parametric = field.newField("parametric", "SFBool", 1, 0)
    tolerance = field.newField("tolerance", "SFFloat", 1, 50.0)

    def properties(self, nurbObject):
        """Configure this sampling type"""
        ### get the appropriate sampling method...
        methods = (GLU_PATH_LENGTH, GLU_PARAMETRIC_ERROR)
        if self.method == "object":
            if not initialise():
                # do regular (non-extension) screen sampling...
                log.warning(
                    """%s declares 'object' sampling method, extension: object_space_tess not available -> ignoring""",
                    self,
                )
                self.method = "screen"
            else:
                methods = (GLU_OBJECT_PATH_LENGTH_EXT, GLU_OBJECT_PARAMETRIC_ERROR_EXT)
        elif self.method != "screen":
            log.warning(
                """%s declares %s sampling method, unknown type -> ignoring""",
                self,
                repr(self.method),
            )
        method = methods[self.parametric]

        gluNurbsProperty(nurbObject, GLU_SAMPLING_METHOD, method)
        if self.parametric:
            gluNurbsProperty(nurbObject, GLU_PARAMETRIC_TOLERANCE, self.tolerance)
        else:
            gluNurbsProperty(nurbObject, GLU_SAMPLING_TOLERANCE, self.tolerance)


class NurbsDomainDistanceSample(NurbsSampling):
    """Domain-distance parametric u and v coordinate sampling"""

    uStep = field.newField("uStep", "SFFloat", 1, 100.0)
    vStep = field.newField("vStep", "SFFloat", 1, 100.0)

    def properties(self, nurbObject):
        """Configure this sampling type"""
        gluNurbsProperty(nurbObject, GLU_SAMPLING_METHOD, GLU_DOMAIN_DISTANCE)
        gluNurbsProperty(nurbObject, GLU_U_STEP, self.uStep)
        gluNurbsProperty(nurbObject, GLU_V_STEP, self.vStep)
