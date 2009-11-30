#! /usr/bin/env python
'''Test of text objects with fontprovider
'''
from OpenGL.GL import *
from OpenGLContext import wxtestingcontext
import wx
BaseContext = wxtestingcontext.BaseContext
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph.text import wxfont
from OpenGLContext.debug import logcontext
import _fontstyles
MESSAGE = """Join the revolution!\nIt will be televised people.\nThere's no excuse."""
SHORT_TEST = "Short Str\nHere"
VERTICAL_TEST = "A\nB\nC"

class TestContext( BaseContext ):
    def OnInit(self):
        """Create the font for use later"""
        wx.InitAllImageHandlers()
        self.font = wxfont.wxBitmapFont(
            FontStyle( size = 1.5 ),
        )
        #~ self.list0 = displaylist.DisplayList()
    def Render( self, mode=None ):
        BaseContext.Render( self, mode )
        #logcontext.logContext()
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA)
        #~ glTranslate( 0,3.0,0)
        #~ self.font.createCharTexture('a')
        glClearColor( 1,0,0, 0)
        glClear( GL_COLOR_BUFFER_BIT )
        #~ glRasterPos( 0,0,0)
        #~ rpixels()
        #~ self.list = displaylist.DisplayList()
        #~ self.list.start()
        #~ rpixels()
        #~ self.list.end()
        #~ self.list()
        #~ import pdb
        #~ pdb.set_trace()
        self.font.render( "Look, some wxPython text!" )
            

def rpixels():
    glDrawPixels (
        6, 12, 6410, 5121, 
        '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    )


if __name__ == "__main__":
    TestContext.ContextMainLoop()

