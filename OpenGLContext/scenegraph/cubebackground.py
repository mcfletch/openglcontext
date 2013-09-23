"""Panoramic image-cube Background node
"""
from OpenGLContext.scenegraph import imagetexture
from OpenGL.arrays import vbo
from OpenGLContext.arrays import array
from vrml import field, protofunctions, fieldtypes, node
from vrml.vrml97 import basenodes, nodetypes

from OpenGL.GL import *
from OpenGL.GL import shaders 
from OpenGLContext import texture
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
        delattr( imageObject, 'components' )
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
            render_data = mode.cache.getData(self)
            if render_data is None:
                render_data = self.compile(mode)
                if not render_data:
                    return
            texture, vert_vbo, index_vbo, shader, vertex_loc, mvp_matrix_loc = render_data
            if clear:
                glClear(
                    GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT|GL_STENCIL_BUFFER_BIT
                )
            glDisable( GL_LIGHTING )
            glDisable( GL_COLOR_MATERIAL )
            try:
                with texture:
                    # we don't currently have it handy...
                    with shader:
                        glEnableVertexAttribArray(vertex_loc)
                        with vert_vbo:
                            glVertexAttribPointer(vertex_loc, 3, GL_FLOAT, GL_FALSE, 0, vert_vbo)
                            matrix = dot(mode.matrix,mode.projection)
                            glUniformMatrix4fv(mvp_matrix_loc,1,GL_FALSE,matrix)
                            with index_vbo:
                                # 6 faces, 4 indices each 
                                glDrawElements(GL_QUADS, 24, GL_UNSIGNED_SHORT, index_vbo)
                        glDisableVertexAttribArray(vertex_loc)
            finally:
                glDepthMask( GL_TRUE ) 
                glEnable( GL_LIGHTING )
                glEnable( GL_COLOR_MATERIAL )
    
    CUBE_VERTICES =  array([
        -100.0,  100.0,  100.0,
        -100.0, -100.0,  100.0,
        100.0, -100.0,  100.0,
        100.0,  100.0,  100.0,
        -100.0,  100.0, -100.0,
        -100.0, -100.0, -100.0,
        100.0, -100.0, -100.0,
        100.0,  100.0, -100.0,
    ],'f')
    CUBE_INDICES = array([
        3,2,1,0,
        0,1,5,4,
        7,6,2,3,
        4,5,6,7,
        4,7,3,0,
        1,2,6,5,
    ],'H')

    # TODO: should have one-per-context...
    def compile( self, mode ):
        """Compile a VBO with our various triangles to render"""
        images = {
            '-x':self.left,
            '+x':self.right,
            '+y':self.top,
            '-y':self.bottom,
            '-z':self.front,
            '+z':self.back,
        }
        def all_same( key ):
            current = None
            for k,value in images.items():
                new = getattr(value,key)
                if current is None:
                    current = new 
                else:
                    if new != current:
                        return False 
            return True
        if not all_same( 'components' ):
            return None 
        tex = texture.CubeTexture( )
        tex.fromPIL( [(k,i.image) for k,i in images.items()] )
        
        vert_vbo = vbo.VBO( self.CUBE_VERTICES )
        index_vbo = vbo.VBO( self.CUBE_INDICES, target=GL_ELEMENT_ARRAY_BUFFER )
        # this shader is from 
        shader = shaders.compileProgram(
            shaders.compileShader(
                '''#version 330
    in vec3 vertex;
    out vec3 texCoord;
    uniform mat4 mvp_matrix;

    void main() {
        gl_Position = mvp_matrix * vec4( vertex, 1.0);
        texCoord = normalize(vertex);
    }''', GL_VERTEX_SHADER ),
            shaders.compileShader(
                '''#version 330
    in vec3 texCoord;
    out vec4 fragColor;
    uniform samplerCube cube_map;

    void main( ) {
        fragColor = texture(cube_map, texCoord);
    }''', GL_FRAGMENT_SHADER ),
        )
        vertex_loc = glGetAttribLocation( shader, 'vertex' )
        mvp_matrix_loc = glGetUniformLocation( shader, 'mvp_matrix' )
        render_data = (tex, vert_vbo, index_vbo, shader, vertex_loc, mvp_matrix_loc)
        if hasattr(mode,'cache'):
            holder = mode.cache.holder( self, render_data )
            for key in ('right','left','top','bottom','front','back'):
                holder.depend( self, key+'Url' )
        return render_data

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
    
