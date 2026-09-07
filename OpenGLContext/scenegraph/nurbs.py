"""Nurbs-rendering nodes based on VRML97 Nurbs extension

NurbsSurface is a geometry object, drop it
into a shape to see the objects in a scene.

A surface is evaluated to triangles by
:mod:`OpenGLContext.scenegraph.nurbstess` -- control points, knots, weights and
trimming contours in, positions, normals, texture coordinates, colours and
indices out -- and the same triangles are drawn under both profiles: through a
vertex buffer and the pass's shader in core, through the fixed-function pipeline
in compatibility. Tessellation itself touches no GL, so a surface can be
evaluated before there is a context to draw it in.

This module holds the surface/curve geometry nodes. Supporting concerns live in
sibling modules, re-exported below so ``nurbs.X`` resolves:

* :mod:`nurbssampling` -- how finely a surface is sampled
* :mod:`nurbstrim` -- 2D trim primitives
* :mod:`nurbstess` -- the evaluator that turns a surface into triangles
"""

import logging
from ctypes import c_void_p

import numpy as np
from opengl_extrusions.nurbs import NurbsError, curve_points
from vrml.vrml97 import nurbs, nodetypes
from vrml import field, protofunctions

from OpenGL.GL import *
from OpenGL.arrays import vbo

log = logging.getLogger(__name__)
from OpenGLContext import arrays
from OpenGLContext.scenegraph.shadergeometry import (
    get_or_build_vao, SHARED_LAYOUT,
)
from OpenGLContext.scenegraph.vertexsemantics import (
    LOC_POSITION, LOC_NORMAL, LOC_COLOR,
)

# Re-exported so importers / node registrations that reference nurbs.X keep
# working after the split (see module docstring).
from OpenGLContext.scenegraph.nurbssampling import (
    NurbsSampling,
    NurbsToleranceSample,
    NurbsDomainDistanceSample,
    defaultSampling,
)
from OpenGLContext.scenegraph.nurbstrim import Polyline2D, NurbsCurve2D, Contour2D
from OpenGLContext.scenegraph.nurbstess import (
    COLOR_NORMAL_POSITION_STRIDE,
    NORMAL_POSITION_STRIDE,
    SurfaceTessellation,
    build_surface_vbo,
    tessellate_surface,
)


# Distance-LOD sampling rate per level. Level 0 is None -> keep the node's own
# ``sampling`` (unchanged close-up look); coarser levels override with
# progressively fewer intervals so a far-off surface tessellates far more cheaply.
NURBS_LOD_STEPS = (None, 16.0, 8.0, 4.0)

# Where each attribute sits in the interleaved vertex, by whether the surface
# carries colours: (stride, colour offset, normal offset, position offset).
INTERLEAVED_WITH_COLOR = (COLOR_NORMAL_POSITION_STRIDE, 0, 16, 28)
INTERLEAVED_PLAIN = (NORMAL_POSITION_STRIDE, None, 0, 12)

#: Points evaluated along a 3D :class:`NurbsCurve` when it names no
#: ``tessellation`` of its own.
CURVE_STEPS = 64


def nurbs_lod_steps(level):
    return NURBS_LOD_STEPS[min(level, len(NURBS_LOD_STEPS) - 1)]


