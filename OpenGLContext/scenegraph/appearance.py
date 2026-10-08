"""Appearance node based on VRML 97 model"""
from typing import Any

from vrml.vrml97 import basenodes
from OpenGL.GL import (
    GL_MODULATE, GL_TEXTURE_2D, GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE,
    glBindTexture, glColor3f, glDisable, glEnable, glTexEnvi,
)
from OpenGLContext.arrays import array 
from OpenGLContext.scenegraph import polygonsort
from OpenGLContext.scenegraph.texturelayers import drawn_singly


#: The token ``render`` hands back for a material's own base colour map, which
#: ``renderPost`` unbinds.
_MATERIAL_TEXTURE = object()


class Appearance(basenodes.Appearance):
    """Specifies visual properties for geometry

    The appearance node specifies a set of appearance properties
    to be applied to some number of geometry objects. The Appearance
    node should be managed by a surrounding Shape node which binds
    the Appearance to the appropriate geometry.  Note that multiple
    Shape nodes are likely to use the same Appearance node.

    There are three attributes of note within the appearance object:

        material -- Material node specifying rendering properties
            for the surface that affect the lighting model and
            transparency of the object.  If None, an un-lit material
            (emissive color == 1.0) is used by default.
            
        texture -- (Image)Texture node specifying a 2-D texture
            to apply to the geometry.  If None, no texture is applied.

        textureTransform -- Apply a 2-D transform to texture
            coordinates before texturing.

    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Appearance
    """
    def render (self, mode: Any = None) -> tuple[Any, ...]:
        """Render Appearance, return (lit, textured, alpha, textureToken)

        Renders the appearance node, returning 3 status flags
        and a token which can be used to disable any enabled
        textures.
        
        Should only be called during visible rendering runs
        """
        if self.material:
            lit = 1
            alpha = self.material.render (mode=mode)
        else:
            lit = 0
            alpha = 1
            glColor3f( 1,1,1)
        textureToken = None
        if self.texture:
            textured = 1
            if self.texture.render( lit=lit, mode=mode ):
                if alpha==1.0:
                    alpha = .5
            if self.textureTransform:
                # only need this if we are textured
                textureToken = self.textureTransform.render (mode=mode)
        else:
            textured = 0
            # A glTF material carries its base colour map itself rather than
            # in ``texture``; it modulates the lit colour, as in the shaders.
            legacy = getattr(self.material, 'legacyTexture', None)
            texture = legacy(mode) if legacy is not None else None
            if texture is not None:
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, texture.texture)
                glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
                textured = 1
                textureToken = _MATERIAL_TEXTURE
        return lit, textured, alpha, textureToken
    def renderPost( self, textureToken: Any = None, mode: Any = None ) -> None:
        """Cleanup after rendering of this node has completed"""
        if self.texture:
            if self.textureTransform:
                self.textureTransform.renderPost(textureToken,mode=mode)
            self.texture.renderPost(mode=mode)
        elif textureToken is _MATERIAL_TEXTURE:
            glBindTexture(GL_TEXTURE_2D, 0)
            glDisable(GL_TEXTURE_2D)

    def sortKey( self, mode: Any, matrix: Any ) -> tuple[Any, ...]:
        """Produce the sorting key for this shape's appearance/shaders/etc
        
        key is:
            (
                (not transparent), # opaque first, then transparent...
                distance, # front-to-back for opaque, back-to-front for transparent
                'legacy', 
                textures, # (grouping)
                material-params # (grouping)
            )
        """
        # TODO: this is now pretty expensive, should cache it...
        # The alpha mode decides: only BLEND blends. OPAQUE ignores any alpha,
        # MASK is opaque with a shader discard, and AUTO blends a transparent
        # material or a texture with alpha. Transmissive glass stays opaque
        # here; the transmission pass draws it (see appearance_alpha).
        from OpenGLContext.scenegraph.physicalmaterial import appearance_alpha
        transparent = appearance_alpha(self)[0] == 'BLEND'
        materialParams = None
        textureToken = []
        # A texture the pass draws is asked for as it is drawn, not as it is sorted
        if not transparent and self.texture and not drawn_singly( self.texture ):
            tex = self.texture.cached( mode )
            if tex:
                textureToken = [tex.texture]
        return (
            transparent, textureToken,
            materialParams
        )
    