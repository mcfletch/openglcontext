'''Low-level tests of bitmap-based fonts'''
from OpenGL.GL import *
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
import _fontstyles
import sys

MESSAGE = """Join the revolution!\nIt will be televised people.\nThere's no excuse."""
SHORT_TEST = "Short Str\nHere"
VERTICAL_TEST = "A\nB\nC"

class TestContext( BaseContext ):
    testingClass = None
    def OnInit(self):
        """Create the fonts for use later

        self.font -- single instance of a font
        self.majorFonts -- fonts for 

        """
        if not self.testingClass:
            print """No testingClass defined, nothing to test"""
            sys.exit( 1 )
        self.font = self.testingClass(
        )
        self.majorFonts = [
            self.testingClass( style )
            for style in _fontstyles.majorAlign
        ]
        self.minorFonts = [
            self.testingClass( style )
            for style in _fontstyles.minorAlign
        ]
        self.minorReverseFonts = [
            self.testingClass( style )
            for style in _fontstyles.minorAlignReverse
        ]
            
    def Render( self, mode=None ):
        BaseContext.Render( self, mode )
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA)
        glTranslate( 0,3.0,0)
        glClearColor( 0,0,0, 0)
        glClear( GL_COLOR_BUFFER_BIT )
        glColor( 1, 1, 1 )
        self.font.render( MESSAGE )
        glTranslate( -3,3.5,0)
        for font in self.majorFonts:
            glTranslate( 0,-1.25,0)
            glRasterPos( 0,0,0)
            glEnable( GL_COLOR_MATERIAL )
            glBegin( GL_LINES )
            try:
                glColor( 1.0,0,0 )
                glVertex( 0,0,0 )
                glColor( 0,1.0,0 )
                glVertex( 1,0,0 )
            finally:
                glEnd( )
            font.render( SHORT_TEST )
        glTranslate( 3, (1.25*(len(self.majorFonts)-5)), 0)
        for font in self.minorFonts:
            glTranslate( 1,0,0)
            glRasterPos( 0,0,0)
            glEnable( GL_COLOR_MATERIAL )
            glBegin( GL_LINES )
            try:
                glColor( 1.0,0,0 )
                glVertex( 0,0,0 )
                glColor( 0,1.0,0 )
                glVertex( 1,0,0 )
            finally:
                glEnd( )
            font.render( VERTICAL_TEST )
        
        glTranslate( -1.0*(len(self.minorFonts)), -5, 0)
        for font in self.minorReverseFonts:
            glTranslate( 1,0,0)
            glRasterPos( 0,0,0)
            glEnable( GL_COLOR_MATERIAL )
            glBegin( GL_LINES )
            try:
                glColor( 1.0,0,0 )
                glVertex( 0,0,0 )
                glColor( 0,1.0,0 )
                glVertex( 1,0,0 )
            finally:
                glEnd( )
            font.render( VERTICAL_TEST )

        
            

if __name__ == "__main__":
    TestContext.ContextMainLoop()