def interleaved_layout(has_colors):
    """``(stride, color_offset, normal_offset, vertex_offset)`` in bytes."""
    return INTERLEAVED_WITH_COLOR if has_colors else INTERLEAVED_PLAIN


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

    def render(
        self,
        visible=1,  # can skip normals and textures if not
        lit=1,  # can skip normals if not
        textured=1,  # can skip textureCoordinates if not
        transparent=0,  # need to sort triangle geometry...
        mode=None,  # the renderpass object
    ):
        """Render the surface, tessellated to triangles"""
        cached = self._cached_geometry(mode)
        if cached is None:
            return 0
        vertices, indices, count, has_colors = cached
        if vertices is None or not count:
            return 0
        if mode is not None and getattr(mode, 'shader_mode', False):
            return self._render_shader(mode, vertices, indices, count, has_colors)
        return self._render_legacy(vertices, indices, count, has_colors, lit)

    # -- the tessellation, built once per LOD level and cached ---------------
    def _cached_geometry(self, mode):
        """The surface's buffers for this frame, from the pass's cache.

        One entry per distance-LOD level, so a far-off surface reuses a coarse
        tessellation instead of the full one (level 0 keeps the node's sampling).
        Without a pass to cache in -- a caller drawing the node directly -- the
        buffers are built each time.
        """
        if mode is None or getattr(mode, 'cache', None) is None:
            return self._build_geometry()
        level = self._lod_level(mode)
        cache_key = 'nurbs_geometry_lod%d' % level
        cached = mode.cache.getData(self, key=cache_key)
        if cached is None:
            cached = self._build_geometry(steps=nurbs_lod_steps(level))
            if cached is not None:
                holder = mode.cache.holder(self, cached, key=cache_key)
                self._setup_shader_cache_dependencies(holder)
        return cached

    def _build_geometry(self, steps=None):
        """Tessellate and upload, as ``(vertices, indices, count, has_colors)``.

        ``steps`` is a sampling rate override (distance-LOD); ``None`` keeps the
        node's own sampling.
        """
        try:
            tessellation = self._tessellate(steps=steps)
        except (NurbsError, ValueError) as err:
            log.error("Cannot tessellate %s: %s", self, err)
            return None
        if tessellation is None:
            return None
        return build_surface_vbo(tessellation)

    def _tessellate(self, steps=None):
        """The surface's triangles (subclass hook)."""
        return None

    # -- drawing -------------------------------------------------------------
    def _render_shader(self, mode, vertices, indices, count, has_colors):
        """Draw the tessellation with the pass's shader program."""
        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None:
            return 0

        # With per-vertex colours the pass's lit program has no diffuse input to
        # read them through, so the vertex-colour program draws instead and the
        # lit one is put back afterwards.
        switched_shader = False
        vc_prog = None
        if has_colors:
            shader_program.use_vertex_color()
            switched_shader = True
            vc_prog = shader_program.vertex_color_program
            # mode.matrix carries the accumulated transforms; getModelView() does not.
            shader_program.set_matrices(mode.matrix, mode.getProjection(), vc_prog)
            # What the vertex-colour program still takes from the material: the
            # diffuse term is the vertex colour, the rest is not.
            shader_program._set_uniform3f('specularColor', (0.0, 0.0, 0.0), vc_prog)
            shader_program._set_uniform3f('emissiveColor', (0.0, 0.0, 0.0), vc_prog)
            shader_program._set_uniform1f('ambientIntensity', 0.2, vc_prog)
            shader_program._set_uniform1f('shininess', 0.2, vc_prog)
            shader_program._set_uniform1f('transparency', 0.0, vc_prog)
            shader_program._set_uniform3f('sceneAmbient', (0.2, 0.2, 0.2), vc_prog)
            self._setup_vertex_color_lights(mode, shader_program, vc_prog)

        stride, color_offset, normal_offset, vertex_offset = interleaved_layout(
            has_colors)
        program = vc_prog if has_colors else shader_program.program

        # The VAO is cached beside the buffers it describes: a tessellation
        # change makes new buffers, which rebuilds the VAO, and so does a change
        # of whether the surface carries colours, since that is what the
        # interleaved stride depends on.
        def _bind_attributes():
            vertices.bind()
            glEnableVertexAttribArray(LOC_POSITION)
            glVertexAttribPointer(LOC_POSITION, 3, GL_FLOAT, GL_FALSE, stride,
                                  c_void_p(vertex_offset))
            glEnableVertexAttribArray(LOC_NORMAL)
            glVertexAttribPointer(LOC_NORMAL, 3, GL_FLOAT, GL_FALSE, stride,
                                  c_void_p(normal_offset))
            if has_colors and color_offset is not None:
                glEnableVertexAttribArray(LOC_COLOR)
                glVertexAttribPointer(LOC_COLOR, 4, GL_FLOAT, GL_FALSE, stride,
                                      c_void_p(color_offset))
            # The element buffer belongs to the VAO too, so it stays bound.
            indices.bind()

        try:
            vao = get_or_build_vao(
                self, program, (vertices, indices, bool(has_colors)),
                _bind_attributes, layout_key=SHARED_LAYOUT)
            if vao is not None:
                glBindVertexArray(vao)
                try:
                    glDrawElements(GL_TRIANGLES, count, GL_UNSIGNED_INT, None)
                finally:
                    glBindVertexArray(0)
            else:
                # Owner can't hold a cache -> transient VAO (rare fallback).
                transient = glGenVertexArrays(1)
                glBindVertexArray(transient)
                try:
                    _bind_attributes()
                    glDrawElements(GL_TRIANGLES, count, GL_UNSIGNED_INT, None)
                finally:
                    glBindVertexArray(0)
                    glDeleteVertexArrays(1, [transient])
        finally:
            if switched_shader:
                shader_program.use(lit=True, vertex_colors=False)
                shader_program.set_matrices(
                    mode.matrix, mode.getProjection(), shader_program.program)
        return 1

    def _render_legacy(self, vertices, indices, count, has_colors, lit=1):
        """Draw the tessellation through the fixed-function pipeline."""
        stride, color_offset, normal_offset, vertex_offset = interleaved_layout(
            has_colors)
        fill = self._fill_mode()
        if fill != GL_FILL:
            glPolygonMode(GL_FRONT_AND_BACK, fill)
        vertices.bind()
        indices.bind()
        try:
            glEnableClientState(GL_VERTEX_ARRAY)
            glVertexPointer(3, GL_FLOAT, stride, vertices + vertex_offset)
            if lit:
                glEnableClientState(GL_NORMAL_ARRAY)
                glNormalPointer(GL_FLOAT, stride, vertices + normal_offset)
            if has_colors and color_offset is not None:
                glEnable(GL_COLOR_MATERIAL)
                glEnableClientState(GL_COLOR_ARRAY)
                glColorPointer(4, GL_FLOAT, stride, vertices + color_offset)
            self._apply_face_state()
            try:
                glDrawElements(GL_TRIANGLES, count, GL_UNSIGNED_INT, indices)
            finally:
                glEnable(GL_CULL_FACE)
                glFrontFace(GL_CCW)
        finally:
            glDisableClientState(GL_VERTEX_ARRAY)
            if lit:
                glDisableClientState(GL_NORMAL_ARRAY)
            if has_colors:
                glDisableClientState(GL_COLOR_ARRAY)
                glDisable(GL_COLOR_MATERIAL)
            indices.unbind()
            vertices.unbind()
            if fill != GL_FILL:
                glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
        return 1

    def _fill_mode(self):
        """``GL_FILL`` or ``GL_LINE``, from ``geometryType``."""
        if self.geometryType in ("edge", "patch"):
            return GL_LINE
        if self.geometryType != "polygon":
            log.warning(
                """%s declares geometryType of %s -> ignoring""",
                self,
                repr(self.geometryType),
            )
            self.geometryType = "polygon"
        return GL_FILL

    def _apply_face_state(self):
        """Winding and culling, from the surface's ``ccw`` and ``solid`` fields."""
        surface = self._face_source()
        if surface is None:
            return
        glFrontFace(GL_CCW if surface.ccw else GL_CW)
        if surface.solid:
            glEnable(GL_CULL_FACE)
        else:
            glDisable(GL_CULL_FACE)

    def _face_source(self):
        """The node whose ``ccw``/``solid`` fields describe these faces."""
        return self

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


