#! /usr/bin/env python
'''Test of text objects
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import *
import string, time, sys, os
import logging
log = logging.getLogger( __name__ )

from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph.text import fontprovider

class TestContext( BaseContext ):
    currentStyle = -1
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        for shape in self.shapes:
            mode.visit( shape )
    def setupFontProviders( self ):
        """Load font providers for the context

        See the OpenGLContext.scenegraph.text package for the
        available font providers.
        """
        from OpenGLContext.scenegraph.text import fontprovider
        try:
            from OpenGLContext.scenegraph.text import toolsfont
            registry = self.getTTFFiles()
        except ImportError, err:
            log.warn( """Unable to import fonttools-based TTF-file registry, no TTF font support!""" )
        else:
            fontprovider.setTTFRegistry(
                registry,
            )
            self.families = registry.DEFAULT_FAMILY_SETS.keys()
            self.families.sort()
            self.family = self.families[0]
        try:
            from OpenGLContext.scenegraph.text import pygamefont
        except ImportError:
            log.warn( """Unable to import PyGame TTF-font renderer, no PyGame anti-aliased font support!""" )
        try:
            from OpenGLContext.scenegraph.text import glutfont
        except ImportError:
            log.warn( """Unable to import GLUT-based TTF-file registry, no GLUT bitmap font support!""" )
    def OnInit( self ):
        print """You should see a 3D-rendered text message"""
        print '  <p> previous fontstyle'
        print '  <n> next fontstyle'
        print '  <f> next font-family'
        print '  <d> set current font as default font for family'
        self.addEventHandler( "keypress", name="n", function = self.OnNextStyle)
        self.addEventHandler( "keypress", name="p", function = self.OnPreviousStyle)
        self.addEventHandler( "keypress", name="d", function = self.OnSetDefault)
        self.addEventHandler( "keypress", name="f", function = self.OnNextFamily)
        self.currentDefault = FontStyle(
            justify = "MIDDLE",
            family = [self.family],
        )
        self.currentDisplay = FontStyle(
            justify = "MIDDLE",
        )
        self.defaultText = Text(
            string=["Current Default"],
            fontStyle = self.currentDefault,
        )
        self.displayText = Text(
            string=["Hello World!", "VRML97 Text"],
            fontStyle = self.currentDisplay,
        )
        self.sg = sceneGraph(
            children = [
                Transform(
                    translation = (0,3,0),
                    children = [
                        Shape(
                            geometry = self.defaultText,
                            appearance = Appearance(
                                material = Material(
                                    diffuseColor = (.3,.2,.8),
                                    shininess = .1,
                                ),
                            ),
                        ),
                    ],
                ),
                Shape(
                    geometry = self.displayText,
                    appearance = Appearance(
                        material = Material(
                            diffuseColor = (.3,.2,.8),
                            shininess = .1,
                        ),
                    ),
                ),
            ]
        )
        self.buildStyles()
    def buildStyles( self ):
        """Build the set of styles from which to choose"""
        try:
            self.styles = self.getTTFFiles().familyMembers( self.family )
        except ImportError:
            self.styles = ['SERIF','SANS','TYPEWRITER']
        if self.styles:
            self.currentDefaultName = (
                self.getDefaultTTFFont( self.family ) or
                self.styles[0]
            )
            self.defaultDisplayText()
        if self.currentDefaultName in self.styles:
            index = self.styles.index( self.currentDefaultName )
        else:
            index = 0
        self.setStyle( index )
    def setStyle (self, index = 0):
        """Set the current font style"""
        if self.styles:
            self.currentStyle = index%(len(self.styles))
            name = self.styles[self.currentStyle]
            self.currentDisplay.family = [name, ]
            #self.sg.children[1].geometry.fontStyle = self.currentDisplay
            #print 'node', repr(self.sg.children[1].geometry)
            assert not self.cache.getData( self.sg.children[1].geometry ), """Cache wasn't cleared for the text node"""
        self.mainDisplayText()
    def OnPreviousStyle( self, event = None):
        """Advance to the next font font style"""
        self.currentStyle -= 1
        if not self.currentStyle % 20:
            providers = fontprovider.FontProvider.getProviders( self.currentStyle )
            for provider in providers:
                provider.clear()
        self.setStyle( self.currentStyle )
        self.triggerRedraw( 1 )
    def OnNextStyle( self, event = None):
        """Advance to the next font font style"""
        self.currentStyle += 1
        if not self.currentStyle % 20:
            providers = fontprovider.FontProvider.getProviders( self.currentStyle )
            for provider in providers:
                provider.clear()
        self.setStyle( self.currentStyle )
        self.triggerRedraw( 1 )
    def OnSetDefault( self, event = None ):
        """Set default font for OpenGLContext to currently displayed"""
        if self.styles:
            name = self.currentDisplay.family[0]
            self.setDefaultTTFFont( name, type=self.family )
            self.currentDefaultName = name
            self.defaultDisplayText()
        self.triggerRedraw(1)
    def OnNextFamily( self, event=None ):
        """Choose the next font-family to display"""
        index = self.families.index( self.family )
        index += 1
        index = index %len(self.families)
        self.family = self.families[index]
        self.buildStyles()

        self.triggerRedraw(1)


    def mainDisplayText( self ):
        """Decide on what text to display in the main text area"""
        base = []
        if self.styles:
            base.append(  "Hello World!" )
            base.append( self.styles[self.currentStyle] )
            base.append( '(%s)'%( self.family ))
        else:
            base.extend( ['No', repr(self.family), 'fonts available'])
        self.displayText.string = base
        return base
    def defaultDisplayText( self ):
        self.currentDefault.family = [
            self.currentDefaultName
        ]
        self.defaultText.string = [
            'Current Default',
            self.currentDefaultName
        ]
        
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()
