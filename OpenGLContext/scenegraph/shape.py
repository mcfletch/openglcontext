"""Renderable geometry composed of a geometry object with applied appearance"""

import contextlib
from collections.abc import Iterator
from typing import Any, Optional

from OpenGL import GL
from OpenGL.GL import *
from OpenGL.GL import GL_BACK, GL_FRONT, glUseProgram
from vrml.vrml97 import basenodes
from vrml import field
from OpenGLContext import lighting
from OpenGLContext.scenegraph import boundingvolume, drawproperties, polygonsort, rendermodes, texgen
from OpenGLContext.scenegraph.physicalmaterial import two_sided
from OpenGLContext.scenegraph.texturelayers import is_layered, texture_layers
from OpenGLContext.arrays import array
import traceback
import logging

log = logging.getLogger(__name__)
LOCAL_ORIGIN = array([[0, 0, 0, 1.0]], "f")


class Shape(basenodes.Shape):
    """Defines renderable objects by binding Appearance to a geometry node

    The Shape node defines a renderable geometric object. Basically
    it is a binding of a particular geometry node to a particular
    appearance node.  The Shape node coordinates the rendering of
    the appearance and geometry such that the appearance is applied
    only to the appropriate geometry.

    Attributes of note within the Shape object:

        geometry -- pointer to the geometry object, often an
            arraygeometry object, although potentially a Nurb object,
            or similar geometric primitive.

        appearance -- pointer to the appearance object.  This must
            be an actual Appearance object or None to the default
            appearance.

    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Shape
    """

    # "Transparent to clicking": when False, the shape writes nothing to the MRT
    # object-id attachment, so a pick reads through to whatever is behind it (an
    # axis gizmo, an annotation, a water surface). It still renders normally to
    # the colour buffer. Default True keeps every existing shape pickable.
    pickable = field.newField('pickable', 'SFBool', 1, True)

    # X3D's `castShadow`: whether this shape is drawn into the shadow maps.
    # Clear it for geometry that costs more to rasterise into every cascade
    # than its shadow is worth -- dense alpha foliage -- and for geometry that
    # stands in for something that is not there, like a sky drawn as a
    # backdrop. The shape rather than the geometry, because a shadow caster is
    # a renderable and the geometry under one may be shared with a shape that
    # does cast. The field is the X3D declaration's.
    #: Another name for `castShadow`, which engine code uses
    castsShadow = field.AliasField('castsShadow', 'castShadow')

    def publishProperties(self, mode: Any) -> None:
        """Give `mode` the appearance's X3D line, point and fill properties

        Read by the geometry that draws lines, points or polygons, which does
        not see the appearance (:mod:`~OpenGLContext.scenegraph.drawproperties`).
        """
        mode._lineProperties = getattr(self.appearance, 'lineProperties', None)
        mode._pointProperties = getattr(self.appearance, 'pointProperties', None)
        mode._fillProperties = getattr(self.appearance, 'fillProperties', None)
        # The geometry a 3D texture spans in the compatibility profile
        mode._texturedGeometry = self.geometry

    def fillStyle(self) -> drawproperties.FillStyle:
        """The appearance's FillProperties as drawn; the default for a
        geometry of lines or points, which it does not apply to"""
        if getattr(type(self.geometry), 'meshArrays', None) is None:
            return drawproperties.FillStyle()
        return drawproperties.fill_style(getattr(self.appearance, 'fillProperties', None))

    def _renderFilledFixed(self, lit: Any, textured: Any, mode: Any) -> None:
        """Draw the geometry by the fixed-function state, or by the X3D shader that reads it

        In the compatibility profile an appearance's X3D shader of GLSL 1.x
        runs as written, its built-ins reading the material, lights,
        matrices and arrays this pass has set (:mod:`~OpenGLContext.scenegraph.x3dshaders`).
        """
        drawn = None
        if getattr(self.appearance, 'shaders', None):
            drawn = self.appearance.drawProgram(mode, self)
        try:
            self.geometry.render(lit=lit, textured=textured, mode=mode)
        finally:
            if drawn is not None:
                self.appearance.releaseProgram(drawn, mode)
                glUseProgram(0)

    def _renderHatchFixed(self, fill: drawproperties.FillStyle, mode: Any) -> None:
        """Draw the geometry again through `fill`'s hatch, as a polygon stipple"""
        glPushAttrib(GL_ENABLE_BIT | GL_POLYGON_STIPPLE_BIT | GL_CURRENT_BIT
                     | GL_DEPTH_BUFFER_BIT)
        try:
            glDisable(GL_LIGHTING)
            glDisable(GL_TEXTURE_2D)
            glEnable(GL_POLYGON_STIPPLE)
            glPolygonStipple(drawproperties.hatch_stipple(fill))
            glDepthFunc(GL_LEQUAL)
            glColor3f(*fill.color)
            self.geometry.render(lit=0, textured=0, mode=mode)
        finally:
            glPopAttrib()

    def Render(self, mode: Any = None) -> Any:
        """Do run-time rendering of the Shape for the given mode"""
        if not self.geometry:
            return
        self.publishProperties(mode)

        # Use shader-based rendering if mode is in shader mode
        if getattr(mode, 'shader_mode', False):
            return self._render_shader(mode)

        # Legacy rendering path
        if mode.visible:  # anything else...
            glPushAttrib(GL_LIGHTING_BIT)
            try:
                if self.appearance:
                    lit, textured, alpha, textureToken = self.appearance.render(
                        mode=mode
                    )
                    if alpha < 1.0:  # is currently somewhat transparent
                        if not mode.transparent:
                            mode.addTransparent(self)
                        if textured:
                            # undo the texture setup (since we won't render anything just now)
                            self.appearance.renderPost(textureToken, mode=mode)
                        return
                else:
                    lit = 0
                    textured = 0
                    glColor3f(1, 1, 1)
                if lit and mode.lighting:
                    glEnable(GL_LIGHTING)
                else:
                    glDisable(GL_LIGHTING)
                fill = self.fillStyle()
                generated = texgen.fixed_function(getattr(self.geometry, 'texGen', None)) \
                    if textured else None
                if fill.filled:
                    with _fixed_texgen(generated):
                        self._renderFilledFixed(lit, textured, mode)
                if textured:
                    self.appearance.renderPost(textureToken, mode=mode)
                if fill.hatch:
                    self._renderHatchFixed(fill, mode)
            finally:
                glPopAttrib()
        else:
            # by default, just render using the mode's settings
            # (this is only called if visible false, BTW)
            self.geometry.render(
                lit=mode.lighting,
                textured=mode.visible,
                visible=mode.visible,
                mode=mode,
            )

    def _render_shader(self, mode: Any) -> Any:
        """Render using shader-based pipeline.

        Sets up material and texture uniforms on the shader, then
        calls geometry's render method (which will use shader path).
        """
        from OpenGLContext.passes.shaderpass import appearance_solid_color

        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None:
            return

        # Shadow depth pass: only positions matter, skip appearance/material/texture.
        # Matrices and program are configured by the shadow pass itself.
        if getattr(mode, 'shadow_pass', False):
            depth = getattr(self.geometry, 'depthDraw', None)
            if depth is None or not depth(mode):
                self.geometry.render(textured=False, mode=mode)
            return

        # The one colour geometry with no material of its own is drawn in --
        # a line, a point cloud. Published here because the appearance belongs
        # to the shape and the geometry node does not see it.
        mode._solid_color = appearance_solid_color(self.appearance,
                                                   lighting.x3d_lit(self.geometry))
        if hasattr(shader_program, 'set_fill_style'):
            shader_program.set_fill_style(self.fillStyle())

        if self.appearance and getattr(self.appearance, 'bringsProgram', False):
            if not getattr(mode, 'visible', True):
                # Selection paints every shape in its own id colour with the
                # pass's own program; the appearance's would paint its own.
                return self.geometry.render(textured=False, mode=mode)
            if self._render_shader_appearance(mode):
                return None
            # No program of its own runs: drawn with its material and texture.

        if getattr(mode, 'visible', True) and rendermodes.has_modes(self.appearance):
            # X_ITE's BlendMode and DepthMode: the appearance's own state
            # around the draw.
            with rendermodes.applied(self.appearance):
                return self._render_shader_drawn(mode, shader_program)
        return self._render_shader_drawn(mode, shader_program)

    def _render_shader_drawn(self, mode: Any, shader_program: Any) -> Any:
        """Draw the geometry with the appearance's material through `shader_program`"""
        from OpenGLContext.passes.shaderpass import (  # noqa: PLC0415 shaderpass imports the scenegraph
            configure_material_from_node,
        )
        # PBR program: it configures its own material + texture maps (and
        # up-converts VRML97 Material), then we just render the geometry.
        if getattr(mode, 'visible', True) and hasattr(shader_program, 'configure_appearance'):
            if two_sided(self.appearance) and not getattr(self.geometry, 'solid', True):
                # The front faces with the material, then the back faces with
                # the back material, each side culling the other.
                try:
                    mode.drawnFaces = GL_FRONT
                    self._render_pbr(mode, shader_program, back=False)
                    mode.drawnFaces = GL_BACK
                    self._render_pbr(mode, shader_program, back=True)
                finally:
                    mode.drawnFaces = None
                return
            self._render_pbr(mode, shader_program, back=False)
            return

        # Skip material/texture setup during selection rendering (mode.visible=False)
        # Selection uses solid colors with unlit shader, not materials
        textured = False
        if getattr(mode, 'visible', True):
            # Set up material properties
            if self.appearance and self.appearance.material:
                configure_material_from_node(shader_program, self.appearance.material)
            elif lighting.x3d_lit(self.geometry):
                shader_program.set_unlit_material()
            else:
                shader_program.set_default_material()

            # A MultiTexture, a cube map or a 3D texture is a chain of layers
            # in place of the texture.
            layered = self.appearance and is_layered(self.appearance.texture)
            if hasattr(shader_program, 'set_texture_layers'):
                shader_program.set_texture_layers(
                    texture_layers(self.appearance, self.geometry) if layered else None,
                    mode, self.geometry)
            # Set up texture if present
            if self.appearance and self.appearance.texture and not layered:
                tex = self.appearance.texture.cached(mode)
                if tex is not None:
                    shader_program.bind_texture(tex)
                    textured = True
                    # Store texture ID in mode for geometry nodes that need direct access
                    mode._bound_texture_id = tex.texture
                    # Apply texture transform if present
                    if self.appearance.textureTransform:
                        shader_program.set_texture_transform(self.appearance.textureTransform)
                    else:
                        shader_program.set_default_texture_transform()

            if not textured:
                shader_program.set_texture_enabled(False)
                mode._bound_texture_id = None
            # One uniform for the pass: a mesh with colours sets it for its own
            # draw, and every other shape is drawn with its material's colour.
            if hasattr(shader_program, 'set_vertex_color'):
                shader_program.set_vertex_color(False)

        # Render the geometry (it will detect shader_mode and use shader path)
        self.geometry.render(textured=textured, mode=mode)

        # Cleanup texture
        if textured:
            shader_program.unbind_texture()

    def _render_pbr(self, mode: Any, shader_program: Any, back: bool) -> None:
        """Draw through the PBR program with the front or back faces' material"""
        if back:
            shader_program.configure_appearance(self.appearance, mode, self.geometry, back=True)
        else:
            shader_program.configure_appearance(self.appearance, mode, self.geometry)
        # Whether the base colour is modulated by a per-vertex colour is one
        # uniform for the whole pass, so it is answered for every shape
        # rather than only by the geometry that has colours: a box drawn
        # after a vertex-coloured terrain would otherwise be modulated by
        # the colour attribute it does not supply, which reads as black.
        if hasattr(shader_program, 'set_vertex_color'):
            shader_program.set_vertex_color(
                getattr(self.geometry, 'colors', None) is not None)
        # The same for texture coordinates a generator makes.
        if hasattr(shader_program, 'set_texgen'):
            shader_program.set_texgen(getattr(self.geometry, 'texGen', None),
                                      getattr(mode, 'matrix', None))
        # Water moves on the card: the mesh is uploaded once and the wave
        # is a handful of uniforms. Answered for every shape rather than
        # only by water, or the hillside after a lake would ripple too.
        if hasattr(shader_program, 'set_wave'):
            shader_program.set_wave(
                getattr(self.geometry, 'waveStyle', None) or None,
                float(getattr(self.geometry, 'wave_time', 0.0) or 0.0))
        self.geometry.render(textured=True, mode=mode)

    def _render_shader_appearance(self, mode: Any) -> bool:
        """Draw the geometry through the GLSL program the appearance brings; whether it did

        A `Shader` appearance carries a program instead of a material and a
        texture; an X3D `Appearance` lists shaders, the first that runs
        drawing in place of its material. The appearance's `drawProgram` binds
        the program and gives it its uniforms, and answers what the geometry
        draws into in place of the pass's programs, or None where no program
        of its own runs. The vertex arrays go to the locations
        `OpenGLContext.scenegraph.vertexsemantics` declares, which the
        program's inputs are bound to.
        """
        # What the pass expects bound for the shapes that follow this one; the
        # appearance's program replaces it for one draw and is put back after,
        # the same discipline the raw-GL layers follow.
        previous = mode.current_program() if hasattr(mode, 'current_program') else 0
        pass_program = mode.shader_program
        drawn = self.appearance.drawProgram(mode, self)
        if drawn is None:
            return False
        mode.shader_program = drawn
        try:
            self.geometry.render(textured=True, mode=mode)
        finally:
            mode.shader_program = pass_program
            self.appearance.releaseProgram(drawn, mode)
            if previous:
                glUseProgram(previous)
            # The program may have replaced the textures on the pass's units;
            # the next shape binds its material's again.
            forget = getattr(pass_program, 'release_coverage', None)
            if forget is not None:
                forget()
            elif hasattr(pass_program, '_boundTextures'):
                pass_program._boundTextures = None
        return True

    def RenderTransparent(self, mode: Any) -> Any:
        if not self.geometry:
            return False
        self.publishProperties(mode)

        # Use shader-based rendering if mode is in shader mode
        if getattr(mode, 'shader_mode', False):
            return self._render_shader(mode)

        # Legacy rendering path
        glPushAttrib(GL_LIGHTING_BIT)
        try:
            textureToken = None
            if self.appearance:
                lit, textured, alpha, textureToken = self.appearance.render(mode=mode)
            else:
                lit = 0
                textured = 0
                glColor3f(1, 1, 1)
            if lit and mode.lighting:
                glEnable(GL_LIGHTING)
            else:
                glDisable(GL_LIGHTING)
            ## do the actual work of rendering it transparently...
            self.geometry.render(lit=lit, textured=textured, transparent=1, mode=mode)
            if self.appearance:
                self.appearance.renderPost(textureToken, mode=mode)
        finally:
            glPopAttrib()

    def drawsNothing(self) -> bool:
        """Whether this shape would put nothing on screen this frame.

        A shape that says so is left out of the render set entirely, so it
        costs no world matrix, no frustum test, no sort key and no draw. It is
        asked once per frame per path, so the answer has to be cheap to give.

        This is *not* the same question as an empty bounding volume. A shape may
        have no extent the frustum test can use and still have something to
        draw, and a volume of unknown extent must always be drawn; only the node
        knows which of those it is.
        """
        return False

    def sortKey(self, mode: Any, matrix: Any) -> tuple[Any, ...]:
        """Produce the sorting key for this shape's appearance/shaders/etc"""
        if self.appearance:
            key = self.appearance.sortKey(mode, matrix)
        else:
            key = (False, [], None)
        if not key[0] and getattr(self.geometry, 'softEdges', False):
            # Drawn with anti-aliased edges, as text is: blended with the
            # transparent shapes
            key = (True,) + tuple(key[1:])
        # Only transparent shapes need a real back-to-front distance. Opaque
        # geometry is depth-buffer-correct in any order and every render pass
        # re-sorts by eye-space z anyway, so skip the per-shape projection for
        # opaque -- it dominated frame time on high-part-count scenes.
        if key[0]:
            distance = -float(polygonsort.distances(
                LOCAL_ORIGIN,
                modelView=matrix,
                projection=mode.getProjection(),
                viewport=mode.getViewport(),
            )[0])
        else:
            distance = 0.0
        return tuple(key[0:2]) + (distance,) + tuple(key[1:])

    def meshOrigin(self) -> Any:
        """The point the geometry is drawn relative to, double precision; None for none

        The geometry's `meshOrigin()`: geometry made from double-precision
        coordinates is drawn from the centre of its points
        (:mod:`OpenGLContext.scenegraph.meshgeometry`), and the render pass
        places it by this point in double precision.
        """
        answer = getattr(self.geometry, 'meshOrigin', None) if self.geometry else None
        return answer() if answer is not None else None

    def meshVolume(self, mode: Any) -> Any:
        """The geometry's bounds relative to :meth:`meshOrigin`, where it has one"""
        return self.geometry.meshVolume(mode)

    def boundingVolume(self, mode: Any) -> Any:
        """Create a bounding-volume object for this node

        This is our geometry's boundingVolume, with the
        addition that any dependent volume must be dependent
        on our geometry field.
        """
        current = boundingvolume.getCachedVolume(self)
        if current:
            return current
        if self.geometry:
            if hasattr(self.geometry, "boundingVolume"):
                volume = self.geometry.boundingVolume(mode)
            else:
                # is considered always visible
                volume = boundingvolume.UnboundedVolume()
        else:
            # is never visible
            volume = boundingvolume.BoundingVolume()
        return boundingvolume.cacheVolume(
            self,
            volume,
            ((self, "geometry"), (volume, None)),
        )

    def inFrustum(self, frustum: Any = None, matrix: Any = None,
                  occlusion: int = 0, mode: Any = None) -> Any:
        """Check whether this renderable node intersects frustum

        frustum -- the bounding volume frustum with a planes
            attribute which defines the plane equations for
            each active clipping plane
        matrix -- the active OpenGL transformation matrix for
            this node, used to determine the transforms for
            the grouping-node's bounding volumes.  Is calculated
            from current OpenGL state if not provided.
        """
        try:
            return self.boundingVolume(mode).visible(
                frustum, matrix, occlusion=occlusion, mode=mode
            )
        except Exception:
            tb = traceback.format_exc()
            log.warning("""Failure during Shape.inFrustum check for %r:\n%s""", self, tb)