#: The fields a surface's tessellation is built from: change any of them and the
#: cached geometry no longer describes the node.
TESSELLATION_FIELDS = (
    'controlPoint', 'color', 'weight', 'uKnot', 'vKnot', 'uDimension', 'vDimension',
)


class NurbsSurface(_SurfaceRenderer, nurbs.NurbsSurface):
    """Surface geometry evaluated from its control net and knot vectors

    Notes:
        uOrder/vOrder -- is not used; the degree follows from the difference
            between the knot and control point counts, which is where a
            mismatch between the two would show up
        uTessellation/vTessellation -- not currently used; ``sampling`` says how
            finely the surface is sampled
        color -- if present, one colour per control point, evaluated through the
            same basis as the surface so it follows its control point across the
            tessellation
        weight -- if present, one positive weight per control point: the
            *rational* in NURBS, and what lets a NURBS circle be a circle
    """

    def _setup_shader_cache_dependencies(self, holder):
        """Invalidate the tessellation when the surface data changes."""
        for field_name in TESSELLATION_FIELDS:
            field_obj = protofunctions.getField(self, field_name)
            if field_obj is not None:
                holder.depend(self, field_obj)

    def _lod_bounding_sphere(self):
        return self._control_point_sphere(self.controlPoint)

    def _tessellate(self, steps=None):
        return tessellate_surface(
            self,
            trimming_contours=self._get_trimming_contours(),
            sampling=self.sampling,
            u_step=steps, v_step=steps,
        )


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
        """Invalidate the tessellation when the surface or its trims change."""
        if self.surface:
            for field_name in TESSELLATION_FIELDS:
                field_obj = protofunctions.getField(self.surface, field_name)
                if field_obj is not None:
                    holder.depend(self.surface, field_obj)
        trim_field = protofunctions.getField(self, 'trimmingContour')
        if trim_field is not None:
            holder.depend(self, trim_field)

    def _lod_bounding_sphere(self):
        if not self.surface:
            return None
        return self._control_point_sphere(self.surface.controlPoint)

    def _face_source(self):
        return self.surface or None

    def _tessellate(self, steps=None):
        if not self.surface:
            return None
        # The sampling is usually set on the inner surface rather than here.
        sampling = getattr(self.surface, 'sampling', None) or self.sampling
        return tessellate_surface(
            self.surface,
            trimming_contours=self._get_trimming_contours(),
            sampling=sampling,
            u_step=steps, v_step=steps,
        )


