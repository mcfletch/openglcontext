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

This module holds the surface/curve geometry nodes. Supporting concerns live in
sibling modules, re-exported below so ``nurbs.X`` resolves:

* :mod:`nurbssampling` -- sampling nodes + object-space-tess probe
* :mod:`nurbstrim` -- 2D trim primitives
* :mod:`nurbstess` -- the GLU-callback tessellation-to-VBO service
"""

from vrml.vrml97 import nurbs, nodetypes
from vrml import node, field, fieldtypes, protofunctions
from OpenGL.GLU import *
from OpenGL.GL import *
import logging

log = logging.getLogger(__name__)
from OpenGLContext import arrays
from OpenGLContext.scenegraph.shadergeometry import _get_or_build_vao

# Re-exported so importers / node registrations that reference nurbs.X keep
# working after the split (see module docstring).
from OpenGLContext.scenegraph.nurbssampling import (
    NurbsSampling,
    NurbsToleranceSample,
    NurbsDomainDistanceSample,
    defaultSampling,
    initialise,
)
from OpenGLContext.scenegraph.nurbstrim import Polyline2D, NurbsCurve2D, Contour2D
from OpenGLContext.scenegraph.nurbstess import (
    NURBSTessellatorCallback,
    _get_tess_callback,
    _tessellate_nurbs_surface,
    _build_nurbs_vbo,
)


# Distance-LOD GLU domain-distance step per level. Level 0 is None -> keep the
# node's own ``sampling`` (unchanged close-up look); coarser levels override with
# progressively fewer steps so a far-off surface tessellates far more cheaply.
NURBS_LOD_STEPS = (None, 16.0, 8.0, 4.0)


def nurbs_lod_steps(level):
    return NURBS_LOD_STEPS[min(level, len(NURBS_LOD_STEPS) - 1)]


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
        # Build/update the VBO if needed - use mode.cache to store per-context,
        # one entry per distance-LOD level so a far-off surface reuses a coarse
        # tessellation instead of the full one (level 0 keeps the node's sampling).
        level = self._lod_level(mode)
        cache_key = 'nurbs_shader_data_lod%d' % level
        cached = mode.cache.getData(self, key=cache_key)
        if cached is None:
            cached = self._build_shader_geometry_cached(steps=nurbs_lod_steps(level))
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

        # Interleaved layout: with colours it's color(4)+normal(3)+vertex(3);
        # without, normal(3)+vertex(3). Attribute locations match the VRML97
        # shaders: 1=aNormal, 2=aPosition, 3=aColor.
        from ctypes import c_void_p
        if has_colors:
            stride, color_offset, normal_offset, vertex_offset = 40, 0, 16, 28
        else:
            stride, color_offset, normal_offset, vertex_offset = 24, None, 0, 12

        # Cache the VAO on the node keyed by program + VBO identity:
        # the VBO is already cached per LOD level, so only the per-frame VAO
        # gen/delete + attribute re-binding remained. A tessellation change makes
        # a new VBO, which rebuilds the VAO.
        program = vc_prog if has_colors else shader_program.program

        def _bind_attributes():
            shader_vbo.bind()
            glEnableVertexAttribArray(2)
            glVertexAttribPointer(2, 3, GL_FLOAT, GL_FALSE, stride, c_void_p(vertex_offset))
            glEnableVertexAttribArray(1)
            glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, c_void_p(normal_offset))
            if has_colors and color_offset is not None:
                glEnableVertexAttribArray(3)
                glVertexAttribPointer(3, 4, GL_FLOAT, GL_FALSE, stride, c_void_p(color_offset))
            shader_vbo.unbind()

        try:
            vao = _get_or_build_vao(self, program, (shader_vbo,), _bind_attributes)
            if vao is not None:
                glBindVertexArray(vao)
                try:
                    glDrawArrays(GL_TRIANGLES, 0, vertex_count)
                finally:
                    glBindVertexArray(0)
            else:
                # Owner can't hold a cache -> transient VAO (rare fallback).
                transient = glGenVertexArrays(1)
                glBindVertexArray(transient)
                try:
                    _bind_attributes()
                    glDrawArrays(GL_TRIANGLES, 0, vertex_count)
                finally:
                    glBindVertexArray(0)
                    glDeleteVertexArrays(1, [transient])
        finally:
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

    def _build_shader_geometry_cached(self, steps=None):
        """Build VBO geometry from GLU tessellation.

        Args:
            steps: Optional GLU domain-distance step override (distance-LOD).

        Returns:
            Tuple of (vbo, vertex_count, has_colors) or None if not supported/failed.

        Subclasses should override to provide surface-specific data.
        """
        # Base class returns None - subclasses override with actual implementation
        return None  # type: ignore[return-value]

    # -- distance level-of-detail -----------------------------------------
    def _lod_bounding_sphere(self):
        """(center, radius) of this surface in local space, or None (subclass hook)."""
        return None

    def _lod_level(self, mode):
        """Distance-LOD level (0 = finest) for this surface this frame."""
        from OpenGLContext.scenegraph import tessellationlod
        sphere = self._lod_bounding_sphere()
        if sphere is None:
            return 0
        center, radius = sphere
        return tessellationlod.lod_level(mode, center, radius)

    @staticmethod
    def _control_point_sphere(control_point):
        """Local bounding sphere (center, radius) from a control-point array."""
        try:
            cp = arrays.reshape(arrays.array(control_point, 'd'), (-1, 3))
        except Exception:
            return None
        if not len(cp):
            return None
        lo = cp.min(0)
        hi = cp.max(0)
        center = tuple(float(v) for v in (lo + hi) * 0.5)
        radius = 0.5 * float((((hi - lo) ** 2).sum()) ** 0.5)
        return center, (radius or 1.0)

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

    def _lod_bounding_sphere(self):
        return self._control_point_sphere(self.controlPoint)

    def _build_shader_geometry_cached(self, steps=None):
        """Build VBO geometry from GLU tessellation for shader rendering.

        Returns:
            Tuple of (vbo, vertex_count, has_colors) or None if failed.
        """
        try:
            callback = _tessellate_nurbs_surface(
                self,
                trimming_contours=self._get_trimming_contours(),
                sampling=self.sampling,
                u_step=steps, v_step=steps,
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

    def _lod_bounding_sphere(self):
        if not self.surface:
            return None
        return self._control_point_sphere(self.surface.controlPoint)

    def _build_shader_geometry_cached(self, steps=None):
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
                u_step=steps, v_step=steps,
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
