#! /usr/bin/env python
'''Test of text objects with fontprovider
'''
from OpenGL.GL import *
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph.text import glutfont

MESSAGE = """Join the revolution!\nIt will be televised people.\nThere's no excuse."""
SHORT_TEST = "Short Str\nHere"

class TestContext( BaseContext ):
    def OnInit(self):
        """Create the font for use later"""
        self.font = glutfont.GLUTFontProvider.get( FontStyle( family=["Arial","SANS"]))
        self.extraFonts = [
            glutfont.GLUTFontProvider.get( FontStyle( family=family))
            for family in [
                "SANS", "TYPEWRITER", "SERIF",
            ]
        ]
            
    def Render( self, mode=None ):
        BaseContext.Render( self, mode )
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA)
        glTranslate( 0,3.0,0)
        glClearColor( 0,0,0, 0)
        glClear( GL_COLOR_BUFFER_BIT )
        self.font.render( MESSAGE )
        glTranslate( -3,1,0)
        for font in self.extraFonts:
            glTranslate( 0,-1.,0)
            glRasterPos( 0,0,0)
            font.render( SHORT_TEST )

if __name__ == "__main__":
    TestContext.ContextMainLoop()