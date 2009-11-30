"""Appearance node based on VRML 97 model"""
from vrml.vrml97 import basenodes
from OpenGL.GL import glColor3f
from OpenGLContext.arrays import array 
from OpenGLContext.scenegraph import polygonsort


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
    def render (self, mode=None):
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
        return lit, textured, alpha, textureToken
    def renderPost( self, textureToken=None, mode=None ):
        """Cleanup after rendering of this node has completed"""
        if self.texture:
            if self.textureTransform:
                self.textureTransform.renderPost(textureToken,mode=mode)
            self.texture.renderPost(mode=mode)

    def sortKey( self, mode, matrix ):
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
        if self.material:
            #materialParams = self.material.sortKey( mode )
            materialParams = None
            transparent = bool(self.material.transparency)
        else:
            transparent = False
            materialParams = None
        textureToken = []
        # correctness of rendering requires the back-to-front 
        # rendering for transparent textures...
        if not transparent:
            if self.texture:
                transparent = transparent or self.texture.transparent( mode )
                tex = self.texture.cached( mode )
                if tex:
                    textureToken = [tex.texture]
        return (
            transparent, textureToken,
            materialParams
        )
    