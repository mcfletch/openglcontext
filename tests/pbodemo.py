#! /usr/bin/env python
'''Tests/demos pixel-buffer-object operations in OpenGL
'''
import OpenGL 
#OpenGL.USE_ACCELERATE = False
#OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
from OpenGL.GL import *
from OpenGLContext.arrays import array, frombuffer
from OpenGL.arrays import vbo
import string, time
import ctypes,weakref

class TestContext( BaseContext ):
    currentImage = 0
    currentSize = 0
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        self.shape.Render( mode )
        width,height = self.getViewPort()
        self.vbo.bind()
        glReadPixels(
            0, 0, 
            300, 300, 
            GL_RGBA, 
            GL_UNSIGNED_BYTE,
            self.vbo,
        )
        # map_buffer returns an Byte view, we want an 
        # UInt view of that same data...
        data = vbo.mapVBO( self.vbo ).view( 'I' )
        print data
        del data
        self.vbo.unbind()
        
    def OnInit( self ):
        """Scene set up and initial processing"""
        self.vbo = vbo.VBO( 
            None,
            target = GL_PIXEL_PACK_BUFFER,
            usage = GL_DYNAMIC_READ,
            size = 300*300*4,
        )
        self.shape = Shape(
            geometry = Teapot( size=2.5 ),
            appearance = Appearance(
                material = Material(
                    diffuseColor =(1,1,1)
                ),
                texture = ImageTexture(
                    url = ["nehe_wall.bmp"]
                ),
            ),
        )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
