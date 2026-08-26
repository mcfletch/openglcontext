"""Renderable geometry composed of a geometry object with applied appearance"""

from OpenGL.GL import *
from vrml.vrml97 import basenodes
from vrml import field
from OpenGLContext.scenegraph import boundingvolume, polygonsort
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

    def Render(self, mode=None):
        """Do run-time rendering of the Shape for the given mode"""
        if not self.geometry:
            return

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
                self.geometry.render(lit=lit, textured=textured, mode=mode)
                if textured:
                    self.appearance.renderPost(textureToken, mode=mode)
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

    def _render_shader(self, mode):
        """Render using shader-based pipeline.

        Sets up material and texture uniforms on the shader, then
        calls geometry's render method (which will use shader path).
        """
        from OpenGLContext.passes.shaderpass import (
            appearance_solid_color,
            configure_material_from_node,
        )

        shader_program = getattr(mode, 'shader_program', None)
        if shader_program is None:
            return

        # Shadow depth pass: only positions matter, skip appearance/material/texture.
        # Matrices and program are configured by the shadow pass itself.
        if getattr(mode, 'shadow_pass', False):
            self.geometry.render(textured=False, mode=mode)
            return

        # The one colour geometry with no material of its own is drawn in --
        # a line, a point cloud. Published here because the appearance belongs
        # to the shape and the geometry node does not see it.
        mode._solid_color = appearance_solid_color(self.appearance)

        # PBR program: it configures its own material + texture maps (and
        # up-converts VRML97 Material), then we just render the geometry.
        if getattr(mode, 'visible', True) and hasattr(shader_program, 'configure_appearance'):
            shader_program.configure_appearance(self.appearance, mode)
            # Whether the base colour is modulated by a per-vertex colour is one
            # uniform for the whole pass, so it is answered for every shape
            # rather than only by the geometry that has colours: a box drawn
            # after a vertex-coloured terrain would otherwise be modulated by
            # the colour attribute it does not supply, which reads as black.
            if hasattr(shader_program, 'set_vertex_color'):
                shader_program.set_vertex_color(
                    getattr(self.geometry, 'colors', None) is not None)
            # Water moves on the card: the mesh is uploaded once and the wave
            # is a handful of uniforms. Answered for every shape rather than
            # only by water, or the hillside after a lake would ripple too.
            if hasattr(shader_program, 'set_wave'):
                shader_program.set_wave(
                    getattr(self.geometry, 'wave_style', None),
                    float(getattr(self.geometry, 'wave_time', 0.0) or 0.0))
            self.geometry.render(textured=True, mode=mode)
            return

        if self.appearance and not hasattr(self.appearance, 'texture'):
            # A `Shader` appearance carries a GLSL program of its own instead of
            # a texture, and draws through the fixed-function vertex arrays that
            # program's `gl_Vertex` reads.  Core-profile geometry is submitted
            # through a vertex array object at attribute locations such a shader
            # would have to declare, so this pass has nothing to hand it.  Said
            # once here rather than as an AttributeError per shape per frame.
            raise NotImplementedError(
                "a %s appearance draws only in the compatibility profile; declare"
                " profile = 'compatibility' on the context that uses it"
                % (self.appearance.__class__.__name__,))

        # Skip material/texture setup during selection rendering (mode.visible=False)
        # Selection uses solid colors with unlit shader, not materials
        textured = False
        if getattr(mode, 'visible', True):
            # Set up material properties
            if self.appearance and self.appearance.material:
                configure_material_from_node(shader_program, self.appearance.material)
            else:
                shader_program.set_default_material()

            # Set up texture if present
            if self.appearance and self.appearance.texture:
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

        # Render the geometry (it will detect shader_mode and use shader path)
        self.geometry.render(textured=textured, mode=mode)

        # Cleanup texture
        if textured:
            shader_program.unbind_texture()

    def RenderTransparent(self, mode):
        if not self.geometry:
            return False

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

    def drawsNothing(self):
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

    def sortKey(self, mode, matrix):
        """Produce the sorting key for this shape's appearance/shaders/etc"""
        if self.appearance:
            key = self.appearance.sortKey(mode, matrix)
        else:
            key = (False, [], None)
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
        return key[0:2] + (distance,) + key[1:]

    def boundingVolume(self, mode):
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

    def visible(self, frustum=None, matrix=None, occlusion=0, mode=None):
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
        except Exception as err:
            tb = traceback.format_exc()
            log.warning("""Failure during Shape.visible check for %r:\n%s""", self, tb)
