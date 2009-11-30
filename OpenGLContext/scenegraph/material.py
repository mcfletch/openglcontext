"""Node specifying rendering properties affecting the lighting model"""
from OpenGL.GL import *
from vrml.vrml97 import basenodes
from vrml import protofunctions
from OpenGLContext.arrays import zeros
from vrml import cache
from OpenGLContext import displaylist
import ctypes

class Material(basenodes.Material):
    """Node specifying rendering properties affecting the lighting model

    The Material node specifies a set of properties which affect
    the lighting model applied to the geometry during rendering.
    The Material node should be managed by surrounding Appearance
    node (which should in turn be managed by a surrounding Shape
    node).

    Attributes of note within the Material object:

        diffuseColor -- the "base" color of the material, reflects
            light from OpenGL lights based on the normals of the
            geometry.

        emissiveColor -- the "glow" color of material, present even
            if there's no light in the scene

        specularColor -- determines the color of highlights

        ambientIntensity -- a fraction of the diffuseColor reflected
            from the surface based on the ambient (background)
            lighting in the scene.  Note: OpenGL is capable of
            creating ambient lighting that is not tied to diffuseColor,
            this definition is taken from the VRML 97 specification.

        shininess -- determines the softness and size of highlights,
            higher values make the highlights smaller and sharper.

        transparency -- the inverse of alpha, higher values make the
            geometry more transparent.  Any non-zero transparency value
            will force the use of the transparent sorted geometry
            algorithm, which could be a considerable performance hit
            for large models.

    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Material
    """
    faces = (GL_FRONT_AND_BACK,)*4
    datamap = (GL_DIFFUSE, GL_EMISSION, GL_SPECULAR, GL_AMBIENT)
    def render (
        self,
        mode = None, # the renderpass object
    ):
        """Called by the Appearance node, returns whether we are transparent or not

        This isn't quite right for VRML97, diffuseColor 
        should not be applied in RGB, and neither diffuseColor
        nor transparency should be applied in RGBA, though I
        don't see why it was spec'd that way :( .
        """
        if self.transparency == 1.0:
            #shortcut to eliminate the rendering of invisible geometry
            return 0.0
        quick = mode.cache.getData(self)
        if not quick:
            quick = self.compile( mode=mode )
        if not quick:
            return 1.0
        quick()
        return 1.0 - self.transparency
    def compile( self, mode=None ):
        """Compile material information into readily-rendered format"""
        holder = mode.cache.holder(self, None)
        for field in protofunctions.getFields( self ):
            # change to any field requires a recompile
            holder.depend( self, field )
#		def dl():
        dl = displaylist.DisplayList( )
        dl.start()
        try:
            alpha = 1.0 - self.transparency
            renderingData = zeros( (4,4),'f')
            renderingData[:,3] = alpha
            diffuseColor = self.diffuseColor.astype( 'f' )
            renderingData[0,:3] = diffuseColor
            renderingData[1,:3] = self.emissiveColor.astype( 'f' )
            renderingData[2,:3] = self.specularColor.astype( 'f' )
            renderingData[3,:3] = (diffuseColor*self.ambientIntensity).astype('f')
            map ( glMaterialfv, self.faces, self.datamap, renderingData )
            glMaterialf( self.faces[0], GL_SHININESS, self.shininess*128 )
        finally:
            dl.end()
        holder.data = dl
        return holder.data

    def sortKey( self, mode ):
        """Produce the sorting key for this shape's appearance/shaders/etc
        """
        