class NurbsCurve(nurbs.NurbsCurve):
    """A 3D nurbs curve (a curvy line in 3D space)

    The curve is evaluated to a polyline and drawn as a line strip, so it draws
    under both profiles.

    Notes:
        order -- is not used; the degree follows from the difference between the
            knot and control point counts
        tessellation -- how many points to evaluate the curve at; left at 0 it
            takes :data:`CURVE_STEPS`
        color -- if present, one colour per control point, carried along the
            curve by the same basis
        weight -- if present, one positive weight per control point
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
        cached = self._cached_points(mode)
        if cached is None:
            return 0
        points, colors = cached
        if len(points) < 2:
            return 0
        if mode is not None and getattr(mode, 'shader_mode', False):
            return self._render_shader(mode, points, colors)
        return self._render_legacy(points, colors)

    def _cached_points(self, mode):
        """``(points, colors)`` for this curve, from the pass's cache."""
        if mode is None or getattr(mode, 'cache', None) is None:
            return self._evaluate()
        cached = mode.cache.getData(self, key='nurbs_curve_points')
        if cached is None:
            cached = self._evaluate()
            if cached is not None:
                holder = mode.cache.holder(self, cached, key='nurbs_curve_points')
                for field_name in ('controlPoint', 'knot', 'color', 'weight',
                                   'tessellation'):
                    field_obj = protofunctions.getField(self, field_name)
                    if field_obj is not None:
                        holder.depend(self, field_obj)
        return cached

    def _evaluate(self):
        """Points along the curve, and a colour each where the node gives them.

        ``None`` where the node does not describe a curve; the colours are
        ``None`` where it carries none.
        """
        control = np.asarray(self.controlPoint, dtype=np.float64).reshape(-1, 3)
        knot = np.asarray(self.knot, dtype=np.float64).ravel()
        if len(control) < 2 or len(knot) < 2:
            return None
        degree = len(knot) - len(control) - 1
        if degree < 1:
            log.error(
                "%s has a knot vector of %d over %d control points"
                " -> no curve to draw", self, len(knot), len(control))
            return None
        count = max(2, int(self.tessellation) or CURVE_STEPS)
        ts = np.linspace(knot[degree], knot[len(control)], count)
        weight = np.asarray(self.weight, dtype=np.float64).ravel()
        weights = weight if weight.size == len(control) else None
        try:
            points = curve_points(control, knot, degree, ts, weights=weights)
            colors = None
            color = np.asarray(self.color, dtype=np.float64).reshape(-1, 3)
            if len(color) == len(control):
                colors = curve_points(color, knot, degree, ts)
        except (NurbsError, ValueError) as err:
            log.error("Cannot evaluate %s: %s", self, err)
            return None
        return points.astype(np.float32), (
            None if colors is None else colors.astype(np.float32))

    def _render_legacy(self, points, colors):
        """Draw the polyline through the fixed-function pipeline."""
        glEnableClientState(GL_VERTEX_ARRAY)
        glVertexPointerf(points)
        if colors is not None:
            glEnable(GL_COLOR_MATERIAL)
            glEnableClientState(GL_COLOR_ARRAY)
            glColorPointerf(colors)
        try:
            glDrawArrays(GL_LINE_STRIP, 0, len(points))
        finally:
            glDisableClientState(GL_VERTEX_ARRAY)
            if colors is not None:
                glDisableClientState(GL_COLOR_ARRAY)
                glDisable(GL_COLOR_MATERIAL)
        return 1

    def _render_shader(self, mode, points, colors):
        """Draw the polyline with the pass's line or unlit program."""
        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None:
            return 0
        has_colors = colors is not None
        if has_colors:
            shader_program.use_line()
            program = shader_program.line_program
        else:
            shader_program.use(lit=False)
            program = shader_program.unlit_program
            shader_program.set_solid_color(
                getattr(mode, '_solid_color', None) or (1.0, 1.0, 1.0, 1.0))
        shader_program.set_matrices(mode.matrix, mode.getProjection(), program=program)

        if has_colors:
            interleaved = np.hstack([points, colors]).astype(np.float32)
            stride = 24
        else:
            interleaved = np.ascontiguousarray(points, dtype=np.float32)
            stride = 12
        curve_vbo = self._curve_vbo(interleaved)

        def _bind_attributes():
            curve_vbo.bind()
            glEnableVertexAttribArray(LOC_POSITION)
            glVertexAttribPointer(LOC_POSITION, 3, GL_FLOAT, GL_FALSE, stride, None)
            if has_colors:
                glEnableVertexAttribArray(LOC_COLOR)
                glVertexAttribPointer(LOC_COLOR, 3, GL_FLOAT, GL_FALSE, stride,
                                      c_void_p(12))
            curve_vbo.unbind()

        try:
            vao = get_or_build_vao(
                self, program, (curve_vbo, has_colors), _bind_attributes,
                layout_key=SHARED_LAYOUT)
            if vao is not None:
                glBindVertexArray(vao)
                try:
                    glDrawArrays(GL_LINE_STRIP, 0, len(points))
                finally:
                    glBindVertexArray(0)
            else:
                transient = glGenVertexArrays(1)
                glBindVertexArray(transient)
                try:
                    _bind_attributes()
                    glDrawArrays(GL_LINE_STRIP, 0, len(points))
                finally:
                    glBindVertexArray(0)
                    glDeleteVertexArrays(1, [transient])
        finally:
            shader_program.use(lit=True)
        return 1

    def _curve_vbo(self, interleaved):
        """The curve's vertex buffer, re-uploaded only when its points change."""
        held = getattr(self, '_curve_gpu', None)
        if held is None or held.data.shape != interleaved.shape:
            held = vbo.VBO(interleaved)
            try:
                self._curve_gpu = held
            except (AttributeError, TypeError):
                pass          # a node that cannot hold one uploads each frame
        elif not np.array_equal(held.data, interleaved):
            held.set_array(interleaved)
        return held

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
