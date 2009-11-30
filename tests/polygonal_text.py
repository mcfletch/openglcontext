#! /usr/bin/env python
# -*- coding: latin-1 -*-
"""Various docs of interest:

Geometry of the outlines:
    http://www.truetype.demon.co.uk/ttoutln.htm
"""

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.arrays import *
from OpenGL.GL import *
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph.text import toolsfont

class TestContext( BaseContext ):
    scale = 400.0
    sourceString = "Hello world (composites: ëé¿á)"
    font = None
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        if self.font:
            #glScaled( .01, .01, .01 )
            glEnable( GL_COLOR_MATERIAL )
            glRotate( 30,0,1,0)
            glPointSize( 4)
            #glDisable( GL_CULL_FACE )
            glColor3f( 0.0,0.0,.75)
            # draw the baseline for the font extending to the left
            glBegin( GL_LINES )
            try:
                glColor3f( 1.0,0,0)
                glVertex( 0,0,0 )
                glColor3f( 0.0,1.0,0)
                glVertex( -1,0,0 )
            finally:
                glEnd()
            for character in self.sourceString:
                glyph = self.font.getGlyph( character )
                glColor3f( 1.0,0,0)
                glyph.renderCap( self.scale )
                glyph.renderExtrusion( self.scale )
                glyph.renderCap( self.scale, front=0 )
                #glyph.renderContours( self.scale)
                glyph.renderAdvance(self.scale)
            
    def OnInit( self ):
        """Load the image on initial load of the application"""
        registry = self.getTTFFiles()
        if registry:
            filenames = registry.files.keys()
            if filenames:
                self.font = toolsfont._SolidFont(filenames[0])

                
if __name__ == "__main__":
    TestContext.ContextMainLoop()
