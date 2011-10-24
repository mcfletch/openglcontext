#! /usr/bin/env python
'''Test of texture atlas behaviour...'''
import OpenGL 
OpenGL.FULL_LOGGING = True
from OpenGL.GL import *
from OpenGL.GL import shaders
from OpenGL.arrays import vbo
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
import _fontstyles
import sys, math
from OpenGLContext.scenegraph.text import pygamefont, fontprovider
from OpenGLContext.arrays import zeros, array
from OpenGLContext import texturecache,texture
from OpenGLContext import atlas as atlasmodule
from OpenGLContext.scenegraph.basenodes import *
    
class TestContext( BaseContext ):
    testText = 'Where in the world have you been hiding?'
    _rendered = False
    def OnInit( self ):
        """Initialize the texture atlas test"""
        self.font = pygamefont.PyGameBitmapFont(
            FontStyle(
                family = ["Arial Bold", "Arial", "SANS"],
                justify = ["BEGIN"],
                size = 5.0,
            )
        )
        self.tc = texturecache.TextureCache( atlasSize=256)
        self.maps = {}
        self.box = Box( size=(.5,.5,.5))
        self.shape = Shape(
            geometry = Box( ),
            appearance = Appearance(
            ),
        )
        vertex = shaders.compileShader( '''
            attribute vec2 coord;
            attribute vec2 tex;
            varying vec2 texcoord;
            void main() {
                gl_Position = gl_ModelViewProjectionMatrix * vec4(
                    coord, 0.0, 1.0 
                );
                texcoord = tex;
            }
        ''', GL_VERTEX_SHADER)
        fragment = shaders.compileShader('''
            // render transparency map as texture of given colour
            uniform sampler2D atlas;
            uniform vec3 color;
            varying vec2 texcoord;
            void main() {
                vec4 tex_color = texture(atlas, texcoord );
                if (tex_color.r < .05) {
                    discard;
                }
                gl_FragColor = vec4(
                    color.r,
                    color.g,
                    color.b,
                    tex_color.r
                );
            }
        ''', GL_FRAGMENT_SHADER)
        self.shader = shaders.compileProgram( vertex, fragment )
        self.coord__loc = glGetAttribLocation( self.shader, 'coord' )
        self.tex__loc = glGetAttribLocation( self.shader, 'tex' )
        self.atlas_loc = glGetUniformLocation( self.shader, 'atlas' )
        self.color_loc = glGetUniformLocation( self.shader, 'color' )
        self.vbo = None
        
    def Render( self, mode=None ):
        if mode.visible and not self._rendered:
            self._rendered = True
            for char in self.testText:
                if not char in self.maps:
                    dataArray, metrics = self.font.createCharTexture(
                        char, mode=mode 
                    )
                    dataArray = array( dataArray[:,:,1] )
                    dataArray.shape = dataArray.shape + (1,)
                    map = self.tc.getTexture( dataArray, texture.Texture )
                    self.maps[char] = (map,metrics)
            atlas = self.atlas = self.maps.values()[0][0].atlas
            atlas.render()
            self.img = ImageTexture.forTexture( 
                atlas.texture, mode=mode 
            )
            self.shape.appearance.texture = self.img
            points = zeros( (len(self.testText)*6,4),'f')
            ll = 0,0
            for i,char in enumerate(self.testText):
                map,metrics = self.maps[char]
                # six points for each character...
                coords = map.coords()
                x,y = ll
                w,h = metrics.width/20.,metrics.height/20.
                texcoords = array([
                    [coords[0][0],coords[0][1]],
                    [coords[1][0],coords[0][1]],
                    [coords[1][0],coords[1][1]],
                    [coords[0][0],coords[0][1]],
                    [coords[1][0],coords[1][1]],
                    [coords[0][0],coords[1][1]],
                ],'f')
                vertices = array([
                    (x,y),
                    (x+w,y),
                    (x+w,y+h),
                    (x,y),
                    (x+w,y+h),
                    (x,y+h),
                ],'f')
                j = i*6
                points[j:j+6,2:] = texcoords
                points[j:j+6,:2] = vertices
                ll = (x+w,0)
            self.vbo = vbo.VBO( points )
        self.shape.Render( mode = mode )
        
        if self.vbo is not None:
            glUseProgram( self.shader )
            self.vbo.bind()
            
            glActiveTexture(GL_TEXTURE1)
            glEnable( GL_TEXTURE_2D )
            # atlas.render() doesn't work here, need to fix that!
            self.img.render( visible=True, mode=mode )
            glUniform1i( self.atlas_loc, 1 ) # texture *unit* 0
            glUniform3f( self.color_loc, 1.0, 0.0, 0.0 ) # texture *unit* 0
            
            glEnableVertexAttribArray( self.coord__loc )
            glVertexAttribPointer( 
                self.coord__loc, 
                2, GL_FLOAT,False, 4*4, 
                self.vbo 
            )
            glEnableVertexAttribArray( self.tex__loc )
            glVertexAttribPointer( 
                self.tex__loc, 
                2, GL_FLOAT,False, 4*4, 
                self.vbo+(2*4)
            )
            glDrawArrays(GL_TRIANGLES, 0, 6*len(self.testText))
            self.vbo.unbind()
            glDisableVertexAttribArray( self.coord__loc )
            glDisableVertexAttribArray( self.tex__loc )
            glUseProgram( 0 )
            glDisable( GL_TEXTURE_2D )
            glActiveTexture(GL_TEXTURE0)
        
    def setupFontProviders( self ):
        """Load font providers for the context

        See the OpenGLContext.scenegraph.text package for the
        available font providers.
        """
        fontprovider.setTTFRegistry(
            self.getTTFFiles(),
        )
if __name__ == "__main__":
    TestContext.ContextMainLoop()