#: The planes s and t are measured along, by the object-linear and eye-linear generators.
_PLANES = ((GL_S, GL_TEXTURE_GEN_S, (1.0, 0.0, 0.0, 0.0)),
           (GL_T, GL_TEXTURE_GEN_T, (0.0, 1.0, 0.0, 0.0)))


@contextlib.contextmanager
def _fixed_texgen(name: Optional[str]) -> Iterator[None]:
    """Generate the first texture unit's s and t by the ``GL_TEXTURE_GEN_MODE``
    named `name` (:func:`OpenGLContext.scenegraph.texgen.fixed_function`) in
    the block; nothing for None"""
    if name is None:
        yield
        return
    generator = getattr(GL, name)
    for coordinate, switch, plane in _PLANES:
        glTexGeni(coordinate, GL_TEXTURE_GEN_MODE, generator)
        if generator == GL_OBJECT_LINEAR:
            glTexGenfv(coordinate, GL_OBJECT_PLANE, plane)
        elif generator == GL_EYE_LINEAR:
            # An eye plane is taken through the modelview as it is set, so
            # with none it is in the camera's space
            glPushMatrix()
            glLoadIdentity()
            glTexGenfv(coordinate, GL_EYE_PLANE, plane)
            glPopMatrix()
        glEnable(switch)
    try:
        yield
    finally:
        for _coordinate, switch, _plane in _PLANES:
            glDisable(switch)
