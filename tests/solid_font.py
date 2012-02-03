#! /usr/bin/env python
'''Low-level tests of solid fonts'''
from OpenGL.GL import *
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
import _fontstyles#, _ttf_fonts
import sys, os, traceback

## The following makes the toolsfont provider available, toolsfont is dependent
## on the Python fonttools module, which is a cross-platform TTF-file module.
from OpenGLContext.scenegraph.text import toolsfont, fontstyle3d
## The fontprovider.FontProvider class provides the hook for getting a particular
## font-provider implementation
from OpenGLContext.scenegraph.text import fontprovider

MESSAGE = unicode("The quick brown fox jumped over the lazy dog", 'latin-1')

class TestContext( BaseContext ):
    testingClass = None
    currentFont = None
    currentStyle = 0
    def setupFontProviders( self ):
        """Load font providers for the context

        See the OpenGLContext.scenegraph.text package for the
        available font providers.
        """
        fontprovider.setTTFRegistry(
            self.getTTFFiles(),
        )
    def OnInit(self):
        """Get a set of fonts providers for later use"""
        print """You should see a 3D-rendered text message"""
        print '  <n> next fontstyle'
        self.addEventHandler( "keypress", name="n", function = self.OnNextStyle)
        providers = fontprovider.getProviders( 'solid' )
        if not providers:
            raise ImportError( """No solid font providers registered! Demo won't function properly!""" )
        registry = self.getTTFFiles()
        styles = []
        for font in registry.familyMembers( 'SANS' ):
            names = registry.fontMembers( font, 400, 0)
            for name in names:
                styles.append( fontstyle3d.FontStyle3D(
                    family = [name],
                    size = .3,
                    justify = "MIDDLE",
                    thickness = .25,
                    quality = 3,
                    renderSides = 1,
                    renderFront = 1,
                    renderBack = 1,
                ))
        self.styles = styles
        self.setStyle( self.currentStyle )
    def setStyle (self, index = 0):
        """Set the current font style"""
        self.currentStyle = index%(len(self.styles))
        self.currentFont = toolsfont.ToolsSolidFontProvider.get(
            self.styles[self.currentStyle]
        )
    def OnNextStyle( self, event = None):
        """Advance to the next font font style"""
        self.currentStyle += 1
        self.setStyle( self.currentStyle )
        print "New font style: %r"%( self.styles[self.currentStyle],)
        self.triggerRedraw( 1 )
    def Render( self, mode=None ):
        BaseContext.Render( self, mode )
        glTranslate( 0,0,3 )
        glRotate( 80, 0,1,0)
        self.currentFont.render( MESSAGE )
            

if __name__ == "__main__":
    TestContext.ContextMainLoop()

