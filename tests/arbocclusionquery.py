#! /usr/bin/env python
'''Tests operation of the OpenGL1.5/ARB Occlusion Query extension
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph import imagetexture, shape, material, appearance, box
from OpenGL.GL import *
from OpenGL.GL.ARB.occlusion_query import *
from OpenGL.extensions import alternate
from OpenGLContext.arrays import array
import string, time, sys

glBeginQuery = alternate( glBeginQuery, glBeginQueryARB )
glDeleteQueries = alternate( glDeleteQueries, glDeleteQueriesARB )
glEndQuery = alternate( glEndQuery, glEndQueryARB )
glGenQueries = alternate( glGenQueries, glGenQueriesARB )
glGetQueryObjectiv = alternate( glGetQueryObjectiv, glGetQueryObjectivARB )
glGetQueryObjectuiv = alternate( glGetQueryObjectiv, glGetQueryObjectuivARB )

images = [
    "nehe_glass.bmp",
    "pimbackground_FR.jpg",
    "nehe_wall.bmp",
]

sizes = [
    (.5,2,.25),
    (1,1,1),
    (2,2,2),
    (3,2,3),
    (4,3,3),
    (3,3,3),
]

class TestContext( BaseContext ):
    currentImage = 0
    currentSize = 0
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        query = glGenQueries(1)
        glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
        glDepthMask(GL_FALSE);
        glBeginQuery(GL_SAMPLES_PASSED, query);
        # we'd want a different non-texture mode here, really...
        self.shape.Render( mode )
        glEndQuery(GL_SAMPLES_PASSED);
        ready = False 
        print 'Waiting for completion of query (normal situation is 8 or 9 wait loop iterations)',
        while not ready:
            ready = glGetQueryObjectiv(query,GL_QUERY_RESULT_AVAILABLE)
            if not ready:
                print '.',
        print
        print 'Fragments affected:', glGetQueryObjectuiv(query, GL_QUERY_RESULT )
        glDeleteQueries( query )

        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glDepthMask(GL_TRUE);
        self.shape.Render( mode )
        
    def OnInit( self ):
        """Scene set up and initial processing"""
        haveExtension = bool(glGenQueries)
        if not haveExtension:
            print 'OpenGL 1.5/GL_ARB_occlusion_query not supported!'
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
        
        print """When the box is offscreen number of pixels should drop to 0
"""
        print 'press i to choose another texture for the box'
        self.addEventHandler(
            'keypress', name = 'i', function = self.OnImageSwitch
        )
        print 'press s to choose another size for the box'
        self.addEventHandler(
            'keypress', name = 's', function = self.OnSizeSwitch
        )
        self.shape = shape.Shape(
            geometry = box.Box( size=sizes[0] ),
            appearance = appearance.Appearance(
                material =material.Material(
                    diffuseColor =(1,1,1)
                ),
                texture = imagetexture.ImageTexture(
                    url = [images[0]]
                ),
            ),
        )
    def OnImageSwitch( self, event=None ):
        """Choose a new mapped texture"""
        self.currentImage = currentImage = self.currentImage+1
        newImage = images[currentImage%len(images)]
        self.shape.appearance.texture.url = [ newImage ]
        print "new image (loading) ->", newImage
    def OnSizeSwitch( self, event=None ):
        """Choose a new size"""
        self.currentSize = currentSize = self.currentSize+1
        newSize = sizes[currentSize%len(sizes)]
        self.shape.geometry.size = newSize
        print "new size ->", newSize
        self.triggerRedraw(1)
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()
