"""Panoramic image-cube Background node
"""
from OpenGLContext.scenegraph import imagetexture
from OpenGL.arrays import vbo
from OpenGLContext.arrays import array
from vrml import field, protofunctions, fieldtypes, node
from vrml.vrml97 import basenodes, nodetypes

from OpenGL.GL import *
from OpenGLContext.arrays import *
from math import pi

class URLField( fieldtypes.MFString ):
    """Cube-background URL field which forwards to the corresponding ImageTexture node's url
    """
    fieldType = "MFString"
    def fset( self, client, value, notify=1 ):
        value = super( URLField, self).fset( client, value, notify )
        imageObject = getattr(client, self.name[:-3])
        setattr( imageObject, 'url', value )
        return value
    def fdel( self, client, notify=1 ):
        value = super( URLField, self).fdel( client, notify )
        imageObject = getattr(client, self.name[:-3])
        delattr( imageObject, 'url')
        return value

class _CubeBackground( object ):
    right = field.newField('right', 'SFNode', default=imagetexture.ImageTexture)
    top = field.newField('top', 'SFNode', default=imagetexture.ImageTexture)
    back = field.newField('back', 'SFNode', default=imagetexture.ImageTexture)
    left = field.newField('left', 'SFNode', default=imagetexture.ImageTexture)
    front = field.newField('front', 'SFNode', default=imagetexture.ImageTexture)
    bottom = field.newField('bottom', 'SFNode', default=imagetexture.ImageTexture)
    
    rightUrl = URLField( 'rightUrl')
    topUrl = URLField( 'topUrl')
    backUrl = URLField( 'backUrl')
    leftUrl = URLField( 'leftUrl')
    frontUrl = URLField( 'frontUrl')
    bottomUrl = URLField( 'bottomUrl')
    
    bound = field.newField( 'bound', 'SFBool', 1, 0)
    
    def Render( self, mode, clear=1 ):
        """Render the cube background

        This renders those of our cube-faces which are
        facing us, and which have a non-0 component-count.

        After it's finished, it clears the depth-buffer
        to make the geometry appear "behind" everything
        else.
        """
        if mode.passCount == 0:
            glPushAttrib( GL_ALL_ATTRIB_BITS )
            glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
            try:
                glDisable( GL_LIGHTING )
                glDisable( GL_COLOR_MATERIAL )
                if not self.VBO:
                    self.compile( mode )
                if clear:
                    glClear(
                        GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT|GL_STENCIL_BUFFER_BIT
                    )
                # we don't want to do anything with the depth buffer
                # once we've cleared it...
                glDepthMask( GL_FALSE ) 
                matrix = glGetDoublev( GL_MODELVIEW_MATRIX )
                if matrix is None:
                    # glGetDoublev can return None if uninitialised...
                    matrix = identity( 4, 'f')
                forward = dot(matrix, [0,0,-1,0])
                self.VBO.bind()
                glInterleavedArrays( GL_T2F_V3F, 0, self.VBO )
                try:
                    for offset,attr_name, normal, data in self.RENDER_DATA:
                        texture = getattr( self, attr_name )
                        if dot(forward, normal) <=0 and texture.components:
                            # we are facing it, and it's loaded/non-null
                            texture.render(lit=0, mode=mode)
                            try:
                                glDrawArrays( GL_TRIANGLES, offset, 6 )
                            finally:
                                texture.renderPost(mode=mode)
                finally:
                    self.VBO.unbind()
            finally:
                glPopClientAttrib()
                glPopAttrib()
    
    # TODO: should have one-per-context...
    VBO = None
    def compile( self, mode ):
        """Compile a VBO with our various triangles to render"""
        if self.VBO:
            return self.VBO
        def vertices( ):
            for (offset,attr,norm,(a,b,c,d)) in self.RENDER_DATA:
                yield a[1]+a[0]
                yield b[1]+b[0]
                yield c[1]+c[0]
                yield a[1]+a[0]
                yield c[1]+c[0]
                yield d[1]+d[0]
        vb = self.VBO = vbo.VBO(array(list(vertices()),'f'))
        return vb
    RENDER_DATA = [
        (0,'front',(0,0,1,0),[
            ((-1,-1,-1), (0,0)),
            ((1,-1,-1), (1,0)),
            ((1,1,-1), (1,1)),
            ((-1,1,-1), (0,1)),
        ]),
        (6,'right',(-1,0,0,0),[
            ((1,-1,-1), (0,0)),
            ((1,-1,1), (1,0)),
            ((1,1,1), (1,1)),
            ((1,1,-1), (0,1)),
        ]),
        (12,'back', (0,0,-1,0), [
            ((1,-1,1), (0,0)),
            ((-1,-1,1), (1,0)),
            ((-1,1,1), (1,1)),
            ((1,1,1), (0,1)),
        ]),
        (18,'left',(1,0,0,0),[
            ((-1,-1,1), (0,0)),
            ((-1,-1,-1), (1,0)),
            ((-1,1,-1), (1,1)),
            ((-1,1,1), (0,1)),
        ]),
        (24,'bottom',(0,1,0,0),[
            ((-1,-1,1), (0,0)),
            ((1,-1,1), (1,0)),
            ((1,-1,-1), (1,1)),
            ((-1,-1,-1), (0,1)),
        ]),
        (30,'top',(0,-1,0,0),[
            ((-1,1,-1), (0,0)),
            ((1,1,-1), (1,0)),
            ((1,1,1), (1,1)),
            ((-1,1,1), (0,1)),
        ]),
    ]
        

class CubeBackground( _CubeBackground, nodetypes.Background, nodetypes.Children, node.Node  ):
    """Image-cube Background node

    The CubeBackground node implements 1/2 of the VRML97
    background node, particularly the image-cube
    functionality represented by the rightUrl, topUrl,
    backUrl, leftUrl, frontUrl, and bottomUrl fields.

    Fields of note within the CubeBackground object:

        back, front, left, right, top, bottom -- texture
            objects applied to the geometry of the cube.
            Any node which supports the texture API
            should work for these attributes
            
        backUrl, frontUrl, leftUrl, rightUrl, topUrl,
        bottomUrl -- texture urls (MFStrings) used to
            load the images above

    Note: the common practice in 3DSMax for creating
    a cubic environment map produces useful
    background images, but it is often necessary to
    swap left and right images to work with the
    VRML 97 system.
    """
    
